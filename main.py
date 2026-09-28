"""
BRUNOCOIN (BRN) — main.py v3.4
============================================================
✅ Economia híbrida (halving + tail + taxas + queima)
✅ P2P com prefixo de tamanho
✅ Validação de cadeia completa
✅ Limite de mempool (anti-DoS)
✅ Auto-descoberta na LAN (multicast)
✅ Mineração LOCAL + nó REMOTO via P2P
✅ Sync automático a cada SYNC_INTERVAL
✅ Broadcast de blocos minerados
✅ Saldo real após sincronização
✅ Transferência de fundos com validação

CORREÇÕES v3.4:
  🐛 #1: Taxa deduzida 2× no saldo
  🐛 #2: Blocos com taxa rejeitados por peers
  🐛 #3: Handshake P2P com s.recv(64)
  🐛 #4: webview travava sem index.html
  🐛 #5: Bootstrap tentava conectar a si mesmo
  🐛 #6: struct não utilizado
  🐛 #7: BRN_NETWORK_MAGIC não usado
  🐛 #8: Falta de fallback headless
  🐛 #9: Import do webview sem try/except
  🐛 #10: Sem auto-sync periódico
  🐛 #11: Blocos minerados não eram propagados
  🐛 #12: Race condition ao limpar mempool
============================================================
"""

import hashlib
import time
import json
import sqlite3
import socket
import threading
import sys
import os
from typing import List, Dict, Any, Tuple, Optional

# ✅ Import webview protegido
try:
    import webview
    WEBVIEW_DISPONIVEL = True
except ImportError:
    WEBVIEW_DISPONIVEL = False
    webview = None

from cripto_wallet import WalletManager
from cripto_db import BlockchainDB
from cripto_p2p_network import AutoPortForwarder

# ✅ Auto-descoberta
try:
    from auto_discovery import AutoNodeDiscovery
    DISCOVERY_DISPONIVEL = True
except ImportError:
    DISCOVERY_DISPONIVEL = False
    AutoNodeDiscovery = None
    print("[Discovery] auto_discovery.py não encontrado — pulando")


# ============================================================
# CONFIGURAÇÃO
# ============================================================
COIN_NAME = "Bruno"
COIN_SYMBOL = "BRN"

# ==================== ECONOMIA ====================
INITIAL_REWARD          = 1.0
HALVING_INTERVAL        = 1_000_000
TAIL_REWARD             = 0.01
TRANSACTION_FEE_FIXED   = 0.001
BURN_PERCENTAGE         = 0.5

# ==================== REDE ====================
DIFFICULTY_ADJUSTMENT_INTERVAL = 5
TARGET_BLOCK_TIME              = 10.0
MAX_MEMPOOL_SIZE               = 10000
MAX_MESSAGE_SIZE               = 10 * 1024 * 1024
SOCKET_TIMEOUT                 = 5.0

# ✅ Sync automático
SYNC_INTERVAL                  = 30.0     # segundos entre syncs
REBROADCAST_BLOCK_DELAY        = 2.0      # espera antes de propagar bloco

BRN_NETWORK_ID = "brunocoin-mainnet-v1"

# ✅ Adicione o IP do seu VPS aqui
BOOTSTRAP_PEERS = [
    # ("203.0.113.42", 6001),   # ← coloque o IP público do VPS aqui
]

# ==================== GÊNESE DETERMINÍSTICO ====================
GENESIS_TIMESTAMP  = 1700000000
GENESIS_DIFFICULTY = 4
GENESIS_ADDRESS    = "brn1111cd943fa71e1f91dcd62f52fc6138bc845ab"
GENESIS_REWARD     = 100000.0
GENESIS_NONCE      = 0


# ============================================================
# ECONOMIA
# ============================================================
def current_reward(block_index: int) -> float:
    halvings = block_index // HALVING_INTERVAL
    if halvings >= 64:
        return TAIL_REWARD
    reward = INITIAL_REWARD / (2 ** halvings)
    return max(reward, TAIL_REWARD)


def calculate_tx_fee(amount: float) -> float:
    return TRANSACTION_FEE_FIXED


def descobrir_nonce_genesis() -> int:
    cb = {"sender": "SISTEMA", "receiver": GENESIS_ADDRESS, "amount": GENESIS_REWARD}
    nonce = 0
    while nonce < 100_000_000:
        bd = {
            "index": 0, "timestamp": round(GENESIS_TIMESTAMP, 6),
            "previous_hash": "0", "transactions": [cb],
            "difficulty": GENESIS_DIFFICULTY, "nonce": nonce,
            "network_id": BRN_NETWORK_ID,
        }
        s = json.dumps(bd, sort_keys=True, separators=(',', ':')).encode()
        h = hashlib.sha256(hashlib.sha256(s).digest()).hexdigest()
        if h.startswith("0" * GENESIS_DIFFICULTY):
            return nonce
        nonce += 1
    return -1


# ============================================================
# BLOCO
# ============================================================
class BrunoBlock:

    def __init__(self, index, previous_hash, transactions, difficulty=4,
                 nonce=0, timestamp=None, block_hash=None):
        self.index = int(index)
        self.timestamp = float(timestamp) if timestamp is not None else time.time()
        self.previous_hash = str(previous_hash)

        if isinstance(transactions, list):
            self.transactions = transactions
        elif isinstance(transactions, str):
            self.transactions = json.loads(transactions)
        else:
            self.transactions = list(transactions)

        self.difficulty = int(difficulty)
        self.nonce = int(nonce)
        self.network_id = BRN_NETWORK_ID
        self.hash = str(block_hash) if block_hash else self.calculate_hash()

    def calculate_hash(self) -> str:
        bd = {
            "index": self.index, "timestamp": round(self.timestamp, 6),
            "previous_hash": self.previous_hash,
            "transactions": self.transactions,
            "difficulty": self.difficulty, "nonce": self.nonce,
            "network_id": self.network_id,
        }
        s = json.dumps(bd, sort_keys=True, separators=(',', ':')).encode()
        return hashlib.sha256(hashlib.sha256(s).digest()).hexdigest()

    def mine_block(self, stop_event=None) -> bool:
        target = "0" * self.difficulty
        while self.hash[:self.difficulty] != target:
            if stop_event and stop_event.is_set():
                return False
            self.nonce += 1
            self.hash = self.calculate_hash()
        return True

    def to_dict(self):
        return {
            "index": self.index, "timestamp": self.timestamp,
            "previous_hash": self.previous_hash,
            "transactions": self.transactions,
            "difficulty": self.difficulty, "nonce": self.nonce,
            "hash": self.hash,
        }


# ============================================================
# API PRINCIPAL
# ============================================================
class CriptoAPI:

    def __init__(self, node_port: int):
        self.p2p_port = int(node_port)
        self.db_path = f"blockchain_node_{self.p2p_port}.db"
        self.db = BlockchainDB(self.db_path)

        self.mempool_lock = threading.Lock()
        self.peers_lock = threading.Lock()
        self.db_lock = threading.RLock()

        self.mempool: List[Dict[str, Any]] = []
        self.connected_peers = set()

        self.is_mining = False
        self.mining_stop_event = threading.Event()
        self.miner_thread: Optional[threading.Thread] = None

        self._init_database()
        self._load_persistent_state()

        # Servidor P2P
        self.server_thread = threading.Thread(
            target=self._start_p2p_server, daemon=True
        )
        self.server_thread.start()

        # Bootstrap estático
        threading.Thread(
            target=self._run_bootstrap_discovery, daemon=True
        ).start()

        # ✅ Auto-sync periódico (a cada 30s)
        threading.Thread(
            target=self._sync_periodico, daemon=True, name="AutoSync"
        ).start()

    # ==========================================================
    # PERSISTÊNCIA
    # ==========================================================
    def _init_database(self):
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS blocks (
                    id_index INTEGER PRIMARY KEY, timestamp REAL,
                    previous_hash TEXT, transactions TEXT,
                    difficulty INTEGER, nonce INTEGER, hash TEXT
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS mempool (
                    signature TEXT PRIMARY KEY, tx_json TEXT NOT NULL,
                    added_at REAL NOT NULL
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS peers (
                    address TEXT PRIMARY KEY, last_seen REAL NOT NULL
                )
            """)
            conn.commit()

            c.execute("SELECT COUNT(*) FROM blocks")
            if c.fetchone()[0] == 0:
                genesis = BrunoBlock(
                    index=0, previous_hash="0",
                    transactions=[{
                        "sender": "SISTEMA", "receiver": GENESIS_ADDRESS,
                        "amount": GENESIS_REWARD,
                    }],
                    difficulty=GENESIS_DIFFICULTY,
                    nonce=GENESIS_NONCE, timestamp=GENESIS_TIMESTAMP,
                )
                if not genesis.hash.startswith("0" * GENESIS_DIFFICULTY):
                    print("[GENESIS] Minerando…")
                    genesis.mine_block()
                    print(f"[GENESIS] ✅ Nonce: {genesis.nonce}")
                self.db.insert_block(genesis)

    def _load_persistent_state(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                c.execute("SELECT tx_json FROM mempool ORDER BY added_at")
                self.mempool = [json.loads(row[0]) for row in c.fetchall()]
                c.execute("SELECT address FROM peers")
                for row in c.fetchall():
                    try:
                        ip, port = row[0].rsplit(":", 1)
                        self.connected_peers.add((ip, int(port)))
                    except Exception:
                        pass
            print(f"[STATE] {len(self.mempool)} txs | {len(self.connected_peers)} peers")
        except Exception as e:
            print(f"[STATE] Erro: {e}")

    def _save_mempool_tx(self, tx):
        try:
            sig = tx.get("signature", "")
            if not sig:
                return
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO mempool VALUES (?, ?, ?)",
                    (sig, json.dumps(tx), time.time()),
                )
                conn.commit()
        except Exception:
            pass

    def _remove_mempool_tx(self, signature):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM mempool WHERE signature = ?", (signature,))
                conn.commit()
        except Exception:
            pass

    def _save_peer(self, ip, port):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO peers VALUES (?, ?)",
                    (f"{ip}:{port}", time.time()),
                )
                conn.commit()
        except Exception:
            pass

    # ==========================================================
    # UTILITÁRIOS
    # ==========================================================
    def get_p2p_port(self):
        return self.p2p_port

    def _get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def _calculate_next_difficulty(self):
        with self.db_lock:
            chain = self.db.get_raw_chain()
        if not chain:
            return GENESIS_DIFFICULTY
        lb = chain[-1]
        if lb["index"] < DIFFICULTY_ADJUSTMENT_INTERVAL:
            return lb["difficulty"]
        if lb["index"] % DIFFICULTY_ADJUSTMENT_INTERVAL != 0:
            return lb["difficulty"]
        prev = chain[-DIFFICULTY_ADJUSTMENT_INTERVAL]
        expected = TARGET_BLOCK_TIME * DIFFICULTY_ADJUSTMENT_INTERVAL
        taken = lb["timestamp"] - prev["timestamp"]
        cur = lb["difficulty"]
        if taken < (expected / 2):
            return cur + 1
        elif taken > (expected * 2):
            return max(1, cur - 1)
        return cur

    # ==========================================================
    # P2P
    # ==========================================================
    def _send_msg(self, sock, payload):
        size = len(payload).to_bytes(4, "big")
        sock.sendall(size + payload)

    def _recv_msg(self, sock, max_size=MAX_MESSAGE_SIZE):
        size_data = b""
        while len(size_data) < 4:
            chunk = sock.recv(4 - len(size_data))
            if not chunk:
                raise ConnectionError("Fechado antes do tamanho")
            size_data += chunk
        size = int.from_bytes(size_data, "big")
        if size > max_size:
            raise ValueError(f"Muito grande: {size}")
        data = b""
        while len(data) < size:
            chunk = sock.recv(min(65536, size - len(data)))
            if not chunk:
                raise ConnectionError("Fechado durante dados")
            data += chunk
        return data

    def _recv_msg_str(self, sock):
        return self._recv_msg(sock).decode("utf-8")

    # ==========================================================
    # SERVIDOR P2P
    # ==========================================================
    def _start_p2p_server(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", self.p2p_port))
        s.listen(10)
        print(f"[P2P] Servidor rodando na porta {self.p2p_port}")

        while True:
            conn = None
            try:
                conn, addr = s.accept()
                conn.settimeout(SOCKET_TIMEOUT)
                data = self._recv_msg_str(conn)

                if data.startswith("HELLO:"):
                    try:
                        info = json.loads(data.split(":", 1)[1])
                        peer_ip = info.get("ip", addr[0])
                        peer_port = int(info.get("port", 6001))
                        with self.peers_lock:
                            self.connected_peers.add((peer_ip, peer_port))
                        self._save_peer(peer_ip, peer_port)
                        self._send_msg(conn, b"HELLO_OK")
                        print(f"[P2P] 👋 Peer: {peer_ip}:{peer_port}")
                    except Exception as e:
                        print(f"[P2P] Handshake erro: {e}")

                elif data == "GET_HEIGHT":
                    with self.db_lock:
                        chain = self.db.get_raw_chain()
                    self._send_msg(conn, str(len(chain)).encode())

                elif data == "GET_CHAIN":
                    with self.db_lock:
                        chain = self.db.get_raw_chain()
                    self._send_msg(conn, json.dumps(chain).encode())

                elif data.startswith("BROADCAST_TX:"):
                    tx = json.loads(data.split(":", 1)[1])
                    if self._verify_tx_structure(tx):
                        self._adicionar_na_mempool(tx)

                elif data.startswith("SYNC_CHAIN:"):
                    incoming = json.loads(data.split(":", 1)[1])
                    self._resolve_consensus(incoming)

                # ✅ NOVO: recebe bloco novo de um peer
                elif data.startswith("NEW_BLOCK:"):
                    block_data = json.loads(data.split(":", 1)[1])
                    self._processar_bloco_recebido(block_data)

            except socket.timeout:
                pass
            except Exception as e:
                print(f"[P2P] Erro: {e}")
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

    # ==========================================================
    # MEMPOOL
    # ==========================================================
    def _adicionar_na_mempool(self, tx):
        with self.mempool_lock:
            sig = tx.get("signature")
            for e in self.mempool:
                if e.get("signature") == sig:
                    return False
            if len(self.mempool) >= MAX_MEMPOOL_SIZE:
                self.mempool.sort(key=lambda t: float(t.get("fee", 0)))
                if float(tx.get("fee", 0)) <= float(self.mempool[0].get("fee", 0)):
                    return False
                removida = self.mempool.pop(0)
                self._remove_mempool_tx(removida.get("signature", ""))
            self.mempool.append(tx)
            self._save_mempool_tx(tx)
            return True

    # ==========================================================
    # DISCOVERY
    # ==========================================================
    def _run_bootstrap_discovery(self):
        time.sleep(2)
        meu_ip = self._get_local_ip()
        for ip, port in BOOTSTRAP_PEERS:
            if ip == meu_ip and port == self.p2p_port:
                continue
            try:
                print(f"[DISCOVERY] Tentando {ip}:{port}…")
                self.connect_and_sync(ip, port)
            except Exception as e:
                print(f"[DISCOVERY] Falha: {e}")

    # ==========================================================
    # ✅ NOVO: AUTO-SYNC PERIÓDICO
    # ==========================================================
    def _sync_periodico(self):
        """Sincroniza com todos os peers a cada SYNC_INTERVAL segundos."""
        time.sleep(15)  # espera inicial

        while True:
            try:
                with self.peers_lock:
                    peers = list(self.connected_peers)

                # Se não tem peers, tenta bootstrap
                if not peers and BOOTSTRAP_PEERS:
                    meu_ip = self._get_local_ip()
                    for ip, port in BOOTSTRAP_PEERS:
                        if ip == meu_ip and port == self.p2p_port:
                            continue
                        try:
                            self.connect_and_sync(ip, port)
                        except Exception:
                            pass
                else:
                    # Sincroniza com todos os peers conhecidos
                    for ip, port in peers:
                        try:
                            self.connect_and_sync(ip, port)
                        except Exception:
                            pass

            except Exception as e:
                print(f"[SYNC] Erro: {e}")

            time.sleep(SYNC_INTERVAL)

    # ==========================================================
    # BROADCAST
    # ==========================================================
    def _broadcast_transaction_to_network(self, tx):
        with self.peers_lock:
            peers = list(self.connected_peers)
        payload = ("BROADCAST_TX:" + json.dumps(tx)).encode()
        for ip, port in peers:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(2.0)
                    s.connect((ip, int(port)))
                    hello = json.dumps({"ip": self._get_local_ip(), "port": self.p2p_port})
                    self._send_msg(s, ("HELLO:" + hello).encode())
                    self._recv_msg(s)
                    self._send_msg(s, payload)
            except Exception:
                with self.peers_lock:
                    self.connected_peers.discard((ip, port))

    def _broadcast_chain_to_peers(self):
        try:
            with self.db_lock:
                chain = self.db.get_raw_chain()
            payload = ("SYNC_CHAIN:" + json.dumps(chain)).encode()
            with self.peers_lock:
                peers = list(self.connected_peers)
            for ip, port in peers:
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(2.0)
                        s.connect((ip, int(port)))
                        self._send_msg(s, payload)
                except Exception:
                    pass
        except Exception:
            pass

    # ✅ NOVO: Broadcast de bloco minerado
    def _broadcast_new_block(self, block):
        """Propaga um bloco recém-minerado para todos os peers."""
        payload = ("NEW_BLOCK:" + json.dumps(block.to_dict())).encode()
        with self.peers_lock:
            peers = list(self.connected_peers)

        propagados = 0
        for ip, port in peers:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(3.0)
                    s.connect((ip, int(port)))
                    hello = json.dumps({"ip": self._get_local_ip(), "port": self.p2p_port})
                    self._send_msg(s, ("HELLO:" + hello).encode())
                    self._recv_msg(s)
                    self._send_msg(s, payload)
                    propagados += 1
            except Exception:
                pass

        if propagados > 0:
            print(f"[P2P] 📡 Bloco #{block.index} propagado para {propagados} peer(s)")

    def _processar_bloco_recebido(self, block_data):
        """✅ Processa bloco vindo de outro peer."""
        try:
            # Já temos esse bloco?
            with self.db_lock:
                existente = self.db.get_raw_chain()
            if any(b["hash"] == block_data["hash"] for b in existente):
                return

            # Valida
            ok, msg = self._validate_block(block_data)
            if not ok:
                print(f"[P2P] Bloco rejeitado: {msg}")
                return

            # Verifica se é o próximo bloco esperado
            with self.db_lock:
                chain = self.db.get_raw_chain()
            ultimo = chain[-1] if chain else None

            if not ultimo or block_data["previous_hash"] != ultimo["hash"]:
                # Não encaixa — precisa sincronizar
                print(f"[P2P] Bloco fora de ordem — disparando sync")
                threading.Thread(target=self._sync_periodico_once, daemon=True).start()
                return

            # Aceita o bloco
            novo_bloco = BrunoBlock(
                block_data["index"], block_data["previous_hash"],
                block_data["transactions"], block_data["difficulty"],
                block_data["nonce"], block_data["timestamp"],
                block_data["hash"],
            )
            with self.db_lock:
                self.db.insert_block(novo_bloco)

            print(f"[P2P] ⬇️ Bloco #{block_data['index']} recebido de peer")

        except Exception as e:
            print(f"[P2P] Erro ao processar bloco: {e}")

    def _sync_periodico_once(self):
        """Sincroniza com peers uma vez (força)."""
        with self.peers_lock:
            peers = list(self.connected_peers)
        for ip, port in peers:
            try:
                self.connect_and_sync(ip, port)
            except Exception:
                pass

    # ==========================================================
    # SYNC
    # ==========================================================
    def connect_and_sync(self, ip, port) -> Dict[str, str]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(3.0)
                s.connect((ip, int(port)))
                hello = json.dumps({"ip": self._get_local_ip(), "port": self.p2p_port})
                self._send_msg(s, ("HELLO:" + hello).encode())
                self._recv_msg(s)

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s_h:
                s_h.settimeout(3.0)
                s_h.connect((ip, int(port)))
                self._send_msg(s_h, b"GET_HEIGHT")
                remote_height = int(self._recv_msg_str(s_h))

            with self.db_lock:
                local_chain = self.db.get_raw_chain()

            if remote_height <= len(local_chain):
                with self.peers_lock:
                    self.connected_peers.add((ip, int(port)))
                self._save_peer(ip, int(port))
                return {"status": "sucesso", "message": "Já atualizado"}

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s_c:
                s_c.settimeout(15.0)
                s_c.connect((ip, int(port)))
                self._send_msg(s_c, b"GET_CHAIN")
                response = self._recv_msg_str(s_c)

            with self.peers_lock:
                self.connected_peers.add((ip, int(port)))
            self._save_peer(ip, int(port))

            remote_chain = json.loads(response)
            msg = self._resolve_consensus(remote_chain)
            print(f"[SYNC] {ip}:{port} — {msg}")
            return {"status": "sucesso", "message": msg}

        except Exception as e:
            return {"status": "erro", "message": str(e)}

    # ==========================================================
    # VALIDAÇÃO
    # ==========================================================
    def _validate_address(self, address):
        if not isinstance(address, str) or not address.startswith("brn1") or len(address) != 44:
            raise ValueError(f"Formato inválido: {address}")
        try:
            int(address[4:], 16)
        except ValueError:
            raise ValueError("Hex inválido")
        return True

    def _verify_tx_structure(self, tx) -> bool:
        if not isinstance(tx, dict):
            return False
        if tx.get("sender") == "SISTEMA":
            return False
        required = ["sender", "receiver", "amount", "public_key", "signature", "timestamp"]
        if not all(k in tx for k in required):
            return False
        try:
            amount = float(tx["amount"])
            if amount <= 0:
                return False
            self._validate_address(tx["sender"])
            self._validate_address(tx["receiver"])
            payload = {
                "sender": tx["sender"], "receiver": tx["receiver"],
                "amount": amount, "timestamp": tx["timestamp"],
            }
            if "fee" in tx:
                payload["fee"] = tx["fee"]
            return WalletManager.verify_signature(tx["public_key"], payload, tx["signature"])
        except Exception:
            return False

    def _validate_block(self, block_data) -> Tuple[bool, str]:
        try:
            block = BrunoBlock(
                block_data["index"], block_data["previous_hash"],
                block_data["transactions"], block_data["difficulty"],
                block_data["nonce"], block_data["timestamp"],
                block_data["hash"],
            )
        except Exception as e:
            return False, f"Malformado: {e}"

        if block.calculate_hash() != block_data["hash"]:
            return False, "Hash incorreto"
        if block.network_id != BRN_NETWORK_ID:
            return False, f"Network ID errado"
        if block.difficulty < 1:
            return False, "Difficulty < 1"
        if not block_data["hash"].startswith("0" * block.difficulty):
            return False, "PoW insuficiente"

        txs = block_data.get("transactions", [])
        if not isinstance(txs, list) or not txs:
            return False, "Sem txs"

        first = txs[0]
        if first.get("sender") != "SISTEMA":
            return False, "Primeira não é coinbase"

        base = current_reward(int(block_data["index"]))
        fees = 0.0
        for tx in txs[1:]:
            try:
                fees += float(tx.get("fee", 0))
            except Exception:
                pass

        try:
            cb_total = sum(float(o["amount"]) for o in first["outputs"])
        except Exception as e:
            return False, f"Coinbase inválida: {e}"

        if cb_total > base + fees + 0.0001:
            return False, f"Coinbase excessiva {cb_total} > {base + fees}"
        if cb_total < base - 0.0001:
            return False, f"Coinbase insuficiente {cb_total} < {base}"

        for i, tx in enumerate(txs[1:], 1):
            if tx.get("sender") == "SISTEMA":
                return False, f"SISTEMA na posição {i}"
            if not self._verify_tx_structure(tx):
                return False, f"Tx inválida na posição {i}"

        return True, "OK"

    def _resolve_consensus(self, remote_chain) -> str:
        with self.db_lock:
            local = self.db.get_raw_chain()

        if len(remote_chain) <= len(local):
            return "Local é dominante"
        if remote_chain[0]["hash"] != local[0]["hash"]:
            return "Gênesis diferente"
        for i in range(1, len(remote_chain)):
            if remote_chain[i]["previous_hash"] != remote_chain[i - 1]["hash"]:
                return f"Elos quebrados em {i}"
        for bd in remote_chain:
            ok, msg = self._validate_block(bd)
            if not ok:
                return f"Bloco #{bd.get('index')}: {msg}"

        with self.db_lock:
            self.db.replace_chain(remote_chain)
        return f"Sincronizado {len(remote_chain)} blocos"

    # ==========================================================
    # API PÚBLICA
    # ==========================================================
    def get_full_chain(self) -> Dict[str, Any]:
        with self.mempool_lock:
            mempool_size = len(self.mempool)
        with self.db_lock:
            chain = self.db.get_raw_chain()
        next_index = len(chain)
        return {
            "chain": chain,
            "length": len(chain),
            "mempool_size": mempool_size,
            "is_mining": self.is_mining,
            "current_difficulty": chain[-1]["difficulty"] if chain else GENESIS_DIFFICULTY,
            "coin": COIN_SYMBOL,
            "block_reward_current": current_reward(next_index),
            "transaction_fee": TRANSACTION_FEE_FIXED,
            "burn_percentage": BURN_PERCENTAGE,
            "next_halving_at": ((next_index // HALVING_INTERVAL) + 1) * HALVING_INTERVAL,
            "network_id": BRN_NETWORK_ID,
            "peers_connected": len(self.connected_peers),
        }

    def get_peers_info(self) -> Dict[str, Any]:
        """✅ NOVO: Info dos peers conectados (usado pela GUI)."""
        with self.peers_lock:
            peers = list(self.connected_peers)
        return {
            "total": len(peers),
            "peers": [f"{ip}:{port}" for ip, port in peers],
        }

    def generate_wallet(self):
        return WalletManager.generate_keypair()

    def _get_balance_unlocked(self, address):
        balance = 0.0
        with self.db_lock:
            chain = self.db.get_raw_chain()
        for block in chain:
            for tx in block["transactions"]:
                if tx.get("sender") == address:
                    balance -= float(tx.get("amount", 0))
                if tx.get("receiver") == address:
                    balance += float(tx.get("amount", 0))
        return balance

    def get_balance(self, address):
        try:
            self._validate_address(address)
            with self.mempool_lock:
                balance = self._get_balance_unlocked(address)
            return {"address": address, "balance": balance}
        except ValueError as e:
            return {"status": "erro", "message": str(e)}

    def send_funds(self, sender, receiver, amount, spend_secret_key, public_key):
        try:
            self._validate_address(sender)
            self._validate_address(receiver)
            amount = float(amount)
            if amount <= 0:
                return {"status": "erro", "message": "Quantia inválida"}
            fee = calculate_tx_fee(amount)

            with self.mempool_lock:
                sender_balance = self._get_balance_unlocked(sender)
                pending = sum(
                    float(tx["amount"]) + float(tx.get("fee", 0))
                    for
