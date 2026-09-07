import hashlib
import json
import secrets
import base64
import os

class WalletManager:
    @staticmethod
    def _derive_key(password: str, salt: bytes) -> bytes:
        key = password.encode()
        for _ in range(5000):
            key = hashlib.sha256(key + salt).digest()
        return key

    @classmethod
    def save_encrypted_wallet(cls, filename, password, address, spend_secret_key):
        try:
            if not filename.endswith(".wallet"): filename += ".wallet"
            wallet_data = {"address": address, "spend_secret_key": spend_secret_key}
            raw_json = json.dumps(wallet_data).encode('utf-8')
            salt = secrets.token_bytes(16)
            key = cls._derive_key(password, salt)
            cipher_stream = hashlib.sha256(key).digest()
            encrypted_bytes = bytearray()
            for i in range(len(raw_json)):
                if i % 32 == 0 and i > 0:
                    cipher_stream = hashlib.sha256(cipher_stream + key).digest()
                encrypted_bytes.append(raw_json[i] ^ cipher_stream[i % 32])
            file_payload = {
                "salt": base64.b64encode(salt).decode('utf-8'),
                "ciphertext": base64.b64encode(encrypted_bytes).decode('utf-8')
            }
            with open(filename, "w") as f: json.dump(file_payload, f)
            return {"status": "sucesso", "message": f"Arquivo {filename} salvo!"}
        except Exception as e: return {"status": "erro", "message": str(e)}

    @classmethod
    def load_encrypted_wallet(cls, filename, password):
        try:
            if not filename.endswith(".wallet"): filename += ".wallet"
            if not os.path.exists(filename): return {"status": "erro", "message": "Não encontrado."}
            with open(filename, "r") as f: file_payload = json.load(f)
            salt = base64.b64decode(file_payload["salt"])
            ciphertext = base64.b64decode(file_payload["ciphertext"])
            key = cls._derive_key(password, salt)
            cipher_stream = hashlib.sha256(key).digest()
            decrypted_bytes = bytearray()
            for i in range(len(ciphertext)):
                if i % 32 == 0 and i > 0:
                    cipher_stream = hashlib.sha256(cipher_stream + key).digest()
                decrypted_bytes.append(ciphertext[i] ^ cipher_stream[i % 32])
            decrypted_data = json.loads(decrypted_bytes.decode('utf-8'))
            return {"status": "sucesso", "address": decrypted_data["address"], "spend_secret_key": decrypted_data["spend_secret_key"]}
        except Exception as e: return {"status": "erro", "message": f"Senha incorreta: {str(e)}"}
