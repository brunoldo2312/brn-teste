import hashlib
import json
import secrets
import base64
import os
from ecdsa import SigningKey, VerifyingKey, SECP256k1, BadSignatureError

try:
    from cryptography.fernet import Fernet, InvalidToken
    FERNET_AVAILABLE = True
except ImportError:
    FERNET_AVAILABLE = False
    print("⚠️ AVISO: Instale 'cryptography' para seguranca adequada: pip install cryptography")

class WalletManager:
    @staticmethod
    def generate_keypair():
        """Gera par de chaves ECDSA (SECP256k1)"""
        sk = SigningKey.generate(curve=SECP256k1)
        vk = sk.verifying_key
        sk_hex = sk.to_string().hex()
        vk_hex = vk.to_string().hex()
        
        # Endereço derivado do hash SHA256 da chave publica
        pk_hash = hashlib.sha256(bytes.fromhex(vk_hex)).hexdigest()
        address = f"brn1{pk_hash[:40]}"
        return {
            "address": address,
            "spend_secret_key": sk_hex,
            "public_key": vk_hex
        }

    @staticmethod
    def sign_transaction(private_key_hex: str, message_dict: dict) -> str:
        """Assina digitalmente uma transacao"""
        sk = SigningKey.from_string(bytes.fromhex(private_key_hex), curve=SECP256k1)
        msg_bytes = json.dumps(message_dict, sort_keys=True).encode('utf-8')
        signature = sk.sign(msg_bytes)
        return signature.hex()

    @staticmethod
    def verify_signature(public_key_hex: str, message_dict: dict, signature_hex: str) -> bool:
        """Valida a assinatura digital de uma transacao"""
        try:
            vk = VerifyingKey.from_string(bytes.fromhex(public_key_hex), curve=SECP256k1)
            msg_bytes = json.dumps(message_dict, sort_keys=True).encode('utf-8')
            return vk.verify(bytes.fromhex(signature_hex), msg_bytes)
        except (BadSignatureError, Exception):
            return False

    @staticmethod
    def _derive_key(password: str, salt: bytes) -> bytes:
        key = password.encode()
        for _ in range(5000):
            key = hashlib.sha256(key + salt).digest()
        return key

    @classmethod
    def save_encrypted_wallet(cls, filename, password, address, spend_secret_key, public_key=""):
        try:
            if not filename.endswith(".wallet"):
                filename += ".wallet"
            
            wallet_data = {
                "address": address, 
                "spend_secret_key": spend_secret_key,
                "public_key": public_key
            }
            raw_json = json.dumps(wallet_data).encode('utf-8')
            
            if FERNET_AVAILABLE:
                salt = secrets.token_bytes(16)
                key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
                key_b64 = base64.b64encode(key[:32])
                cipher = Fernet(key_b64)
                ciphertext = cipher.encrypt(raw_json)
                
                file_payload = {
                    "method": "fernet",
                    "salt": base64.b64encode(salt).decode('utf-8'),
                    "ciphertext": base64.b64encode(ciphertext).decode('utf-8')
                }
            else:
                salt = secrets.token_bytes(16)
                key = cls._derive_key(password, salt)
                cipher_stream = hashlib.sha256(key).digest()
                encrypted_bytes = bytearray()
                for i in range(len(raw_json)):
                    if i % 32 == 0 and i > 0:
                        cipher_stream = hashlib.sha256(cipher_stream + key).digest()
                    encrypted_bytes.append(raw_json[i] ^ cipher_stream[i % 32])
                file_payload = {
                    "method": "xor",
                    "salt": base64.b64encode(salt).decode('utf-8'),
                    "ciphertext": base64.b64encode(encrypted_bytes).decode('utf-8')
                }
                
            with open(filename, "w") as f:
                json.dump(file_payload, f)
            return {"status": "sucesso", "message": f"Arquivo {filename} salvo com seguranca!"}
        except Exception as e:
            return {"status": "erro", "message": str(e)}

    @classmethod
    def load_encrypted_wallet(cls, filename, password):
        try:
            if not filename.endswith(".wallet"):
                filename += ".wallet"
            if not os.path.exists(filename):
                return {"status": "erro", "message": "Arquivo nao encontrado."}
                
            with open(filename, "r") as f:
                file_payload = json.load(f)
                
            method = file_payload.get("method", "xor")
            salt = base64.b64decode(file_payload["salt"])
            ciphertext = base64.b64decode(file_payload["ciphertext"])
            
            if method == "fernet" and FERNET_AVAILABLE:
                key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
                key_b64 = base64.b64encode(key[:32])
                try:
                    cipher = Fernet(key_b64)
                    decrypted_data = json.loads(cipher.decrypt(ciphertext).decode('utf-8'))
                except InvalidToken:
                    return {"status": "erro", "message": "Senha incorreta."}
            else:
                key = cls._derive_key(password, salt)
                cipher_stream = hashlib.sha256(key).digest()
                decrypted_bytes = bytearray()
                for i in range(len(ciphertext)):
                    if i % 32 == 0 and i > 0:
                        cipher_stream = hashlib.sha256(cipher_stream + key).digest()
                    decrypted_bytes.append(ciphertext[i] ^ cipher_stream[i % 32])
                try:
                    decrypted_data = json.loads(decrypted_bytes.decode('utf-8'))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return {"status": "erro", "message": "Senha incorreta."}

            return {
                "status": "sucesso",
                "address": decrypted_data["address"],
                "spend_secret_key": decrypted_data["spend_secret_key"],
                "public_key": decrypted_data.get("public_key", "")
            }
        except Exception as e:
            return {"status": "erro", "message": f"Erro ao carregar carteira: {str(e)}"}
