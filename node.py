
import hashlib
import json
import time
import threading
import sqlite3
import os
import requests
from pathlib import Path
from functools import wraps
from flask import Flask, jsonify, request, Response
from cripto_wallet import WalletManager
from bruno_blockchain_real import (Blockchain, Block, Transaction, State,
                                   Finality, NATIVE_ASSET, NATIVE_ASSET_ISSUER,
                                   DB_PATH, BLOCK_REWARD, MIN_STAKE,
                                   FINALITY_INTERVAL, FINALITY_THRESHOLD,
                                   FAUCET_ADDRESS, FAUCET_AMOUNT,
                                   FAUCET_COOLDOWN, REGULATOR_ADDRESS,
                                   GENESIS_ALLOCATIONS, NETWORK_ID)

P2P_PORT = int(os.environ.get("BRN_P2P_PORT", "7777"))
TARGET_BLOCK_TIME = int(os.environ.get("BRN_TARGET_BLOCK_TIME", "10"))
WEB_USER = os.environ.get("BRN_WEB_USER", "admin")
WEB_PASS = os.environ.get("BRN_WEB_PASS", "")

_global_node_ref = None
_blockchain_instance = None

app = Flask(__name__)


def require_auth(f):
    @wraps(f)
    def deco(*a, **kw):
        if not WEB_PASS:
            return Response("BRN_WEB_PASS nao definido.", 500)
        auth = request.authorization
        if not auth or auth.username != WEB_USER or auth.password != WEB_PASS:
            return Response("Acesso negado.", 401,
                            {"WWW-Authenticate": 'Basic realm="BRN"'})
        return f(*a, **kw)
    return deco


@app.route("/api/status")
def api_status():
    if _blockchain_instance is None:
        return jsonify(error="nao inicializada"), 503
    bc = _blockchain_instance
    return jsonify(network_id=NETWORK_ID, height=len(bc.chain),
                   last_hash=bc.last_block.hash, mempool=len(bc.pending),
                   finalized=bc.finality.finalized_height,
                   assets=list(bc.registry.assets.keys()))


@app.route("/api/portfolio/<address>")
@require_auth
def api_portfolio(address):
    if _blockchain_instance is None:
        return jsonify(error="nao inicializada"), 503
    return jsonify(portfolio=_blockchain_instance.portfolio(address))


@app.route("/api/faucet", methods=["POST"])
@require_auth
def api_faucet():
    if _blockchain_instance is None:
        return jsonify(ok=False, msg="nao inicializada"), 503
    d = request.get_json(silent=True) or {}
    addr = (d.get("address") or "").strip()
    if not addr.startswith("brn1"):
        return jsonify(ok=False, msg="endereco invalido"), 400
    sk = d.get("private_key", ""); pk = d.get("public_key", "")
    if not sk or not pk:
        return jsonify(ok=False, msg="chaves obrigatorias"), 400
    return jsonify(_blockchain_instance.faucet(addr, sk, pk))


@app.route("/api/transfer", methods=["POST"])
@require_auth
def api_transfer():
    if _blockchain_instance is None:
        return jsonify(ok=False, msg="nao inicializada"), 503
    d = request.get_json(silent=True) or {}
    try:
        tx = Transaction.build(
            tx_type=d.get("type", "transfer"),
            asset_id=d["asset_id"], sender_address=d["from"],
            receiver_address=d["to"], amount=float(d["amount"]),
            nonce=int(d["nonce"]), private_key_hex=d["private_key"],
            public_key_hex=d["public_key"], metadata=d.get("metadata"))
    except (KeyError, ValueError) as e:
        return jsonify(ok=False, msg=f"payload invalido: {e}"), 400
    return jsonify(_blockchain_instance.add_transaction(tx))


@app.route("/api/mine", methods=["POST"])
@require_auth
def api_mine():
    if _blockchain_instance is None:
        return jsonify(ok=False, msg="nao inicializada"), 503
    blk = _blockchain_instance.produce_block()
    if blk is None:
        return jsonify(ok=False, msg="nao foi possivel produzir bloco.")
    return jsonify(ok=True, block=blk.to_dict())


@app.route("/api/chain", methods=["GET"])
def api_chain():
    if _blockchain_instance is None:
        return jsonify(error="nao inicializada"), 503
    return jsonify(_blockchain_instance.to_dict())


@app.route("/api/slashing")
@require_auth
def api_slashing():
    if _blockchain_instance is None: return jsonify([])
    return jsonify(_blockchain_instance.slashing_report())


@app.route("/api/finality")
@require_auth
def api_finality():
    if _blockchain_instance is None: return jsonify({})
    return jsonify(_blockchain_instance.finality_report())


@app.route("/p2p/tx", methods=["POST"])
def p2p_tx():
    if _blockchain_instance is None: return jsonify(ok=False), 503
    tx = request.get_json(silent=True) or {}
    r = _blockchain_instance.add_transaction(tx)
    if r.get("ok") and _global_node_ref:
        _global_node_ref.broadcast_tx(tx)
    return jsonify(r)


@app.route("/p2p/chain", methods=["GET"])
def p2p_chain():
    if _blockchain_instance is None: return jsonify(error="nao inicializada"), 503
    return jsonify(_blockchain_instance.to_dict())


@app.route("/p2p/block", methods=["POST"])
def p2p_block():
    if _blockchain_instance is None: return jsonify(ok=False), 503
    d = request.get_json(silent=True) or {}
    try: blk = Block.from_dict(d)
    except Exception as e: return jsonify(ok=False, msg=str(e)), 400
    if not blk.verify():
        _blockchain_instance._slash(blk.validator,
                                    f"bloco invalido #{blk.index} via P2P",
                                    block_idx=blk.index)
        return jsonify(ok=False, msg="bloco invalido"), 400
    return jsonify(ok=True)


class Node:
    def __init__(self, db_path=DB_PATH, identity=None, p2p_port=P2P_PORT,
                 web_port=None, seed_peers=None):
        global _global_node_ref, _blockchain_instance
        self.db_path = db_path
        self.p2p_port = p2p_port
        self.web_port = int(web_port or os.environ.get("BRN_WEB_PORT", "5000"))
        self.seed_peers = list(seed_peers or [])
        self.peers = set(self.seed_peers)
        self.running = False
        self.lock = threading.RLock()
        self.identity = identity or WalletManager.generate_keypair()
        self.bc = Blockchain(db_path=db_path, node_identity=self.identity,
                             regulator_address=REGULATOR_ADDRESS)
        self.bc.node_identity = self.identity
        _blockchain_instance = self.bc
        _global_node_ref = self

    def register_external_peer(self, endpoint):
        if not endpoint or ":" not in endpoint: return
        with self.lock:
            if endpoint not in self.peers:
                self.peers.add(endpoint)
                print(f"[p2p] peer registrado: {endpoint}")

    def broadcast_tx(self, tx):
        for p in list(self.peers):
            try: requests.post(f"http://{p}/p2p/tx", json=tx, timeout=3)
            except Exception: pass

    def broadcast_block(self, blk):
        for p in list(self.peers):
            try: requests.post(f"http://{p}/p2p/block", json=blk, timeout=3)
            except Exception: pass

    def sync_with_peers(self):
        for p in list(self.peers):
            try:
                r = requests.get(f"http://{p}/p2p/chain", timeout=5)
                if r.status_code == 200:
                    self.bc.replace_chain(r.json()["chain"])
            except Exception: pass

    def _consensus_loop(self):
        while self.running:
            try:
                blk = self.bc.produce_block()
                if blk:
                    print(f"[consenso] bloco #{blk.index} ({len(blk.transactions)} tx)")
                    self.broadcast_block(blk.to_dict())
            except Exception as e:
                print(f"[consenso] erro: {e}")
            time.sleep(TARGET_BLOCK_TIME)

    def _p2p_loop(self):
        while self.running:
            try: self.sync_with_peers()
            except Exception: pass
            time.sleep(30)

    def start(self):
        self.running = True
        threading.Thread(target=self._consensus_loop, daemon=True,
                         name="consensus").start()
        threading.Thread(target=self._p2p_loop, daemon=True,
                         name="p2p-sync").start()
        print(f"[node] P2P em 0.0.0.0:{self.p2p_port} | web :{self.web_port}")
        print(f"[node] endereco: {self.identity['address']}")
        app.run(host="0.0.0.0", port=self.web_port, debug=False,
                use_reloader=False, threaded=True)


if __name__ == "__main__":
    import sys
    port_arg = None; db_arg = None
    for arg in sys.argv[1:]:
        if arg.isdigit() and 1 <= int(arg) <= 65535:
            port_arg = int(arg)
        else:
            db_arg = arg
    db = db_arg or DB_PATH
    port = port_arg or int(os.environ.get("BRN_WEB_PORT", "5000"))
    os.environ["BRN_WEB_PORT"] = str(port)
    print(f"[node] iniciando | DB={db} | web_port={port}")

    identity_file = Path(f"{db}.identity.json")
    identity = None
    if identity_file.exists():
        try:
            identity = json.loads(identity_file.read_text())
            print(f"[node] identidade: {identity['address']}")
        except Exception: identity = None
    if identity is None:
        identity = WalletManager.generate_keypair()
        try:
            identity_file.write_text(json.dumps(identity, indent=2))
            os.chmod(identity_file, 0o600)
        except OSError: pass
        print(f"[node] identidade criada: {identity['address']}")

    Node(db_path=db, identity=identity, p2p_port=P2P_PORT,
         web_port=port).start()
