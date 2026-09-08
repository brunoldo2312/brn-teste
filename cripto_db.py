import sqlite3
import json


class BlockchainDB:
    def __init__(self, db_path="blockchain.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS blocks (
                    id_index INTEGER PRIMARY KEY,
                    timestamp REAL,
                    previous_hash TEXT,
                    transactions TEXT,
                    difficulty INTEGER,
                    nonce INTEGER,
                    hash TEXT UNIQUE
                )
            ''')
            conn.commit()

    def insert_block(self, block):
        """Insere um bloco (objeto ou dicionário) no banco."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if hasattr(block, 'index'):
                # Objeto
                cursor.execute(
                    'INSERT OR IGNORE INTO blocks VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (block.index, block.timestamp, block.previous_hash,
                     json.dumps(block.transactions), block.difficulty,
                     block.nonce, block.hash)
                )
            else:
                # Dicionário
                cursor.execute(
                    'INSERT OR IGNORE INTO blocks VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (block["index"], block["timestamp"], block["previous_hash"],
                     json.dumps(block["transactions"]), block["difficulty"],
                     block["nonce"], block["hash"])
                )
            conn.commit()

    def replace_chain(self, new_chain):
        """Substitui toda a cadeia por uma nova (usado na sincronização)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM blocks')
            for block in new_chain:
                if hasattr(block, 'index'):
                    cursor.execute(
                        'INSERT INTO blocks VALUES (?, ?, ?, ?, ?, ?, ?)',
                        (block.index, block.timestamp, block.previous_hash,
                         json.dumps(block.transactions), block.difficulty,
                         block.nonce, block.hash)
                    )
                else:
                    cursor.execute(
                        'INSERT INTO blocks VALUES (?, ?, ?, ?, ?, ?, ?)',
                        (block["index"], block["timestamp"], block["previous_hash"],
                         json.dumps(block["transactions"]), block["difficulty"],
                         block["nonce"], block["hash"])
                    )
            conn.commit()

    def get_chain(self):
        """Retorna a cadeia completa como lista de dicionários."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM blocks ORDER BY id_index ASC')
            rows = cursor.fetchall()
            chain = []
            for row in rows:
                block = {
                    "index": row[0],
                    "timestamp": row[1],
                    "previous_hash": row[2],
                    "transactions": json.loads(row[3]),
                    "difficulty": row[4],
                    "nonce": row[5],
                    "hash": row[6]
                }
                chain.append(block)
            return chain

    def get_balance(self, address):
        """Calcula o saldo de um endereço (varredura simples)."""
        chain = self.get_chain()
        balance = 0
        for block in chain:
            for tx in block["transactions"]:
                if tx["to"] == address:
                    balance += tx["amount"]
                if tx.get("from") == address:
                    balance -= tx["amount"]
        return balance