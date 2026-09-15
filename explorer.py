"""Explorador BRN — Flask puro, sem Qt/WebEngine."""
import os
from flask import Flask, jsonify, send_from_directory, request
from db import ChainDB

app = Flask(__name__, static_folder=".")
DB_PATH = os.environ.get("BRN_DB", "brn_v2_chain.db")
PORT = int(os.environ.get("BRN_EXPLORER_PORT", "8080"))

def _db() -> ChainDB:
    return ChainDB(DB_PATH)

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/api/status")
def status():
    db = _db()
    try:
        return jsonify({
            "height": db.height(),
            "tip": db.tip_hash(),
            "utxos": db.count_utxos(),
            "mempool": len(db.all_mempool(limit=10000)),
        })
    finally:
        db.close()

@app.route("/api/block/<int:h>")
def block(h):
    db = _db()
    try:
        b = db.get_block(h)
        return jsonify(b) if b else ({"error": "not found"}, 404)
    finally:
        db.close()

@app.route("/api/latest")
def latest():
    db = _db()
    try:
        top = db.height()
        out = [db.get_block(i) for i in range(max(0, top - 9), top + 1)]
        return jsonify(out)
    finally:
        db.close()

@app.route("/api/balance/<address>")
def balance(address):
    db = _db()
    try:
        return jsonify({
            "address": address,
            "balance": db.balance(address),
            "utxos": db.utxos_for(address),
        })
    finally:
        db.close()

@app.route("/api/mempool")
def mempool():
    db = _db()
    try:
        return jsonify(db.all_mempool(limit=200))
    finally:
        db.close()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, threaded=True, debug=False)