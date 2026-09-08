import hashlib
import time
import json
import sqlite3
import secrets
import socket
import threading
import sys
import logging
import hmac
import ipaddress
from cripto_db import BlockchainDB
from cripto_wallet import Wallet
from cripto_p2p_network import AutoPortForwarder, P2PNetwork

# Constantes da rede
MONERO_FORK_NETWORK_ID = "BRN_MAINNET"
INITIAL_COINS = 100000
REWARD = 50
DIFFICULTY_ADJUSTMENT_INTERVAL = 5
TARGET_BLOCK_TIME = 60  # segundos

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class BrunoBlock:
    def __init__(self, index, timestamp, previous_hash, transactions, difficulty, nonce=0, network_id=None):
        self.index = index
        self.timestamp = timestamp
        self.previous_hash = previous_hash
        self.transactions = transactions
        self.difficulty = difficulty
        self.nonce = nonce
        self.network_id = network_id if network_id is not None else MONERO_FORK_NETWORK_ID
        self.hash = self.calculate_hash()

    def calculate_hash(self):
        block_string = json.dumps({
            "index": self.index,
            "timestamp": self.timestamp,
            "previous_hash": self.previous_hash,
            "transactions": self.transactions,
            "difficulty": self.difficulty,
            "nonce": self.nonce,
            "network": self.network_id
        }, sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()

    @staticmethod
    def is_hash_valid(block_hash, difficulty):
        return block_hash.startswith('0' * difficulty)

    def mine_block(self):
        while not self.is_hash_valid(self.hash, self.difficulty):
            self.nonce += 1
            self.hash = self.calculate_hash()
        return self


class CriptoAPI:
    def __init__(self, port=6001):
        self.db = BlockchainDB()
        self.wallet = Wallet()
        self.port = port
        self.mempool = []
        self.lock = threading.Lock()
        self.mining = False
        self.mining_thread = None

        # Inicializar blockchain se vazia
        if len(self.db.get_chain()) == 0:
            genesis = BrunoBlock(0, int(time.time()), "0", [], 4)
            self.db.insert_block(genesis)
            logging.info("Bloco gênesis criado.")

        # Iniciar servidor P2P
        self.p2p = P2PNetwork(port, self)
        threading.Thread(target=self.p2p.start_server, daemon=True).start()

    def start_mining(self):
        if self.mining:
            return
        self.mining = True
        self.mining_thread = threading.Thread(target=self._continuous_mining)
        self.mining_thread.daemon = True
        self.mining_thread.start()
        logging.info("Mineração iniciada.")

    def stop_mining(self):
        self.mining = False
        if self.mining_thread:
            self.mining_thread.join(timeout=2)
        logging.info("Mineração parada.")

    def _continuous_mining(self):
        while self.mining:
            with self.lock:
                if len(self.mempool) == 0:
                    time.sleep(5)
                    continue

                chain = self.db.get_chain()
                last_block = chain[-1] if chain else None
                if not last_block:
                    continue

                # Transação de recompensa
                reward_tx = {
                    "from": "COINBASE",
                    "to": self.wallet.public_key,
                    "amount": REWARD,
                    "timestamp": int(time.time())
                }
                transactions = [reward_tx] + self.mempool[:10]

                # Ajuste de dificuldade
                if len(chain) % DIFFICULTY_ADJUSTMENT_INTERVAL == 0 and len(chain) >= DIFFICULTY_ADJUSTMENT_INTERVAL:
                    prev_interval = chain[-DIFFICULTY_ADJUSTMENT_INTERVAL:]
                    time_taken = sum((b.timestamp - prev_interval[i-1].timestamp) for i, b in enumerate(prev_interval[1:], 1))
                    expected_time = TARGET_BLOCK_TIME * DIFFICULTY_ADJUSTMENT_INTERVAL
                    difficulty = max(1, last_block.difficulty - 1) if time_taken > expected_time else last_block.difficulty + 1
                else:
                    difficulty = last_block.difficulty

                new_block = BrunoBlock(
                    len(chain),
                    int(time.time()),
                    last_block.hash,
                    transactions,
                    difficulty
                )

            # Mineração (sequencial, mas pode ser substituída por paralela)
            mined = new_block.mine_block()
            if mined:
                with self.lock:
                    if len(self.db.get_chain()) == mined.index:
                        self.db.insert_block(mined)
                        for tx in transactions:
                            if tx in self.mempool:
                                self.mempool.remove(tx)
                        self.p2p.broadcast_block(mined)
                        logging.info(f"Bloco minerado: {mined.hash}")
            time.sleep(1)

    def add_transaction(self, tx):
        if not self.wallet.verify_transaction(tx):
            return False
        with self.lock:
            self.mempool.append(tx)
            self.p2p.broadcast_transaction(tx)
        return True

    def get_balance(self, address):
        return self.db.get_balance(address)

    def get_chain(self):
        return self.db.get_chain()


if __name__ == "__main__":
    api = CriptoAPI()
    api.start_mining()
    while True:
        time.sleep(1)