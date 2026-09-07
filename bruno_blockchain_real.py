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
        return {"index": self.index, "timestamp": self.timestamp, "previous_hash": self.previous_hash, "transactions": self.transactions, "difficulty": self.difficulty, "nonce": self.nonce, "hash": self.hash}

class CriptoAPI:
    def __init__(self, node_port):
        self.p2p_port = node_port
        self.db_path = f"blockchain_node_{node_port}.db"
        self.db = BlockchainDB(self.db_path)
        self.mempool = []
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

    def _start_p2p_server(self):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(('0.0.0.0', self.p2p_port))
        server_socket.listen(10)
        while True:
            try:
                client_conn, client_addr = server_socket.accept()
                data = client_conn.recv(1024 * 1024).decode('utf-8')
                if client_addr != "127.0.0.1":
                    self.connected_peers.add((client_addr[0], self.p2p_port))
                if data == "GET_HEIGHT":
                    client_conn.sendall(str(len(self.db.get_raw_chain())).encode('utf-8'))
                elif data == "GET_CHAIN":
                    client_conn.sendall(json.dumps(self.db.get_raw_chain()).encode('utf-8'))
                elif data.startswith("BROADCAST_TX:"):
                    tx_data = json.loads(data.split(":", 1)[1])
                    if tx_data not in self.mempool: self.mempool.append(tx_data)
                elif data.startswith("SYNC_CHAIN:"):
                    incoming_chain = json.loads(data.split(":", 1)[1])
                    self._resolve_consensus(incoming_chain)
                client_conn.close()
            except Exception: pass

    def _run_bootstrap_discovery(self):
        time.sleep(2)
        for ip, port in BOOTSTRAP_PEERS:
            if port != self.p2p_port:
                try: self.connect_and_sync(ip, port)
                except Exception: pass

    def _broadcast_transaction_to_network(self, tx):
        for ip, port in list(self.connected_peers):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2.0)
                s.connect((ip, int(port)))
                s.sendall(f"BROADCAST_TX:{json.dumps(tx)}".encode('utf-8'))
                s.close()
            except Exception: self.connected_peers.discard((ip, port))

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
            client_socket.connect((ip, int(port)))
            client_socket.sendall("GET_CHAIN".encode('utf-8'))
            response = b""
            while True:
                chunk = client_socket.recv(4046)
                if not chunk: break
                response += chunk
            client_socket.close()
            self.connected_peers.add((ip, int(port)))
            return {"status": "sucesso", "message": self._resolve_consensus(json.loads(response.decode('utf-8')))}
        except Exception as e: return {"status": "erro", "message": str(e)}

    def _resolve_consensus(self, remote_chain) -> str:
        if len(remote_chain) <= len(self.db.get_raw_chain()): return "Cadeia local ja e dominante."
        for i in range(1, len(remote_chain)):
            if remote_chain[i]["previous_hash"] != remote_chain[i-1]["hash"]: return "Hashes corrompidos."
        self.db.replace_chain(remote_chain)
        return f"Sincronizado para {len(remote_chain)} blocos."

    def save_encrypted_wallet(self, filename, password, address, spend_secret_key):
        return WalletManager.save_encrypted_wallet(filename, password, address, spend_secret_key)

    def load_encrypted_wallet(self, filename, password):
        return WalletManager.load_encrypted_wallet(filename, password)

    def get_full_chain(self):
        return {"chain": self.db.get_raw_chain(), "length": len(self.db.get_raw_chain()), "mempool_size": len(self.mempool)}

    def generate_wallet(self):
        sk = secrets.token_hex(32)
        pk = hashlib.sha256(sk.encode()).hexdigest()
        return {"address": f"brn1{pk[:40]}", "spend_secret_key": sk}

    def get_balance(self, address):
        balance = 0.0
        for b in self.db.get_raw_chain():
            for tx in b["transactions"]:
                if tx.get("sender") == address: balance -= float(tx.get("amount", 0))
                if tx.get("receiver") == address: balance += float(tx.get("amount", 0))
        return {"address": address, "balance": balance}

    def send_funds(self, sender, receiver, amount):
        try:
            amount = float(amount)
            if amount <= 0: return {"status": "erro", "message": "Quantia invalida."}
            if self.get_balance(sender)["balance"] < amount: return {"status": "erro", "message": "Saldo insuficiente!"}
            nova_tx = {"sender": str(sender).strip(), "receiver": str(receiver).strip(), "amount": amount, "timestamp": time.time()}
            self.mempool.append(nova_tx)
            threading.Thread(target=self._broadcast_transaction_to_network, args=(nova_tx,), daemon=True).start()
            return {"status": "sucesso", "message": "Transacao adicionada!"}
        except Exception as e: return {"status": "erro", "message": str(e)}

    def mine_next_block(self, miner_address):
        local_chain = self.db.get_raw_chain()
        last_block = local_chain[-1]
        bloco_txs = [{"sender": "SISTEMA", "receiver": str(miner_address).strip(), "amount": BLOCK_REWARD}] + self.mempool
        new_block = BrunoBlock(last_block["index"] + 1, last_block["hash"], bloco_txs, difficulty=last_block["difficulty"])
        new_block.mine_block()
        self.db.insert_block(new_block)
        
        raw_chain_json = json.dumps(self.db.get_raw_chain())
        for ip, port in list(self.connected_peers):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect((ip, int(port)))
                s.sendall(f"SYNC_CHAIN:{raw_chain_json}".encode('utf-8'))
                s.close()
            except Exception: pass
        self.mempool.clear()
        return {"status": "sucesso", "block": new_block.to_dict()}

if __name__ == '__main__':
    p2p_port = 6001
    if len(sys.argv) > 1:
        try: p2p_port = int(sys.argv[1])
        except ValueError: pass
    AutoPortForwarder.open_port_on_router(p2p_port)
    api_local = CriptoAPI(p2p_port)
    webview.create_window(title=f"Carteira Nativa {COIN_NAME} (Porta: {p2p_port})", url="index.html", js_api=api_local, width=720, height=760, resizable=True)
    webview.start()
