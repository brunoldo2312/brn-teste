
import os
import sys
import time
from pathlib import Path
import requests
import webview
from cripto_wallet import WalletManager

API_PORT = int(os.environ.get("BRN_WEB_PORT", "5000"))
API_URL = os.environ.get("BRN_API_URL", f"http://127.0.0.1:{API_PORT}")
WEB_USER = os.environ.get("BRN_WEB_USER", "admin")
WEB_PASS = os.environ.get("BRN_WEB_PASS", "")

if not WEB_PASS:
    print("ERRO: defina BRN_WEB_PASS antes de rodar.", file=sys.stderr)
    sys.exit(1)

AUTH = (WEB_USER, WEB_PASS)


class WalletApi:
    def generate_wallet(self):
        try: return WalletManager.generate_keypair()
        except Exception as e: return {"erro": str(e)}

    def validate_address(self, addr):
        return WalletManager.validate_address(addr)

    def portfolio(self, addr):
        if not WalletManager.validate_address(addr):
            return {"erro": "Endereco invalido."}
        try:
            r = requests.get(f"{API_URL}/api/portfolio/{addr}",
                             auth=AUTH, timeout=8)
            if r.status_code == 401: return {"erro": "401 - senha errada."}
            if r.status_code != 200: return {"erro": f"HTTP {r.status_code}"}
            return r.json().get("portfolio", {})
        except requests.exceptions.ConnectionError:
            return {"erro": f"No offline em {API_URL}."}
        except Exception as e:
            return {"erro": str(e)}

    def transfer(self, sender, to, asset_id, amount, sk, pk):
        if not WalletManager.validate_address(sender):
            return {"ok": False, "msg": "Remetente invalido."}
        if not WalletManager.validate_address(to):
            return {"ok": False, "msg": "Destinatario invalido."}
        if asset_id == "KYC":
            return {"ok": False, "msg": "KYC via API admin."}
        try: amount_f = float(amount)
        except (ValueError, TypeError):
            return {"ok": False, "msg": "Valor invalido."}
        if amount_f <= 0:
            return {"ok": False, "msg": "Valor deve ser positivo."}
        payload = {"type": "transfer", "asset_id": asset_id,
                   "from": sender, "to": to, "amount": amount_f,
                   "public_key": pk, "private_key": sk,
                   "nonce": int(time.time() * 1000)}
        try:
            r = requests.post(f"{API_URL}/api/transfer", auth=AUTH,
                              json=payload, timeout=8)
            return r.json()
        except requests.exceptions.ConnectionError:
            return {"ok": False, "msg": f"No offline em {API_URL}."}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def mine_block(self, addr):
        if not WalletManager.validate_address(addr):
            return {"ok": False, "msg": "Endereco invalido."}
        try:
            r = requests.post(f"{API_URL}/api/mine", auth=AUTH,
                              json={"validator_address": addr}, timeout=15)
            if r.status_code == 200: return r.json()
            return {"ok": False, "msg": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def call_faucet(self, addr, sk, pk):
        if not WalletManager.validate_address(addr):
            return {"ok": False, "msg": "Endereco invalido."}
        try:
            r = requests.post(f"{API_URL}/api/faucet", auth=AUTH,
                              json={"address": addr, "private_key": sk,
                                    "public_key": pk}, timeout=8)
            return r.json()
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def save_wallet(self, filename, password, address, sk, pk):
        return WalletManager.save_encrypted_wallet(filename, password, address, sk, pk)

    def load_wallet(self, filename, password):
        return WalletManager.load_encrypted_wallet(filename, password)

    def list_wallets(self):
        return WalletManager.list_wallets()

    def node_status(self):
        try:
            r = requests.get(f"{API_URL}/api/status", timeout=5)
            if r.status_code == 200:
                return {"ok": True, **r.json()}
            return {"ok": False, "msg": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"ok": False, "msg": str(e)}


def main():
    index_path = Path(__file__).parent / "index.html"
    if not index_path.exists():
        print(f"ERRO: {index_path} nao encontrado.", file=sys.stderr)
        sys.exit(1)
    api = WalletApi()
    webview.create_window(
        "BRN RWA - Carteira Digital",
        url=index_path.resolve().as_uri(),
        js_api=api, width=1020, height=880,
        min_size=(820, 640), background_color="#0d1117")
    try: webview.start(gui="gtk", debug=False)
    except Exception: webview.start(debug=False)


if __name__ == "__main__":
    main()
