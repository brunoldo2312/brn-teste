import sqlite3
import json

class BlockchainDB:
    def __init__(self, db_path):
        self.db_path = db_path

    def get_raw_chain(self):
        chain = []
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id_index, previous_hash, transactions, difficulty, nonce, timestamp, hash FROM blocks ORDER BY id_index ASC')
            for row in cursor.fetchall():
                chain.append({
                    "index": int(row[0]), 
                    "previous_hash": str(row[1]), 
                    "transactions": json.loads(row[2]),
                    "difficulty": int(row[3]), 
                    "nonce": int(row[4]), 
                    "timestamp": float(row[5]), 
                    "hash": str(row[6])
                })
        return chain

    def replace_chain(self, remote_chain):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM blocks')
            for b in remote_chain:
                cursor.execute('INSERT INTO blocks VALUES (?, ?, ?, ?, ?, ?, ?)', 
                               (b["index"], b["timestamp"], b["previous_hash"], json.dumps(b["transactions"]), b["difficulty"], b["nonce"], b["hash"]))
            conn.commit()

    def insert_block(self, b):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO blocks VALUES (?, ?, ?, ?, ?, ?, ?)', 
                           (b.index, b.timestamp, b.previous_hash, json.dumps(b.transactions), b.difficulty, b.nonce, b.hash))
            conn.commit()
