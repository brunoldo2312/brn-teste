import hashlib
import time
import json
import sqlite3
import secrets
import socket
import threading
import sys
import webview
from cripto_wallet import WalletManager
from cripto_db import BlockchainDB
from cripto_p2p_network import AutoPortForwarder

COIN_NAME = "Bruno"
COIN_SYMBOL = "BRN"
BLOCK_REWARD = 50.0
MONERO_FORK_NETWORK_ID = [0xAA, 0xBB, 0xCC, 0xDD, 0x11, 0x22, 0x33, 0x44]

BOOTSTRAP_PEERS = [
    ("192.168.0.17", 6001)
]

class BrunoBlock:
    def __init__(self, index, previous_hash, transactions, difficulty=4, nonce=0, timestamp=None, block_hash=None):
        self.index = int(index)
        self.timestamp = float(timestamp) if timestamp else time.time()
        self.previous_hash = str(previous_hash)
        self.transactions = transactions if isinstance(transactions, list) else json.loads(transactions)
        self.difficulty = int(difficulty)
        self.nonce = int(nonce)
        self.network_id = MONERO_FORK_NETWORK_ID
        self.hash = str(block_hash) if block_hash else self.calculate_hash()

    def calculate_hash(self) -> str:
        block_string = json.dumps({
            "index": self.index, "timestamp": self.timestamp, "previous_hash": self.previous_hash,
            "transactions": self.transactions, "difficulty": self.difficulty, "nonce": self.nonce, "network_id": self.network_id
        }, sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()

    def mine_block(self):
        target = "0" * self.difficulty
        while self.hash[:self.difficulty] != target:
            self.nonce += 1
            self.hash = self.calculate_hash()
        return True

    def to_dict(self):
        """Converte bloco para dicionário (CORRIGIDO - estava truncado)"""
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "previous_hash": self.previous_hash,
            "transactions": self.transactions,
            "difficulty": self.difficulty,
            "nonce": self.nonce,
            "hash": self.hash
        }

class CriptoAPI:
    def __init__(self, node_port):
        self.p2p_port = node_port
        self.db_path = f"blockchain_node_{node_port}.db"
        self.db = BlockchainDB(self.db_path)
        self.mempool = []
        self.mempool_lock = threading.Lock()  # SEGURANÇA: Proteção contra race condition
        self.connected_peers = set()
        self._init_database()
        
        self.server_thread = threading.Thread(target=self._start_p2p_server)
        self.server_thread.daemon = True
        self.server_thread.start()
        
        threading.Thread(target=self._run_bootstrap_discovery, daemon=True).start()

    def _init_database(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS blocks (
                    id_index INTEGER PRIMARY KEY, timestamp REAL, previous_hash TEXT,
                    transactions TEXT, difficulty INTEGER, nonce INTEGER, hash TEXT
                )
            ''')
            cursor.execute('SELECT COUNT(*) FROM blocks')
            if cursor.fetchone()[0] == 0:
                genesis = BrunoBlock(0, "0", [{"sender": "SISTEMA", "receiver": "brn1111cd943fa71e1f91dcd62f52fc6138bc845ab", "amount": 100000.0}])
                genesis.mine_block()
                self.db.insert_block(genesis)

    def get_p2p_port(self):
        return self.p2p_port

    def _receive_all(self, sock, buffer_size=4096, max_size=10*1024*1024):
        """Recebe dados completos do socket com proteção de tamanho"""
        data = b""
        try:
            while True:
                chunk = sock.recv(buffer_size)
                if not chunk:
                    break
                data += chunk
                if len(data) > max_size:
                    raise ValueError(f"Mensagem excede tamanho máximo de {max_size} bytes")
        except socket.timeout:
            pass
        except Exception as e:
            print(f"Erro ao receber dados: {e}")
        return data.decode('utf-8', errors='ignore')

    def _start_p2p_server(self):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(('0.0.0.0', self.p2p_port))
        server_socket.listen(10)
        while True:
            try:
                client_conn, client_addr = server_socket.accept()
                client_conn.settimeout(5.0)
                data = self._receive_all(client_conn)
                
                # CORREÇÃO: client_addr é tuple (ip, port), não string
                if client_addr[0] != "127.0.0.1":
                    self.connected_peers.add((client_addr[0], self.p2p_port))
                
                if data == "GET_HEIGHT":
                    client_conn.sendall(str(len(self.db.get_raw_chain())).encode('utf-8'))
                elif data == "GET_CHAIN":
                    client_conn.sendall(json.dumps(self.db.get_raw_chain()).encode('utf-8'))
                elif data.startswith("BROADCAST_TX:"):
                    tx_data = json.loads(data.split(":", 1)[1])
                    with self.mempool_lock:
                        if tx_data not in self.mempool:
                            self.mempool.append(tx_data)
                elif data.startswith("SYNC_CHAIN:"):
                    incoming_chain = json.loads(data.split(":", 1)[1])
                    self._resolve_consensus(incoming_chain)
                client_conn.close()
            except Exception as e:
                pass

    def _run_bootstrap_discovery(self):
        time.sleep(2)
        for ip, port in BOOTSTRAP_PEERS:
            if port != self.p2p_port:
                try:
                    self.connect_and_sync(ip, port)
                except Exception:
                    pass

    def _broadcast_transaction_to_network(self, tx):
        for ip, port in list(self.connected_peers):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2.0)
                s.connect((ip, int(port)))
                s.sendall(f"BROADCAST_TX:{json.dumps(tx)}".encode('utf-8'))
                s.close()
            except Exception:
                self.connected_peers.discard((ip, port))

    def connect_and_sync(self, ip, port):
        try:
            s_height = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s_height.settimeout(3.0)
            s_height.connect((ip, int(port)))
            s_height.sendall("GET_HEIGHT".encode('utf-8'))
            remote_height = int(s_height.recv(1024).decode('utf-8'))
            s_height.close()
            
            if remote_height <= len(self.db.get_raw_chain()):
                return {"status": "sucesso", "message": "Sua blockchain ja esta atualizada."}

            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(10.0)
            client_socket.connect((ip, int(port)))
            client_socket.sendall("GET_CHAIN".encode('utf-8'))
            response = self._receive_all(client_socket)
            client_socket.close()
            self.connected_peers.add((ip, int(port)))
            return {"status": "sucesso", "message": self._resolve_consensus(json.loads(response))}
        except Exception as e:
            return {"status": "erro", "message": str(e)}

    def _validate_address(self, address):
        """Valida formato de endereço BRN1 (SEGURANÇA)"""
        if not isinstance(address, str):
            raise ValueError("Endereço deve ser uma string")
        if not address.startswith("brn1"):
            raise ValueError("Endereço deve começar com 'brn1'")
        if len(address) != 44:  # brn1 (4) + 40 hex
            raise ValueError(f"Tamanho de endereço inválido (esperado 44, recebido {len(address)})")
        try:
            int(address[4:], 16)
        except ValueError:
            raise ValueError("Endereço contém caracteres inválidos")
        return True

    def _validate_block(self, block_data):
        """Valida Proof-of-Work de um bloco (SEGURANÇA)"""
        block = BrunoBlock(
            block_data["index"],
            block_data["previous_hash"],
            block_data["transactions"],
            block_data["difficulty"],
            block_data["nonce"],
            block_data["timestamp"],
            block_data["hash"]
        )
        calculated_hash = block.calculate_hash()
        if calculated_hash != block_data["hash"]:
            return False, "Hash não corresponde"
        
        # Validar Proof-of-Work
        target = "0" * block_data["difficulty"]
        if not block_data["hash"].startswith(target):
            return False, "Proof-of-Work inválido"
        
        return True, "OK"

    def _resolve_consensus(self, remote_chain) -> str:
        """Resolve consenso com validação de PoW (CORRIGIDO)"""
        if len(remote_chain) <= len(self.db.get_raw_chain()):
            return "Cadeia local ja e dominante."
        
        # Validar linkagem de hashes
        for i in range(1, len(remote_chain)):
            if remote_chain[i]["previous_hash"] != remote_chain[i-1]["hash"]:
                return "Hashes corrompidos."
        
        # Validar Proof-of-Work de todos os blocos (SEGURANÇA ADICIONADA)
        for block_data in remote_chain:
            is_valid, message = self._validate_block(block_data)
            if not is_valid:
                return f"Bloco #{block_data['index']}: {message}"
        
        self.db.replace_chain(remote_chain)
        return f"Sincronizado para {len(remote_chain)} blocos."

    def save_encrypted_wallet(self, filename, password, address, spend_secret_key):
        return WalletManager.save_encrypted_wallet(filename, password, address, spend_secret_key)

    def load_encrypted_wallet(self, filename, password):
        return WalletManager.load_encrypted_wallet(filename, password)

    def get_full_chain(self):
        with self.mempool_lock:
            mempool_size = len(self.mempool)
        return {"chain": self.db.get_raw_chain(), "length": len(self.db.get_raw_chain()), "mempool_size": mempool_size}

    def generate_wallet(self):
        sk = secrets.token_hex(32)
        pk = hashlib.sha256(sk.encode()).hexdigest()
        return {"address": f"brn1{pk[:40]}", "spend_secret_key": sk}

    def get_balance(self, address):
        try:
            self._validate_address(address)
            balance = 0.0
            for b in self.db.get_raw_chain():
                for tx in b["transactions"]:
                    if tx.get("sender") == address:
                        balance -= float(tx.get("amount", 0))
                    if tx.get("receiver") == address:
                        balance += float(tx.get("amount", 0))
            return {"address": address, "balance": balance}
        except ValueError as e:
            return {"status": "erro", "message": str(e)}

    def send_funds(self, sender, receiver, amount):
        try:
            self._validate_address(sender)
            self._validate_address(receiver)
            amount = float(amount)
            if amount <= 0:
                return {"status": "erro", "message": "Quantia invalida."}
            if self.get_balance(sender).get("balance", 0) < amount:
                return {"status": "erro", "message": "Saldo insuficiente!"}
            
            nova_tx = {
                "sender": str(sender).strip(),
                "receiver": str(receiver).strip(),
                "amount": amount,
                "timestamp": time.time()
            }
            
            with self.mempool_lock:
                self.mempool.append(nova_tx)
            
            threading.Thread(target=self._broadcast_transaction_to_network, args=(nova_tx,), daemon=True).start()
            return {"status": "sucesso", "message": "Transacao adicionada!"}
        except ValueError as e:
            return {"status": "erro", "message": str(e)}
        except Exception as e:
            return {"status": "erro", "message": str(e)}

    def mine_next_block(self, miner_address):
        try:
            self._validate_address(miner_address)
            local_chain = self.db.get_raw_chain()
            last_block = local_chain[-1]
            
            with self.mempool_lock:
                bloco_txs = [
                    {"sender": "SISTEMA", "receiver": str(miner_address).strip(), "amount": BLOCK_REWARD}
                ] + list(self.mempool)
                self.mempool.clear()
            
            new_block = BrunoBlock(
                last_block["index"] + 1,
                last_block["hash"],
                bloco_txs,
                difficulty=last_block["difficulty"]
            )
            new_block.mine_block()
            self.db.insert_block(new_block)
            
            raw_chain_json = json.dumps(self.db.get_raw_chain())
            for ip, port in list(self.connected_peers):
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(3.0)
                    s.connect((ip, int(port)))
                    s.sendall(f"SYNC_CHAIN:{raw_chain_json}".encode('utf-8'))
                    s.close()
                except Exception:
                    pass
            
            return {"status": "sucesso", "block": new_block.to_dict()}
        except ValueError as e:
            return {"status": "erro", "message": str(e)}
        except Exception as e:
            return {"status": "erro", "message": str(e)}

if __name__ == '__main__':
    p2p_port = 6001
    if len(sys.argv) > 1:
        try:
            p2p_port = int(sys.argv[1])
        except ValueError:
            pass
    AutoPortForwarder.open_port_on_router(p2p_port)
    api_local = CriptoAPI(p2p_port)
    webview.create_window(title=f"Carteira Nativa {COIN_NAME} (Porta: {p2p_port})", url="index.html", js_api=api_local, width=720, height=760, resizable=True)
    webview.start()
