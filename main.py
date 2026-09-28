"""
BRUNOCOIN (BRN) — main.py v3.3
============================================================
✅ Economia híbrida (halving + tail + taxas + queima)
✅ P2P com prefixo de tamanho (sem truncamento)
✅ Validação de cadeia completa no sync
✅ Limite de mempool (anti-DoS)
✅ Network ID próprio
✅ Port forwarding opt-in
✅ Gênese determinístico
✅ Auto-descoberta de peers na LAN (multicast UDP)

CORREÇÕES v3.3 (comparado ao v3.0 original):
  🐛 #1: Taxa de transação deduzida 2× no saldo
  🐛 #2: Blocos com taxa eram rejeitados por peers
  🐛 #3: Handshake P2P lia dados errados (s.recv 64)
  🐛 #4: webview travava se index.html faltava
  🐛 #5: Bootstrap tentava conectar a si mesmo
  🐛 #6: Import `struct` não utilizado
  🐛 #7: `BRN_NETWORK_MAGIC` definido mas não usado
  🐛 #8: Falta de fallback headless em servidores
  🐛 #9: Import do webview sem try/except
  ✨ #10: Auto-descoberta integrada ao P2P (LAN)
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

# ✅ BUG #9 CORRIGIDO: import webview protegido
try:
    import webview
    WEBVIEW_DISPONIVEL = True
except ImportError:
    WEBVIEW_DISPONIVEL = False
    webview = None

from cripto_wallet import WalletManager
from cripto_db import BlockchainDB
from cripto_p2p_network import AutoPortForwarder

# ✅ AUTO-DESCOBERTA: import protegido
try:
    from auto_discovery import AutoNodeDiscovery
    DISCOVERY_DISPONIVEL = True
except ImportError:
    DISCOVERY_DISPONIVEL = False
    AutoNodeDiscovery = None
    print("[Discovery] auto_discovery.py não encontrado — pulando")


# ============================================================
# CONFIGURAÇÃO DA MOEDA E REDE
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

BRN_NETWORK_ID = "brunocoin-mainnet-v1"

BOOTSTRAP_PEERS = [
    ("192.168.0.17", 6001),
]

# ==================== GÊNESE DETERMINÍSTICO ====================
GENESIS_TIMESTAMP  = 1700000000
GENESIS_DIFFICULTY = 4
GENESIS_ADDRESS    = "brn1111cd943fa71e1f91dcd62f52fc6138bc845ab"
GENESIS_REWARD     = 100000.0
GENESIS_NONCE      = 0


# ============================================================
# ECONOMIA — FUNÇÕES PURAS
# ============================================================
def current_reward(block_index: int) -> float:
    """Recompensa com halving + tail emission."""
    halvings = block_index // HALVING_INTERVAL
    if halvings >= 64:
        return TAIL_REWARD
    reward = INITIAL_REWARD / (2 ** halvings)
    return max(reward, TAIL_REWARD)


def calculate_tx_fee(amount: float) -> float:
    """Taxa fixa por transação."""
    return TRANSACTION_FEE_FIXED


def descobrir_nonce_genesis() -> int:
    """
    Descobre o nonce que gera PoW válido para o gênese.
    Rode UMA VEZ, copie o valor e coloque em GENESIS_NONCE.
    """
    cb = {
        "sender":   "SISTEMA",
        "receiver": GENESIS_ADDRESS,
        "amount":   GENESIS_REWARD,
    }
    nonce = 0
    while nonce < 100_000_000:
        block_dict = {
            "index":         0,
            "timestamp":     round(GENESIS_TIMESTAMP, 6),
            "previous_hash": "0",
            "transactions":  [cb],
            "difficulty":    GENESIS_DIFFICULTY,
            "nonce":         nonce,
            "network_id":    BRN_NETWORK_ID,
        }
        s = json.dumps(block_dict, sort_keys=True,
                       separators=(',', ':')).encode('utf-8')
        h = hashlib.sha256(hashlib.sha256(s).digest()).hexdigest()
        if h.startswith("0" * GENESIS_DIFFICULTY):
            return nonce
        nonce += 1
    return -1


# ============================================================
# BLOCO
# ============================================================
class BrunoBlock:

    def __init__(
        self,
        index: int,
        previous_hash: str,
        transactions: Any,
        difficulty: int = 4,
        nonce: int = 0,
        timestamp: Optional[float] = None,
        block_hash: Optional[str] = None,
    ):
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

        if block_hash:
            self.hash = str(block_hash)
        else:
            self.hash = self.calculate_hash()

    def calculate_hash(self) -> str:
        """Double SHA256 do header (padrão Bitcoin)."""
        block_dict = {
            "index":         self.index,
            "timestamp":     round(self.timestamp, 6),
            "previous_hash": self.previous_hash,
            "transactions":  self.transactions,
            "difficulty":    self.difficulty,
            "nonce":         self.nonce,
            "network_id":    self.network_id,
        }
        block_string = json.dumps(
            block_dict, sort_keys=True, separators=(',', ':')
        ).encode('utf-8')
        return hashlib.sha256(hashlib.sha256(block_string).digest()).hexdigest()

    def mine_block(self, stop_event: Optional[threading.Event] = None) -> bool:
        target = "0" * self.difficulty
        while self.hash[:self.difficulty] != target:
            if stop_event and stop_event.is_set():
                return False
            self.nonce += 1
            self.hash = self.calculate_hash()
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index":         self.index,
            "timestamp":     self.timestamp,
            "previous_hash": self.previous_hash,
            "transactions":  self.transactions,
            "difficulty":    self.difficulty,
            "nonce":         self.nonce,
            "hash":          self.hash,
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

        self.server_thread = threading.Thread(
            target=self._start_p2p_server, daemon=True
        )
        self.server_thread.start()

        threading.Thread(
            target=self._run_bootstrap_discovery, daemon=True
        ).start()

    # ==========================================================
    # PERSISTÊNCIA
    # ==========================================================
    def _init_database(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS blocks (
                    id_index      INTEGER PRIMARY KEY,
                    timestamp     REAL,
                    previous_hash TEXT,
                    transactions  TEXT,
                    difficulty    INTEGER,
                    nonce         INTEGER,
                    hash          TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mempool (
                    signature TEXT PRIMARY KEY,
                    tx_json   TEXT NOT NULL,
                    added_at  REAL NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS peers (
                    address   TEXT PRIMARY KEY,
                    last_seen REAL NOT NULL
                )
            """)

            conn.commit()

            cursor.execute("SELECT COUNT(*) FROM blocks")
            if cursor.fetchone()[0] == 0:
                genesis = BrunoBlock(
                    index=0,
                    previous_hash="0",
                    transactions=[{
                        "sender":   "SISTEMA",
                        "receiver": GENESIS_ADDRESS,
                        "amount":   GENESIS_REWARD,
                    }],
                    difficulty=GENESIS_DIFFICULTY,
                    nonce=GENESIS_NONCE,
                    timestamp=GENESIS_TIMESTAMP,
                )
                if not genesis.hash.startswith("0" * GENESIS_DIFFICULTY):
                    print("[GENESIS] Nonce fixo inválido — minerando…")
                    genesis.mine_block()
                    print(f"[GENESIS] ✅ Novo nonce: {genesis.nonce}")
                    print(f"[GENESIS]    Copie para GENESIS_NONCE no código.")
                self.db.insert_block(genesis)

    def _load_persistent_state(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                cursor.execute("SELECT tx_json FROM mempool ORDER BY added_at")
                self.mempool = [json.loads(row[0]) for row in cursor.fetchall()]

                cursor.execute("SELECT address FROM peers")
                for row in cursor.fetchall():
                    try:
                        ip, port = row[0].rsplit(":", 1)
                        self.connected_peers.add((ip, int(port)))
                    except Exception:
                        pass

            print(f"[STATE] {len(self.mempool)} txs restauradas do disco")
            print(f"[STATE] {len(self.connected_peers)} peers restaurados")
        except Exception as e:
            print(f"[STATE] Falha ao restaurar estado: {e}")

    def _save_mempool_tx(self, tx: Dict[str, Any]):
        try:
            sig = tx.get("signature", "")
            if not sig:
                return
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO mempool (signature, tx_json, added_at) "
                    "VALUES (?, ?, ?)",
                    (sig, json.dumps(tx), time.time()),
                )
                conn.commit()
        except Exception as e:
            print(f"[MEMPOOL] Falha ao salvar: {e}")

    def _remove_mempool_tx(self, signature: str):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM mempool WHERE signature = ?", (signature,))
                conn.commit()
        except Exception:
            pass

    def _save_peer(self, ip: str, port: int):
        try:
            addr = f"{ip}:{port}"
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO peers (address, last_seen) VALUES (?, ?)",
                    (addr, time.time()),
                )
                conn.commit()
        except Exception:
            pass

    # ==========================================================
    # UTILITÁRIOS
    # ==========================================================
    def get_p2p_port(self) -> int:
        return self.p2p_port

    def _get_local_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def _calculate_next_difficulty(self) -> int:
        with self.db_lock:
            chain = self.db.get_raw_chain()
        if not chain:
            return GENESIS_DIFFICULTY

        latest_block = chain[-1]
        if latest_block["index"] < DIFFICULTY_ADJUSTMENT_INTERVAL:
            return latest_block["difficulty"]

        if latest_block["index"] % DIFFICULTY_ADJUSTMENT_INTERVAL != 0:
            return latest_block["difficulty"]

        prev_adjustment_block = chain[-DIFFICULTY_ADJUSTMENT_INTERVAL]
        time_expected = TARGET_BLOCK_TIME * DIFFICULTY_ADJUSTMENT_INTERVAL
        time_taken = latest_block["timestamp"] - prev_adjustment_block["timestamp"]
        current_diff = latest_block["difficulty"]

        if time_taken < (time_expected / 2):
            return current_diff + 1
        elif time_taken > (time_expected * 2):
            return max(1, current_diff - 1)
        return current_diff

    # ==========================================================
    # P2P — ENVIO E RECEPÇÃO
    # ==========================================================
    def _send_msg(self, sock: socket.socket, payload: bytes):
        size = len(payload).to_bytes(4, "big")
        sock.sendall(size + payload)

    def _recv_msg(self, sock: socket.socket,
                  max_size: int = MAX_MESSAGE_SIZE) -> bytes:
        size_data = b""
        while len(size_data) < 4:
            chunk = sock.recv(4 - len(size_data))
            if not chunk:
                raise ConnectionError("Conexão fechada antes do tamanho")
            size_data += chunk

        size = int.from_bytes(size_data, "big")
        if size > max_size:
            raise ValueError(f"Mensagem muito grande: {size} bytes")

        data = b""
        while len(data) < size:
            chunk = sock.recv(min(65536, size - len(data)))
            if not chunk:
                raise ConnectionError("Conexão fechada durante dados")
            data += chunk
        return data

    def _recv_msg_str(self, sock: socket.socket) -> str:
        return self._recv_msg(sock).decode("utf-8")

    # ==========================================================
    # SERVIDOR P2P
    # ==========================================================
    def _start_p2p_server(self):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(("0.0.0.0", self.p2p_port))
        server_socket.listen(10)
        print(f"[P2P] Servidor rodando na porta {self.p2p_port}")

        while True:
            client_conn = None
            try:
                client_conn, client_addr = server_socket.accept()
                client_conn.settimeout(SOCKET_TIMEOUT)
                data = self._recv_msg_str(client_conn)

                if data.startswith("HELLO:"):
                    try:
                        info = json.loads(data.split(":", 1)[1])
                        peer_ip   = info.get("ip", client_addr[0])
                        peer_port = int(info.get("port", 6001))
                        with self.peers_lock:
                            self.connected_peers.add((peer_ip, peer_port))
                        self._save_peer(peer_ip, peer_port)
                        self._send_msg(client_conn, b"HELLO_OK")
                        print(f"[P2P] 👋 Peer conectado: {peer_ip}:{peer_port}")
                    except Exception as e:
                        print(f"[P2P] Handshake falhou: {e}")

                elif data == "GET_HEIGHT":
                    with self.db_lock:
                        chain = self.db.get_raw_chain()
                    self._send_msg(client_conn, str(len(chain)).encode("utf-8"))

                elif data == "GET_CHAIN":
                    with self.db_lock:
                        chain = self.db.get_raw_chain()
                    self._send_msg(client_conn, json.dumps(chain).encode("utf-8"))

                elif data.startswith("BROADCAST_TX:"):
                    tx_data = json.loads(data.split(":", 1)[1])
                    if self._verify_tx_structure(tx_data):
                        self._adicionar_na_mempool(tx_data)

                elif data.startswith("SYNC_CHAIN:"):
                    incoming_chain = json.loads(data.split(":", 1)[1])
                    self._resolve_consensus(incoming_chain)

            except socket.timeout:
                pass
            except Exception as e:
                print(f"[P2P] Erro: {e}")
            finally:
                if client_conn:
                    try:
                        client_conn.close()
                    except Exception:
                        pass

    # ==========================================================
    # MEMPOOL COM LIMITE
    # ==========================================================
    def _adicionar_na_mempool(self, tx: Dict[str, Any]) -> bool:
        with self.mempool_lock:
            sig = tx.get("signature")
            for existing in self.mempool:
                if existing.get("signature") == sig:
                    return False

            if len(self.mempool) >= MAX_MEMPOOL_SIZE:
                self.mempool.sort(key=lambda t: float(t.get("fee", 0)))
                menor_fee = float(self.mempool[0].get("fee", 0))
                nova_fee  = float(tx.get("fee", 0))
                if nova_fee <= menor_fee:
                    return False
                removida = self.mempool.pop(0)
                self._remove_mempool_tx(removida.get("signature", ""))

            self.mempool.append(tx)
            self._save_mempool_tx(tx)
            return True

    # ==========================================================
    # DISCOVERY (BOOTSTRAP ESTÁTICO)
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
                print(f"[DISCOVERY] Falha {ip}:{port} — {e}")

    # ==========================================================
    # BROADCAST
    # ==========================================================
    def _broadcast_transaction_to_network(self, tx: Dict[str, Any]):
        with self.peers_lock:
            peers = list(self.connected_peers)

        payload = ("BROADCAST_TX:" + json.dumps(tx)).encode("utf-8")

        for ip, port in peers:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(2.0)
                    s.connect((ip, int(port)))
                    hello = json.dumps({
                        "ip":   self._get_local_ip(),
                        "port": self.p2p_port,
                    })
                    self._send_msg(s, ("HELLO:" + hello).encode("utf-8"))
                    # ✅ BUG #3 CORRIGIDO: usa _recv_msg
                    self._recv_msg(s)
                    self._send_msg(s, payload)
            except Exception:
                with self.peers_lock:
                    self.connected_peers.discard((ip, port))

    def _broadcast_chain_to_peers(self):
        try:
            with self.db_lock:
                chain = self.db.get_raw_chain()
            payload = ("SYNC_CHAIN:" + json.dumps(chain)).encode("utf-8")

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

    # ==========================================================
    # SYNC
    # ==========================================================
    def connect_and_sync(self, ip: str, port: int) -> Dict[str, str]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(3.0)
                s.connect((ip, int(port)))
                hello = json.dumps({
                    "ip":   self._get_local_ip(),
                    "port": self.p2p_port,
                })
                self._send_msg(s, ("HELLO:" + hello).encode("utf-8"))
                # ✅ BUG #3 CORRIGIDO: usa _recv_msg
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
                return {"status": "sucesso",
                        "message": "Sua blockchain já está atualizada."}

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s_c:
                s_c.settimeout(15.0)
                s_c.connect((ip, int(port)))
                self._send_msg(s_c, b"GET_CHAIN")
                response = self._recv_msg_str(s_c)

            with self.peers_lock:
                self.connected_peers.add((ip, int(port)))
            self._save_peer(ip, int(port))

            remote_chain = json.loads(response)
            return {"status": "sucesso",
                    "message": self._resolve_consensus(remote_chain)}

        except Exception as e:
            return {"status": "erro", "message": str(e)}

    # ==========================================================
    # VALIDAÇÃO
    # ==========================================================
    def _validate_address(self, address: str) -> bool:
        if not isinstance(address, str) or not address.startswith("brn1") or len(address) != 44:
            raise ValueError(f"Formato/Tamanho inválido: {address}")
        try:
            int(address[4:], 16)
        except ValueError:
            raise ValueError("Endereço com hex inválido.")
        return True

    def _verify_tx_structure(self, tx: Dict[str, Any]) -> bool:
        """Valida uma tx de usuário (SISTEMA é rejeitada)."""
        if not isinstance(tx, dict):
            return False

        # ✅ SISTEMA nunca vem pela mempool
        if tx.get("sender") == "SISTEMA":
            return False

        required = ["sender", "receiver", "amount", "public_key",
                    "signature", "timestamp"]
        if not all(k in tx for k in required):
            return False

        try:
            amount = float(tx["amount"])
            if amount <= 0:
                return False

            self._validate_address(tx["sender"])
            self._validate_address(tx["receiver"])

            payload = {
                "sender":    tx["sender"],
                "receiver":  tx["receiver"],
                "amount":    amount,
                "timestamp": tx["timestamp"],
            }
            if "fee" in tx:
                payload["fee"] = tx["fee"]

            return WalletManager.verify_signature(
                tx["public_key"], payload, tx["signature"]
            )
        except Exception:
            return False

    def _validate_block(self, block_data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Valida um bloco completo.
        ✅ BUG #2 CORRIGIDO: usa BOUNDS (min/max), não valor exato.
        """
        try:
            block = BrunoBlock(
                block_data["index"],
                block_data["previous_hash"],
                block_data["transactions"],
                block_data["difficulty"],
                block_data["nonce"],
                block_data["timestamp"],
                block_data["hash"],
            )
        except Exception as e:
            return False, f"Bloco malformado: {e}"

        # 1. Hash confere?
        if block.calculate_hash() != block_data["hash"]:
            return False, "Hash do bloco incompatível"

        # 2. Network ID
        if block.network_id != BRN_NETWORK_ID:
            return False, f"Network ID inválido ({block.network_id})"

        # 3. Difficulty
        difficulty = int(block_data["difficulty"])
        if difficulty < 1:
            return False, "Dificuldade inválida"

        # 4. PoW
        target = "0" * difficulty
        if not block_data["hash"].startswith(target):
            return False, "PoW inválida"

        # 5. Transações
        transactions = block_data.get("transactions", [])
        if not isinstance(transactions, list) or not transactions:
            return False, "Bloco sem transações"

        # ✅ 6. Primeira tx deve ser SISTEMA
        first_tx = transactions[0]
        if first_tx.get("sender") != "SISTEMA":
            return False, "Primeira tx deve ser coinbase (SISTEMA)"

        # ✅ BUG #2 CORRIGIDO: valida com BOUNDS
        base_reward = current_reward(int(block_data["index"]))

        fees_in_block = 0.0
        for tx in transactions[1:]:
            try:
                fees_in_block += float(tx.get("fee", 0))
            except (ValueError, TypeError):
                pass

        try:
            cb_total = sum(float(o["amount"]) for o in first_tx["outputs"])
        except (KeyError, ValueError, TypeError) as e:
            return False, f"Coinbase com outputs inválidos: {e}"

        max_allowed  = base_reward + fees_in_block
        min_required = base_reward
        tolerancia   = 0.0001

        if cb_total > max_allowed + tolerancia:
            return False, (
                f"Coinbase excessiva: {cb_total:.6f} > "
                f"máx {max_allowed:.6f} (base {base_reward} + fees {fees_in_block})"
            )

        if cb_total < min_required - tolerancia:
            return False, (
                f"Coinbase insuficiente: {cb_total:.6f} < "
                f"mín {min_required:.6f}"
            )

        # ✅ 7. Demais txs NÃO podem ser SISTEMA
        for i, tx in enumerate(transactions[1:], 1):
            if tx.get("sender") == "SISTEMA":
                return False, f"SISTEMA em posição inválida ({i})"
            if not self._verify_tx_structure(tx):
                return False, f"Tx inválida na posição {i}"

        return True, "OK"

    def _resolve_consensus(self, remote_chain: List[Dict[str, Any]]) -> str:
        with self.db_lock:
            local_chain = self.db.get_raw_chain()

        if len(remote_chain) <= len(local_chain):
            return "Cadeia local já é dominante."

        if remote_chain[0]["hash"] != local_chain[0]["hash"]:
            return "Gênesis diferente — rede incompatível"

        for i in range(1, len(remote_chain)):
            if remote_chain[i]["previous_hash"] != remote_chain[i - 1]["hash"]:
                return f"Elos quebrados na posição {i}"

        for block_data in remote_chain:
            ok, msg = self._validate_block(block_data)
            if not ok:
                return f"Bloco #{block_data.get('index')} rejeitado: {msg}"

        with self.db_lock:
            self.db.replace_chain(remote_chain)
        return f"Sincronizado para {len(remote_chain)} blocos."

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
            "chain":                chain,
            "length":               len(chain),
            "mempool_size":         mempool_size,
            "is_mining":            self.is_mining,
            "current_difficulty":   chain[-1]["difficulty"] if chain else GENESIS_DIFFICULTY,
            "coin":                 COIN_SYMBOL,
            "block_reward_current": current_reward(next_index),
            "transaction_fee":      TRANSACTION_FEE_FIXED,
            "burn_percentage":      BURN_PERCENTAGE,
            "next_halving_at":      ((next_index // HALVING_INTERVAL) + 1) * HALVING_INTERVAL,
            "network_id":           BRN_NETWORK_ID,
            "peers_connected":      len(self.connected_peers),
        }

    def generate_wallet(self):
        return WalletManager.generate_keypair()

    def _get_balance_unlocked(self, address: str) -> float:
        """
        Calcula saldo SEM adquirir lock.
        ✅ BUG #1 CORRIGIDO: NÃO deduzir a taxa separadamente.
        A taxa já está implícita no 'amount' que o sender não recebe de volta.
        """
        balance = 0.0
        with self.db_lock:
            chain = self.db.get_raw_chain()

        for block in chain:
            for tx in block["transactions"]:
                sender   = tx.get("sender")
                receiver = tx.get("receiver")
                amount   = float(tx.get("amount", 0))

                if sender == address:
                    balance -= amount
                    # ✅ BUG #1: NÃO deduzir fee separadamente
                if receiver == address:
                    balance += amount

        return balance

    def get_balance(self, address: str) -> Dict[str, Any]:
        try:
            self._validate_address(address)
            with self.mempool_lock:
                balance = self._get_balance_unlocked(address)
            return {"address": address, "balance": balance}
        except ValueError as e:
            return {"status": "erro", "message": str(e)}

    def send_funds(
        self,
        sender: str,
        receiver: str,
        amount: float,
        spend_secret_key: str,
        public_key: str,
    ) -> Dict[str, Any]:
        try:
            self._validate_address(sender)
            self._validate_address(receiver)

            amount = float(amount)
            if amount <= 0:
                return {"status": "erro", "message": "Quantia inválida."}

            fee = calculate_tx_fee(amount)

            with self.mempool_lock:
                sender_balance = self._get_balance_unlocked(sender)

                pending_outflow = sum(
                    float(tx["amount"]) + float(tx.get("fee", 0))
                    for tx in self.mempool
                    if tx.get("sender") == sender
                )

                if (sender_balance - pending_outflow) < (amount + fee):
                    return {
                        "status": "erro",
                        "message": (
                            f"Saldo insuficiente. "
                            f"Disponível: {sender_balance - pending_outflow:.6f} BRN, "
                            f"necessário: {amount + fee:.6f} BRN "
                            f"(inclui taxa {fee})."
                        ),
                    }

                tx_payload = {
                    "sender":    str(sender).strip(),
                    "receiver":  str(receiver).strip(),
                    "amount":    amount,
                    "fee":       fee,
                    "timestamp": time.time(),
                }

                signature = WalletManager.sign_transaction(
                    spend_secret_key, tx_payload
                )
                full_tx = {
                    **tx_payload,
                    "public_key": public_key,
                    "signature":  signature,
                }

                for existing in self.mempool:
                    if existing.get("signature") == signature:
                        return {"status": "erro", "message": "Tx duplicada."}

                self.mempool.append(full_tx)
                self._save_mempool_tx(full_tx)

            threading.Thread(
                target=self._broadcast_transaction_to_network,
                args=(full_tx,),
                daemon=True,
            ).start()

            return {
                "status":  "sucesso",
                "message": f"Tx enviada! Taxa: {fee} BRN",
                "txid":    signature[:16],
            }

        except Exception as e:
            return {"status": "erro", "message": str(e)}

    def toggle_continuous_mining(self, miner_address: str) -> Dict[str, Any]:
        if self.is_mining:
            self.is_mining = False
            self.mining_stop_event.set()
            return {
                "status":    "sucesso",
                "message":   "Mineração pausada.",
                "is_mining": False,
            }

        try:
            self._validate_address(miner_address)
            self.is_mining = True
            self.mining_stop_event.clear()

            self.miner_thread = threading.Thread(
                target=self._continuous_mining_loop,
                args=(miner_address,),
                daemon=True,
            )
            self.miner_thread.start()

            return {
                "status":       "sucesso",
                "message":      "Mineração iniciada!",
                "is_mining":    True,
                "block_reward": current_reward(0),
            }
        except Exception as e:
            return {"status": "erro", "message": str(e)}

    # ==========================================================
    # LOOP DE MINERAÇÃO
    # ==========================================================
    def _continuous_mining_loop(self, miner_address: str):
        print(f
