"""SQLite com WAL, mmap, UTXO set, mempool persistente e poda."""
import sqlite3
import zlib
import time
import threading
import orjson

class ChainDB:
    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        for p in (
            "PRAGMA journal_mode=WAL",
            "PRAGMA synchronous=NORMAL",
            "PRAGMA temp_store=MEMORY",
            "PRAGMA cache_size=-20000",
            "PRAGMA mmap_size=268435456",
            "PRAGMA foreign_keys=ON",
        ):
            self.conn.execute(p)
        self._schema()

    def _schema(self):
        with self.lock:
            self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS blocks (
                height     INTEGER PRIMARY KEY,
                hash       TEXT UNIQUE NOT NULL,
                prev_hash  TEXT NOT NULL,
                timestamp  INTEGER NOT NULL,
                nonce      INTEGER NOT NULL,
                merkle     TEXT NOT NULL,
                difficulty INTEGER NOT NULL,
                raw        BLOB NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_blocks_hash ON blocks(hash);
            CREATE INDEX IF NOT EXISTS idx_blocks_prev ON blocks(prev_hash);

            CREATE TABLE IF NOT EXISTS transactions (
                txid         TEXT PRIMARY KEY,
                block_height INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tx_block ON transactions(block_height);

            CREATE TABLE IF NOT EXISTS utxos (
                txid         TEXT NOT NULL,
                vout         INTEGER NOT NULL,
                address      TEXT NOT NULL,
                amount       INTEGER NOT NULL,
                pubkey       TEXT NOT NULL,
                block_height INTEGER NOT NULL,
                spent        INTEGER NOT NULL DEFAULT 0,
                spent_by     TEXT,
                PRIMARY KEY (txid, vout)
            );
            CREATE INDEX IF NOT EXISTS idx_utxo_addr  ON utxos(address, spent);
            CREATE INDEX IF NOT EXISTS idx_utxo_spent ON utxos(spent);
            CREATE INDEX IF NOT EXISTS idx_utxo_h     ON utxos(block_height);

            CREATE TABLE IF NOT EXISTS mempool (
                txid        TEXT PRIMARY KEY,
                raw         BLOB NOT NULL,
                fee         INTEGER NOT NULL,
                received_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_mp_fee  ON mempool(fee DESC);
            CREATE INDEX IF NOT EXISTS idx_mp_time ON mempool(received_at);

            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """)

    # ---------- blocos ----------
    def add_block(self, block: dict):
        with self.lock:
            blob = zlib.compress(orjson.dumps(block), level=6)
            self.conn.execute(
                "INSERT INTO blocks(height,hash,prev_hash,timestamp,nonce,merkle,difficulty,raw)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (block["height"], block["hash"], block["prev_hash"],
                 block["timestamp"], block["nonce"], block["merkle"],
                 block["difficulty"], blob),
            )
            for tx in block["transactions"]:
                self.conn.execute(
                    "INSERT OR REPLACE INTO transactions(txid,block_height) VALUES (?,?)",
                    (tx["txid"], block["height"]),
                )

    def get_block(self, height: int) -> dict | None:
        row = self.conn.execute("SELECT raw FROM blocks WHERE height=?", (height,)).fetchone()
        return orjson.loads(zlib.decompress(row["raw"])) if row else None

    def get_block_by_hash(self, h: str) -> dict | None:
        row = self.conn.execute("SELECT raw FROM blocks WHERE hash=?", (h,)).fetchone()
        return orjson.loads(zlib.decompress(row["raw"])) if row else None

    def height(self) -> int:
        row = self.conn.execute("SELECT MAX(height) AS h FROM blocks").fetchone()
        return int(row["h"]) if row and row["h"] is not None else -1

    def tip(self) -> dict | None:
        row = self.conn.execute(
            "SELECT hash,prev_hash FROM blocks ORDER BY height DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def tip_hash(self) -> str:
        t = self.tip()
        return t["hash"] if t else "0" * 64

    def headers(self, start: int, limit: int = 2000) -> list[dict]:
        rows = self.conn.execute(
            "SELECT height,hash,prev_hash,timestamp,nonce,merkle,difficulty"
            " FROM blocks WHERE height>=? ORDER BY height LIMIT ?",
            (start, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- UTXO ----------
    def balance(self, address: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(amount),0) AS s FROM utxos WHERE address=? AND spent=0",
            (address,),
        ).fetchone()
        return int(row["s"])

    def utxos_for(self, address: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT txid,vout,amount,pubkey FROM utxos"
            " WHERE address=? AND spent=0 ORDER BY amount DESC",
            (address,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_utxo(self, txid: str, vout: int) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM utxos WHERE txid=? AND vout=? AND spent=0", (txid, vout)
        ).fetchone()
        return dict(row) if row else None

    def apply_tx(self, tx: dict, height: int, coinbase: bool = False):
        with self.lock:
            if not coinbase:
                for inp in tx["inputs"]:
                    self.conn.execute(
                        "UPDATE utxos SET spent=1, spent_by=? WHERE txid=? AND vout=? AND spent=0",
                        (tx["txid"], inp["txid"], inp["vout"]),
                    )
            for i, out in enumerate(tx["outputs"]):
                self.conn.execute(
                    "INSERT OR REPLACE INTO utxos"
                    "(txid,vout,address,amount,pubkey,block_height,spent)"
                    " VALUES (?,?,?,?,?,?,0)",
                    (tx["txid"], i, out["address"], out["amount"],
                     out.get("pubkey", ""), height),
                )

    def rollback_block(self, height: int):
        """Desfaz bloco (usado em reorg)."""
        with self.lock:
            block = self.get_block(height)
            if not block:
                return
            for tx in reversed(block["transactions"]):
                for i, out in enumerate(tx["outputs"]):
                    self.conn.execute(
                        "DELETE FROM utxos WHERE txid=? AND vout=?", (tx["txid"], i)
                    )
                if block["height"] > 0:
                    for inp in tx.get("inputs", []):
                        if inp["txid"] == "0" * 64:
                            continue
                        self.conn.execute(
                            "UPDATE utxos SET spent=0, spent_by=NULL WHERE txid=? AND vout=?",
                            (inp["txid"], inp["vout"]),
                        )
                self.conn.execute("DELETE FROM transactions WHERE txid=?", (tx["txid"],))
            self.conn.execute("DELETE FROM blocks WHERE height=?", (height,))

    # ---------- mempool ----------
    def add_mempool(self, tx: dict, fee: int) -> bool:
        with self.lock:
            try:
                self.conn.execute(
                    "INSERT INTO mempool(txid,raw,fee,received_at) VALUES (?,?,?,?)",
                    (tx["txid"], zlib.compress(orjson.dumps(tx)), fee, time.time()),
                )
            except sqlite3.IntegrityError:
                return False
            self._prune_mempool()
            return True

    def _prune_mempool(self, max_size=1000, ttl=3600):
        self.conn.execute("DELETE FROM mempool WHERE received_at < ?", (time.time() - ttl,))
        n = self.conn.execute("SELECT COUNT(*) AS c FROM mempool").fetchone()["c"]
        if n > max_size:
            self.conn.execute("""
                DELETE FROM mempool WHERE txid IN (
                    SELECT txid FROM mempool ORDER BY fee ASC, received_at ASC LIMIT ?
                )
            """, (n - max_size,))

    def has_mempool(self, txid: str) -> bool:
        return self.conn.execute("SELECT 1 FROM mempool WHERE txid=?", (txid,)).fetchone() is not None

    def get_mempool_tx(self, txid: str) -> dict | None:
        row = self.conn.execute("SELECT raw FROM mempool WHERE txid=?", (txid,)).fetchone()
        return orjson.loads(zlib.decompress(row["raw"])) if row else None

    def all_mempool(self, limit: int = 1000) -> list[dict]:
        rows = self.conn.execute(
            "SELECT raw FROM mempool ORDER BY fee DESC LIMIT ?", (limit,)
        ).fetchall()
        return [orjson.loads(zlib.decompress(r["raw"])) for r in rows]

    def remove_mempool(self, txid: str):
        with self.lock:
            self.conn.execute("DELETE FROM mempool WHERE txid=?", (txid,))

    # ---------- poda / snapshot ----------
    def prune_spent_utxos(self, keep_height: int = 1000) -> int:
        cutoff = max(0, self.height() - keep_height)
        with self.lock:
            n = self.conn.execute(
                "DELETE FROM utxos WHERE spent=1 AND block_height < ?", (cutoff,)
            ).rowcount
        return n

    def snapshot_utxo(self, path: str = "utxo_snapshot.db"):
        with self.lock:
            snap = sqlite3.connect(path)
            snap.execute("DROP TABLE IF EXISTS utxos")
            snap.execute("CREATE TABLE utxos AS SELECT * FROM utxos WHERE spent=0")
            snap.commit()
            snap.close()

    def count_utxos(self) -> int:
        return self.conn.execute("SELECT COUNT(*) AS c FROM utxos WHERE spent=0").fetchone()["c"]

    # ---------- meta ----------
    def set_meta(self, key: str, value: str):
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)", (key, value))

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def close(self):
        self.conn.close()