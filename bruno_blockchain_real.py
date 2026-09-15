
import hashlib
import json
import time
import secrets
import threading
import sqlite3
import os
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Set
from cripto_wallet import WalletManager
from assets import (AssetRegistry, AssetDefinition, ComplianceRecord,
                    TransferRule, ASSET_TYPES, KYC_STATUS, KYC_LEVELS)

NETWORK_ID = os.environ.get("BRN_NETWORK_ID", "brn-rwa-1")
BLOCK_REWARD = float(os.environ.get("BRN_BLOCK_REWARD", "1"))
MIN_STAKE = float(os.environ.get("BRN_MIN_STAKE", "100"))
DB_PATH = os.environ.get("BRN_DB_PATH", "blockchain.db")
FINALITY_INTERVAL = int(os.environ.get("BRN_FINALITY_INTERVAL", "5"))
FINALITY_THRESHOLD = float(os.environ.get("BRN_FINALITY_THRESHOLD", "0.67"))
FAUCET_ADDRESS = os.environ.get("BRN_FAUCET_ADDRESS", "").strip()
FAUCET_AMOUNT = float(os.environ.get("BRN_FAUCET_AMOUNT", "100"))
FAUCET_COOLDOWN = int(os.environ.get("BRN_FAUCET_COOLDOWN", "3600"))
REGULATOR_ADDRESS = os.environ.get("BRN_REGULATOR_ADDRESS", "").strip()
NATIVE_ASSET = "BRN"
NATIVE_ASSET_ISSUER = "brn1" + "0" * 40

_raw = os.environ.get("BRN_GENESIS_ALLOC", "").strip()
GENESIS_ALLOCATIONS: Dict[str, Dict[str, float]] = {}
if _raw:
    for pair in _raw.split(","):
        parts = pair.split(":")
        if len(parts) == 3:
            try:
                GENESIS_ALLOCATIONS.setdefault(parts[0].strip(), {})[parts[1].strip()] = float(parts[2].strip())
            except ValueError:
                pass


@dataclass
class Block:
    index: int
    timestamp: float
    previous_hash: str
    transactions: List[dict]
    validator: str
    validator_public_key: str = ""
    nonce: int = 0
    signature: str = ""
    hash: str = ""
    registry_snapshot: Optional[dict] = None

    def calculate_hash(self):
        body = {"index": self.index, "timestamp": self.timestamp,
                "previous_hash": self.previous_hash,
                "transactions": self.transactions,
                "validator": self.validator,
                "validator_public_key": self.validator_public_key,
                "nonce": self.nonce, "network_id": NETWORK_ID,
                "registry_hash": self._registry_hash()}
        return hashlib.sha3_256(json.dumps(body, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()

    def _registry_hash(self):
        if not self.registry_snapshot: return ""
        return hashlib.sha3_256(json.dumps(self.registry_snapshot,
                                            sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()

    def finalize(self): self.hash = self.calculate_hash()

    def sign(self, sk_hex):
        if not self.hash: self.finalize()
        self.signature = WalletManager.sign_transaction(
            sk_hex, {"block_hash": self.hash, "index": self.index})

    def verify(self):
        if self.hash != self.calculate_hash(): return False
        if self.index == 0: return True
        if not self.validator_public_key or not self.signature: return False
        if WalletManager.address_from_public_key(self.validator_public_key) != self.validator:
            return False
        return WalletManager.verify_signature(
            self.validator_public_key,
            {"block_hash": self.hash, "index": self.index},
            self.signature)

    def to_dict(self): return asdict(self)

    @classmethod
    def from_dict(cls, d): return cls(**d)


class Transaction:
    REQUIRED_FIELDS = {"type", "asset_id", "from", "to", "amount",
                       "nonce", "public_key", "signature"}
    VALID_TYPES = {"transfer", "issue", "redeem", "freeze", "unfreeze",
                   "kyc_register", "kyc_revoke", "asset_create",
                   "asset_update", "dividend"}

    @staticmethod
    def build(tx_type, asset_id, sender_address, receiver_address, amount,
              nonce, private_key_hex, public_key_hex, metadata=None):
        if tx_type not in Transaction.VALID_TYPES:
            raise ValueError(f"Tipo invalido: {tx_type}")
        if amount < 0: raise ValueError("Valor negativo.")
        if tx_type == "transfer" and sender_address == receiver_address:
            raise ValueError("Remetente = destinatario.")
        tx = {"type": tx_type, "asset_id": asset_id, "from": sender_address,
              "to": receiver_address, "amount": float(amount),
              "nonce": int(nonce), "public_key": public_key_hex,
              "timestamp": time.time(), "metadata": metadata or {}}
        tx["signature"] = WalletManager.sign_transaction(private_key_hex, tx)
        return tx

    @staticmethod
    def verify_signature(tx):
        if not Transaction.REQUIRED_FIELDS.issubset(tx.keys()): return False
        payload = {k: v for k, v in tx.items() if k != "signature"}
        return WalletManager.verify_signature(tx["public_key"], payload,
                                              tx["signature"])

    @staticmethod
    def derived_address(tx):
        return WalletManager.address_from_public_key(tx["public_key"])

    @staticmethod
    def hash(tx):
        return hashlib.sha3_256(json.dumps(tx, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()


class State:
    def __init__(self):
        self.balances: Dict[str, Dict[str, float]] = {}
        self.nonces: Dict[str, int] = {}
        self.frozen: Dict[str, Dict[str, float]] = {}
        self.total_supply: Dict[str, float] = {}

    def balance(self, addr, asset_id=NATIVE_ASSET):
        return self.balances.get(addr, {}).get(asset_id, 0.0)

    def available(self, addr, asset_id):
        return self.balance(addr, asset_id) - self.frozen.get(addr, {}).get(asset_id, 0.0)

    def nonce(self, addr): return self.nonces.get(addr, 0)

    def credit(self, addr, asset_id, amount):
        self.balances.setdefault(addr, {})
        self.balances[addr][asset_id] = self.balances[addr].get(asset_id, 0.0) + amount
        self.total_supply[asset_id] = self.total_supply.get(asset_id, 0.0) + amount

    def debit(self, addr, asset_id, amount):
        self.balances.setdefault(addr, {})
        self.balances[addr][asset_id] = self.balances[addr].get(asset_id, 0.0) - amount
        self.total_supply[asset_id] = self.total_supply.get(asset_id, 0.0) - amount

    def freeze(self, addr, asset_id, amount):
        self.frozen.setdefault(addr, {})
        self.frozen[addr][asset_id] = self.frozen[addr].get(asset_id, 0.0) + amount

    def unfreeze(self, addr, asset_id, amount):
        self.frozen.setdefault(addr, {})
        self.frozen[addr][asset_id] = max(0.0,
            self.frozen[addr].get(asset_id, 0.0) - amount)

    def copy(self):
        s = State()
        s.balances = {a: dict(v) for a, v in self.balances.items()}
        s.nonces = dict(self.nonces)
        s.frozen = {a: dict(v) for a, v in self.frozen.items()}
        s.total_supply = dict(self.total_supply)
        return s


class Finality:
    def __init__(self, interval=FINALITY_INTERVAL, threshold=FINALITY_THRESHOLD):
        self.interval = interval
        self.threshold = threshold
        self.finalized_height = -1
        self.votes: Dict[int, Set[str]] = {}

    def is_checkpoint(self, h): return h > 0 and h % self.interval == 0

    def vote(self, h, v):
        if not self.is_checkpoint(h): return False
        self.votes.setdefault(h, set()).add(v)
        return False

    def try_finalize(self, h, stakes):
        if h <= self.finalized_height or not self.is_checkpoint(h): return False
        voted = self.votes.get(h, set())
        total = sum(stakes.values())
        if total <= 0: return False
        voted_stake = sum(stakes.get(v, 0.0) for v in voted)
        if voted_stake >= self.threshold * total:
            self.finalized_height = h
            print(f"[finality] checkpoint #{h} FINALIZADO")
            return True
        return False

    def to_dict(self):
        return {"interval": self.interval, "threshold": self.threshold,
                "finalized_height": self.finalized_height,
                "votes": {str(k): list(v) for k, v in self.votes.items()}}

    @classmethod
    def from_dict(cls, d):
        f = cls(d.get("interval", FINALITY_INTERVAL),
                d.get("threshold", FINALITY_THRESHOLD))
        f.finalized_height = d.get("finalized_height", -1)
        f.votes = {int(k): set(v) for k, v in d.get("votes", {}).items()}
        return f


@dataclass
class SlashingEvidence:
    validator: str
    reason: str
    block_index: int
    invalid_block: dict
    reporter: str
    reporter_public_key: str
    reporter_signature: str

    def canonical(self):
        return {"validator": self.validator, "reason": self.reason,
                "block_index": self.block_index,
                "block_hash": self.invalid_block.get("hash", ""),
                "reporter": self.reporter}

    def verify(self):
        try: blk = Block.from_dict(self.invalid_block)
        except Exception: return False
        if blk.verify(): return False
        if self.validator != blk.validator: return False
        if self.block_index != blk.index: return False
        if WalletManager.address_from_public_key(self.reporter_public_key) != self.reporter:
            return False
        return WalletManager.verify_signature(
            self.reporter_public_key, self.canonical(), self.reporter_signature)

    @staticmethod
    def build(invalid_block, reason, reporter_sk, reporter_pk):
        addr = WalletManager.address_from_public_key(reporter_pk)
        ev = SlashingEvidence(validator=invalid_block.validator, reason=reason,
                              block_index=invalid_block.index,
                              invalid_block=invalid_block.to_dict(),
                              reporter=addr, reporter_public_key=reporter_pk,
                              reporter_signature="")
        ev.reporter_signature = WalletManager.sign_transaction(reporter_sk, ev.canonical())
        return ev

    def to_dict(self): return asdict(self)

    @classmethod
    def from_dict(cls, d): return cls(**d)


class Blockchain:
    def __init__(self, db_path=DB_PATH, node_identity=None,
                 genesis_allocations=None, regulator_address=""):
        self.db_path = db_path
        self.node_identity = node_identity
        self.genesis_allocations = dict(genesis_allocations or GENESIS_ALLOCATIONS)
        self.chain: List[Block] = []
        self.pending: List[dict] = []
        self.state = State()
        self.registry = AssetRegistry()
        if regulator_address: self.registry.regulator = regulator_address
        self.slashed: Set[str] = set()
        self.finality = Finality()
        self.lock = threading.RLock()
        self._init_db()
        if not self._load_from_db():
            self._create_genesis()
            self._persist_block(self.chain[0])
            self._rebuild_state()
            self._bootstrap_native_asset()
            print("[chain] genese RWA criada.")
        else:
            print(f"[chain] {len(self.chain)} blocos carregados.")

    def _bootstrap_native_asset(self):
        if NATIVE_ASSET in self.registry.assets: return
        self.registry.add_asset(AssetDefinition(
            asset_id=NATIVE_ASSET, name="BRN", symbol="BRN",
            asset_type="currency", decimals=8,
            issuer=NATIVE_ASSET_ISSUER, transfer_agent=NATIVE_ASSET_ISSUER,
            transfer_restricted=False, max_supply=0))
        self._persist_registry()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS blocks (
                idx INTEGER PRIMARY KEY, hash TEXT NOT NULL,
                validator TEXT, timestamp REAL, data TEXT NOT NULL)""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hash ON blocks(hash)")
            conn.execute("""CREATE TABLE IF NOT EXISTS mempool (
                tx_hash TEXT PRIMARY KEY, ts REAL NOT NULL, data TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS slashing (
                validator TEXT PRIMARY KEY, reason TEXT,
                block_idx INTEGER, ts REAL, evidence TEXT)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS faucet_claims (
                address TEXT PRIMARY KEY, last_claim REAL NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS finality (
                id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS registry (
                id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL)""")
            conn.commit()

    def _persist_block(self, block):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO blocks VALUES (?,?,?,?,?)",
                         (block.index, block.hash, block.validator,
                          block.timestamp, json.dumps(block.to_dict())))
            conn.commit()

    def _persist_registry(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO registry VALUES (1, ?)",
                         (json.dumps(self.registry.to_dict()),))
            conn.commit()

    def _persist_finality(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO finality VALUES (1, ?)",
                         (json.dumps(self.finality.to_dict()),))
            conn.commit()

    def _load_registry(self):
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT data FROM registry WHERE id=1").fetchone()
        if row:
            try:
                self.registry = AssetRegistry.from_dict(json.loads(row[0]))
            except Exception: pass

    def _load_finality(self):
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT data FROM finality WHERE id=1").fetchone()
        if row:
            try: self.finality = Finality.from_dict(json.loads(row[0]))
            except Exception: pass

    def _load_slashed(self):
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT validator FROM slashing").fetchall()
        self.slashed = {r[0] for r in rows}

    def _mempool_add(self, tx):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO mempool VALUES (?,?,?)",
                         (Transaction.hash(tx), time.time(), json.dumps(tx)))
            conn.commit()

    def _mempool_remove(self, tx):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM mempool WHERE tx_hash=?",
                         (Transaction.hash(tx),))
            conn.commit()

    def _mempool_clear(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM mempool")
            conn.commit()

    def _mempool_load(self):
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT data FROM mempool ORDER BY ts ASC").fetchall()
        self.pending = []
        for (data,) in rows:
            try:
                tx = json.loads(data)
                if Transaction.verify_signature(tx):
                    self.pending.append(tx)
            except Exception: continue

    def _load_from_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute("SELECT data FROM blocks ORDER BY idx ASC").fetchall()
        except sqlite3.Error: return False
        if not rows: return False
        self.chain = [Block.from_dict(json.loads(r[0])) for r in rows]
        self._load_slashed()
        self._load_finality()
        self._load_registry()
        self._rebuild_state()
        self._mempool_load()
        return True

    def _create_genesis(self):
        g = Block(index=0, timestamp=time.time(), previous_hash="0"*64,
                  transactions=[], validator="genesis")
        g.finalize()
        self.chain.append(g)

    @property
    def last_block(self): return self.chain[-1]

    def _rebuild_state(self):
        self.state = State()
        for addr, alloc in self.genesis_allocations.items():
            for asset_id, amt in alloc.items():
                self.state.credit(addr, asset_id, amt)
        for blk in self.chain[1:]:
            for tx in blk.transactions:
                self._apply_tx_to_state(self.state, tx)
            self.state.credit(blk.validator, NATIVE_ASSET, BLOCK_REWARD)

    def _apply_tx_to_state(self, state, tx):
        t = tx["type"]
        sender, receiver = tx["from"], tx["to"]
        asset_id = tx["asset_id"]
        amount = float(tx["amount"])
        if t == "transfer":
            if state.available(sender, asset_id) < amount: return False
            state.debit(sender, asset_id, amount)
            state.credit(receiver, asset_id, amount)
            state.nonces[sender] = state.nonce(sender) + 1
            return True
        if t == "issue":
            a = self.registry.get_asset(asset_id)
            if not a: return False
            if a.max_supply > 0 and state.total_supply.get(asset_id, 0) + amount > a.max_supply:
                return False
            state.credit(receiver, asset_id, amount)
            state.nonces[sender] = state.nonce(sender) + 1
            return True
        if t == "redeem":
            if state.available(sender, asset_id) < amount: return False
            state.debit(sender, asset_id, amount)
            state.nonces[sender] = state.nonce(sender) + 1
            return True
        if t in ("freeze", "unfreeze"):
            if t == "freeze":
                if state.available(receiver, asset_id) < amount: return False
                state.freeze(receiver, asset_id, amount)
            else:
                state.unfreeze(receiver, asset_id, amount)
            state.nonces[sender] = state.nonce(sender) + 1
            return True
        if t in ("kyc_register", "kyc_revoke", "asset_create",
                 "asset_update", "dividend"):
            state.nonces[sender] = state.nonce(sender) + 1
            return True
        return False

    def _apply_registry_ops(self, tx, persist=True):
        t = tx["type"]; md = tx.get("metadata", {})
        if t == "asset_create":
            a = AssetDefinition(
                asset_id=md["asset_id"], name=md.get("name", md["asset_id"]),
                symbol=md.get("symbol", md["asset_id"]),
                asset_type=md["asset_type"], decimals=int(md.get("decimals", 2)),
                issuer=md["issuer"],
                transfer_agent=md.get("transfer_agent", md["issuer"]),
                custodian=md.get("custodian", ""), isin=md.get("isin", ""),
                max_supply=float(md.get("max_supply", 0)),
                transfer_restricted=bool(md.get("transfer_restricted", True)),
                legal_doc_hash=md.get("legal_doc_hash", ""),
                metadata=md.get("metadata", {}))
            self.registry.add_asset(a)
            if persist: self._persist_registry()
        elif t == "asset_update":
            self.registry.update_asset(tx["asset_id"], md)
            if persist: self._persist_registry()
        elif t == "kyc_register":
            rec = ComplianceRecord(
                address=tx["to"], status=md.get("status", "approved"),
                level=md.get("level", "basic"),
                jurisdiction=md.get("jurisdiction", ""),
                verified_by=tx["from"], verified_at=time.time(),
                expires_at=float(md.get("expires_at", 0)),
                restrictions=list(md.get("restrictions", [])),
                metadata=md.get("extra", {}))
            self.registry.set_compliance(rec)
            if persist: self._persist_registry()
        elif t == "kyc_revoke":
            rec = self.registry.get_compliance(tx["to"])
            if rec:
                rec.status = "revoked"
                if persist: self._persist_registry()
        elif t == "freeze" and md.get("freeze_asset"):
            a = self.registry.get_asset(tx["asset_id"])
            if a:
                a.frozen = True
                if persist: self._persist_registry()
        elif t == "unfreeze" and md.get("unfreeze_asset"):
            a = self.registry.get_asset(tx["asset_id"])
            if a:
                a.frozen = False
                if persist: self._persist_registry()

    def _validate_tx(self, tx):
        t = tx["type"]; asset_id = tx["asset_id"]
        sender, receiver = tx["from"], tx["to"]
        amount = float(tx["amount"]); md = tx.get("metadata", {})
        if t == "transfer":
            if asset_id not in self.registry.assets:
                return False, f"ativo '{asset_id}' nao registrado"
            recv_after = self.state.balance(receiver, asset_id) + amount
            return self.registry.validate_transfer(asset_id, sender, receiver,
                                                    amount, recv_after)
        if t == "issue":
            if not self.registry.can_issue(asset_id, sender):
                return False, "nao e emissor"
            a = self.registry.get_asset(asset_id)
            if a.max_supply > 0 and self.state.total_supply.get(asset_id, 0) + amount > a.max_supply:
                return False, "max_supply excedido"
            return True, "ok"
        if t == "redeem":
            a = self.registry.get_asset(asset_id)
            if not a: return False, "ativo inexistente"
            if sender not in (a.issuer, a.transfer_agent):
                return False, "sem permissao"
            if self.state.available(receiver, asset_id) < amount:
                return False, "saldo insuficiente"
            return True, "ok"
        if t in ("freeze", "unfreeze"):
            if not self.registry.can_freeze(asset_id, sender):
                return False, "sem permissao"
            return True, "ok"
        if t == "kyc_register":
            if not self.registry.can_manage_kyc(asset_id, sender):
                return False, "sem permissao KYC"
            if md.get("status", "approved") not in KYC_STATUS:
                return False, "status invalido"
            if md.get("level", "basic") not in KYC_LEVELS:
                return False, "level invalido"
            return True, "ok"
        if t == "kyc_revoke":
            if not self.registry.can_manage_kyc(asset_id, sender):
                return False, "sem permissao KYC"
            return True, "ok"
        if t == "asset_create":
            new_id = md.get("asset_id", "")
            if not new_id or new_id in self.registry.assets:
                return False, "asset_id invalido"
            if md.get("asset_type") not in ASSET_TYPES:
                return False, "asset_type invalido"
            if md.get("issuer") != sender:
                return False, "issuer != sender"
            return True, "ok"
        if t == "asset_update":
            if not self.registry.can_issue(asset_id, sender):
                return False, "so emissor atualiza"
            return True, "ok"
        if t == "dividend":
            if not self.registry.can_issue(asset_id, sender):
                return False, "so emissor paga dividendos"
            if self.state.available(sender, NATIVE_ASSET) < amount:
                return False, "sem saldo BRN"
            snap = md.get("snapshot", {})
            if not isinstance(snap, dict) or not snap:
                return False, "snapshot ausente"
            return True, "ok"
        return False, "tipo nao suportado"

    def add_transaction(self, tx):
        with self.lock:
            if not Transaction.verify_signature(tx):
                return {"ok": False, "msg": "Assinatura invalida."}
            if Transaction.derived_address(tx) != tx["from"]:
                return {"ok": False, "msg": "Endereco != chave publica."}
            if tx["from"] in self.slashed:
                return {"ok": False, "msg": "Remetente banido."}
            if tx["nonce"] != self.state.nonce(tx["from"]):
                return {"ok": False, "msg": f"Nonce invalido (esperado {self.state.nonce(tx['from'])})."}
            if tx["type"] not in Transaction.VALID_TYPES:
                return {"ok": False, "msg": "Tipo desconhecido."}
            ok, why = self._validate_tx(tx)
            if not ok: return {"ok": False, "msg": why}
            for p in self.pending:
                if p["from"] == tx["from"] and p["nonce"] == tx["nonce"]:
                    return {"ok": False, "msg": "Duplicada."}
            self.pending.append(tx)
            self._mempool_add(tx)
            return {"ok": True, "msg": "Aceita.", "tx_hash": Transaction.hash(tx)}

    def _select_validator(self):
        eligible = {a: b.get(NATIVE_ASSET, 0.0)
                    for a, b in self.state.balances.items()
                    if b.get(NATIVE_ASSET, 0.0) >= MIN_STAKE and a not in self.slashed}
        if not eligible:
            if self.node_identity and self.node_identity["address"] not in self.slashed:
                return self.node_identity["address"]
            return None
        total = sum(eligible.values())
        pick = secrets.randbelow(max(1, int(total * 1_000_000))) / 1_000_000
        acc = 0.0
        for addr, weight in eligible.items():
            acc += weight
            if pick <= acc: return addr
        return list(eligible.keys())[-1]

    def produce_block(self):
        with self.lock:
            if not self.node_identity: return None
            if self.node_identity["address"] in self.slashed: return None
            validator = self._select_validator()
            if validator != self.node_identity["address"]: return None
            temp = self.state.copy()
            temp_reg = AssetRegistry.from_dict(self.registry.to_dict())
            chosen = []
            real_reg = self.registry
            self.registry = temp_reg
            try:
                for tx in sorted(self.pending, key=lambda t: (t["from"], t["nonce"])):
                    if not Transaction.verify_signature(tx): continue
                    if tx["nonce"] != temp.nonce(tx["from"]): continue
                    ok, _ = self._validate_tx(tx)
                    if not ok: continue
                    if not self._apply_tx_to_state(temp, tx): continue
                    self._apply_registry_ops(tx, persist=False)
                    chosen.append(tx)
            finally:
                self.registry = real_reg
            block = Block(index=self.last_block.index + 1,
                          timestamp=time.time(),
                          previous_hash=self.last_block.hash,
                          transactions=chosen,
                          validator=self.node_identity["address"],
                          validator_public_key=self.node_identity["public_key"],
                          registry_snapshot=self.registry.to_dict())
            block.finalize()
            block.sign(self.node_identity["spend_secret_key"])
            if not block.verify(): return None
            for tx in chosen:
                self._apply_tx_to_state(self.state, tx)
                self._apply_registry_ops(tx, persist=True)
                self._mempool_remove(tx)
            self.state.credit(block.validator, NATIVE_ASSET, BLOCK_REWARD)
            self.pending = [t for t in self.pending if t not in chosen]
            self.chain.append(block)
            self._persist_block(block)
            if self.finality.is_checkpoint(block.index):
                self.finality.vote(block.index, block.validator)
                stakes = {a: b.get(NATIVE_ASSET, 0.0)
                          for a, b in self.state.balances.items()}
                if self.finality.try_finalize(block.index, stakes):
                    self._persist_finality()
            return block

    def _find_invalid_block(self, chain):
        for i, blk in enumerate(chain):
            if not blk.verify(): return blk
            if i == 0: continue
            prev = chain[i - 1]
            if blk.previous_hash != prev.hash or blk.index != prev.index + 1:
                return blk
        return None

    def _verify_chain_structure(self, chain):
        return self._find_invalid_block(chain) is None

    def _fork_score(self, chain):
        if not chain: return 0.0
        temp = State()
        for addr, alloc in self.genesis_allocations.items():
            for asset_id, amt in alloc.items():
                temp.credit(addr, asset_id, amt)
        score = 0.0
        for blk in chain[1:]:
            for tx in blk.transactions:
                try: self._apply_tx_to_state(temp, tx)
                except Exception: pass
            temp.credit(blk.validator, NATIVE_ASSET, BLOCK_REWARD)
            score += 1.0 + temp.balance(blk.validator, NATIVE_ASSET)
        return score

    def _replace_all_in_db(self, blocks):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM blocks")
            for blk in blocks:
                conn.execute("INSERT INTO blocks VALUES (?,?,?,?,?)",
                             (blk.index, blk.hash, blk.validator,
                              blk.timestamp, json.dumps(blk.to_dict())))
            conn.commit()

    def replace_chain(self, new_chain):
        try:
            blocks = [Block.from_dict(b) if isinstance(b, dict) else b
                      for b in new_chain]
        except Exception as e:
            print(f"[chain] erro desserializar: {e}"); return False
        with self.lock:
            if len(blocks) <= self.finality.finalized_height: return False
            for i in range(min(self.finality.finalized_height + 1, len(self.chain))):
                if i >= len(blocks) or blocks[i].hash != self.chain[i].hash:
                    return False
            invalid = self._find_invalid_block(blocks)
            if invalid:
                self._slash(invalid.validator,
                            f"bloco invalido #{invalid.index}",
                            block_idx=invalid.index)
                return False
            if self._fork_score(blocks) < self._fork_score(self.chain): return False
            if self._fork_score(blocks) == self._fork_score(self.chain) and \
               len(blocks) <= len(self.chain): return False
            new_state = State()
            new_reg = AssetRegistry()
            new_reg.regulator = self.registry.regulator
            new_reg.add_asset(AssetDefinition(
                asset_id=NATIVE_ASSET, name="BRN", symbol="BRN",
                asset_type="currency", decimals=8,
                issuer=NATIVE_ASSET_ISSUER, transfer_agent=NATIVE_ASSET_ISSUER,
                transfer_restricted=False))
            for addr, alloc in self.genesis_allocations.items():
                for asset_id, amt in alloc.items():
                    new_state.credit(addr, asset_id, amt)
            real_reg = self.registry
            self.registry = new_reg
            try:
                for blk in blocks[1:]:
                    for tx in blk.transactions:
                        if not Transaction.verify_signature(tx): return False
                        if not self._apply_tx_to_state(new_state, tx): return False
                        self._apply_registry_ops(tx, persist=False)
                    new_state.credit(blk.validator, NATIVE_ASSET, BLOCK_REWARD)
                committed_reg = self.registry
            except Exception as e:
                print(f"[chain] erro replay: {e}"); return False
            finally:
                self.registry = real_reg
            self.chain = blocks
            self.state = new_state
            self.registry = committed_reg
            self._persist_registry()
            self._replace_all_in_db(blocks)
            confirmed = {Transaction.hash(tx)
                         for blk in blocks for tx in blk.transactions}
            self.pending = [t for t in self.pending
                            if Transaction.hash(t) not in confirmed]
            self._mempool_clear()
            for t in self.pending:
                self._mempool_add(t)
            print(f"[chain] substituida -> altura {len(blocks)}")
            return True

    def _slash(self, validator, reason, block_idx=-1, evidence=None):
        if not validator or validator == "genesis": return False
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO slashing VALUES (?,?,?,?,?)",
                         (validator, reason, block_idx, time.time(),
                          json.dumps(evidence.to_dict()) if evidence else None))
            conn.commit()
        self.slashed.add(validator)
        if validator in self.state.balances:
            self.state.balances[validator] = {}
        self.state.nonces[validator] = self.state.nonce(validator) + 1
        print(f"[slash] {validator[:16]}... banido ({reason})")
        return True

    def faucet(self, to_address, private_key_hex, public_key_hex):
        if not FAUCET_ADDRESS:
            return {"ok": False, "msg": "Faucet desativado."}
        if FAUCET_ADDRESS != WalletManager.address_from_public_key(public_key_hex):
            return {"ok": False, "msg": "Chave nao corresponde."}
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT last_claim FROM faucet_claims WHERE address=?",
                               (to_address,)).fetchone()
        if row and (now - row[0]) < FAUCET_COOLDOWN:
            return {"ok": False, "msg": f"Aguarde {int(FAUCET_COOLDOWN-(now-row[0]))}s."}
        tx = Transaction.build(
            tx_type="transfer", asset_id=NATIVE_ASSET,
            sender_address=FAUCET_ADDRESS, receiver_address=to_address,
            amount=FAUCET_AMOUNT, nonce=self.state.nonce(FAUCET_ADDRESS),
            private_key_hex=private_key_hex, public_key_hex=public_key_hex)
        r = self.add_transaction(tx)
        if not r.get("ok"): return r
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO faucet_claims VALUES (?,?)",
                         (to_address, now))
            conn.commit()
        return {"ok": True, "msg": f"{FAUCET_AMOUNT} BRN enfileirados.", "tx": tx}

    def portfolio(self, addr):
        out = {}
        for asset_id, amount in self.state.balances.get(addr, {}).items():
            a = self.registry.get_asset(asset_id)
            rec = self.registry.get_compliance(addr)
            out[asset_id] = {
                "amount": amount,
                "available": self.state.available(addr, asset_id),
                "frozen": self.state.frozen.get(addr, {}).get(asset_id, 0.0),
                "asset": a.to_dict() if a else None,
                "compliance": rec.to_dict() if rec else None,
            }
        return out

    def slashing_report(self):
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT validator, reason, block_idx, ts, evidence "
                                "FROM slashing ORDER BY ts DESC").fetchall()
        return [{"validator": r[0], "reason": r[1], "block_index": r[2],
                 "timestamp": r[3],
                 "evidence": json.loads(r[4]) if r[4] else None} for r in rows]

    def finality_report(self):
        return {"finalized_height": self.finality.finalized_height,
                "interval": self.finality.interval,
                "threshold": self.finality.threshold,
                "checkpoint_pending": {str(k): list(v)
                                       for k, v in self.finality.votes.items()}}

    def to_dict(self):
        return {"network_id": NETWORK_ID, "length": len(self.chain),
                "chain": [b.to_dict() for b in self.chain]}
