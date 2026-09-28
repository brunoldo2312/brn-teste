from flask import Flask, request, jsonify
from flask_cors import CORS
import secrets
import json
import os

from wallet import Wallet
from blockchain import Blockchain

app = Flask(__name__)
CORS(app)

CHAIN = Blockchain("brn_v2_chain.db")
WALLETS_FILE = "user_wallets.json"

def carregar_wallets():
    if not os.path.exists(WALLETS_FILE):
        return {}
    with open(WALLETS_FILE, "r") as f:
        return json.load(f)

def salvar_wallets(w):
    with open(WALLETS_FILE, "w") as f:
        json.dump(w, f, indent=2)


# ============================================================
# GERAR CARTEIRA AUTOMATICAMENTE
# ============================================================
@app.route("/api/nova-carteira", methods=["POST"])
def nova_carteira():
    """
    Gera uma carteira BRN nova:
    - Chave privada
    - Chave pública
    - Endereço brn1...
    Retorna ao usuário (que DEVE guardar a chave privada).
    """
    try:
        w = Wallet()  # gera keypair novo
        dados = {
            "address": w.address,
            "private_key": w.private_key_hex(),
            "public_key": w.public_key_hex(),
        }

        # opcional: guarda no servidor
        wallets = carregar_wallets()
        wallets[w.address] = {
            "public_key": dados["public_key"],
            # NUNCA guarde private_key em texto puro em produção!
            # Aqui é só exemplo didático.
        }
        salvar_wallets(wallets)

        return jsonify({"success": True, **dados})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================
# CONSULTAR SALDO DE UM ENDEREÇO
# ============================================================
@app.route("/api/saldo/<address>", methods=["GET"])
def saldo(address):
    try:
        utxos = CHAIN.db.get_utxos(address)
        total = sum(u["amount"] for u in utxos)
        return jsonify({
            "success": True,
            "address": address,
            "balance_sats": total,
            "balance_brn": total / 10**8,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================
# LISTAR TRANSAÇÕES DE UM ENDEREÇO
# ============================================================
@app.route("/api/transacoes/<address>", methods=["GET"])
def transacoes(address):
    try:
        txs = CHAIN.db.get_txs_by_address(address)  # você implementa
        return jsonify({"success": True, "address": address, "transactions": txs})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================
# INFO DA CADEIA
# ============================================================
@app.route("/api/chain-info", methods=["GET"])
def chain_info():
    return jsonify({
        "success": True,
        "name": "BrunoCoin",
        "ticker": "BRN",
        "height": CHAIN.db.height(),
        "tip_hash": CHAIN.db.tip_hash(),
        "reward": CHAIN.current_reward(CHAIN.db.height() + 1),
        "difficulty": CHAIN.current_difficulty(),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)