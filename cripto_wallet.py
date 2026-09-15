
import hashlib
import json
import secrets
import base64
import os
from pathlib import Path
from ecdsa import SigningKey, VerifyingKey, SECP256k1, BadSignatureError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from argon2.low_level import hash_secret_raw, Type


class WalletManager:
    ARGON2_TIME_COST = 3
    ARGON2_MEMORY_COST = 65536
    ARGON2_PARALLELISM = 4
    ARGON2_HASH_LEN = 32
    ARGON2_SALT_LEN = 16
    GCM_NONCE_LEN = 12
    WALLET_EXT = ".wallet"
    MIN_PASSWORD_LEN = 12

    @staticmethod
    def address_from_public_key(public_key_hex: str) -> str:
        try:
            public_key = bytes.fromhex(public_key_hex)
        except ValueError as e:
            raise ValueError(f"Chave publica invalida: {e}") from e
        try:
            VerifyingKey.from_string(public_key, curve=SECP256k1)
        except Exception as e:
            raise ValueError(f"Chave publica invalida SECP256k1: {e}") from e
        digest = hashlib.sha256(public_key).hexdigest()
        return f"brn1{digest[:40]}"

    @staticmethod
    def validate_address(address: str) -> bool:
        if not isinstance(address, str): return False
        if not address.startswith("brn1"): return False
        if len(address) != 44: return False
        try:
            int(address[4:], 16); return True
        except ValueError:
            return False

    @staticmethod
    def generate_keypair() -> dict:
        sk = SigningKey.generate(curve=SECP256k1)
        vk = sk.verifying_key
        sk_hex = sk.to_string().hex()
        vk_hex = vk.to_string().hex()
        return {
            "address": WalletManager.address_from_public_key(vk_hex),
            "spend_secret_key": sk_hex,
            "public_key": vk_hex,
        }

    @staticmethod
    def sign_transaction(private_key_hex: str, message_dict: dict) -> str:
        if not isinstance(private_key_hex, str) or len(private_key_hex) < 64:
            raise ValueError("Chave privada invalida.")
        sk_bytes = bytes.fromhex(private_key_hex)
        sk = SigningKey.from_string(sk_bytes, curve=SECP256k1)
        msg = json.dumps(message_dict, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
        return sk.sign_deterministic(msg, hashfunc=hashlib.sha256).hex()

    @staticmethod
    def verify_signature(public_key_hex: str, message_dict: dict,
                         signature_hex: str) -> bool:
        try:
            vk = VerifyingKey.from_string(
                bytes.fromhex(public_key_hex), curve=SECP256k1)
            msg = json.dumps(message_dict, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")
            return vk.verify(bytes.fromhex(signature_hex), msg,
                             hashfunc=hashlib.sha256)
        except (BadSignatureError, ValueError, TypeError, AttributeError):
            return False

    @staticmethod
    def _wallet_dir() -> Path:
        d = Path.cwd() / "wallets"
        d.mkdir(mode=0o700, exist_ok=True)
        return d

    @classmethod
    def _wallet_path(cls, filename: str) -> Path:
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("Nome de arquivo invalido.")
        safe = Path(filename).name
        if safe in {"", ".", ".."}:
            raise ValueError("Nome de arquivo invalido.")
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.")
        if not all(c in allowed for c in safe):
            raise ValueError("Caracteres invalidos no nome do arquivo.")
        if not safe.endswith(cls.WALLET_EXT):
            safe += cls.WALLET_EXT
        return cls._wallet_dir() / safe

    @classmethod
    def save_encrypted_wallet(cls, filename, password, address,
                              spend_secret_key, public_key=""):
        try:
            if not isinstance(password, str) or len(password) < cls.MIN_PASSWORD_LEN:
                return {"status": "erro",
                        "message": f"Senha precisa ter >= {cls.MIN_PASSWORD_LEN} caracteres."}
            if not cls.validate_address(address):
                return {"status": "erro", "message": "Endereco invalido."}
            if not spend_secret_key:
                return {"status": "erro", "message": "Chave privada ausente."}
            path = cls._wallet_path(filename)
            data = {"address": address,
                    "spend_secret_key": spend_secret_key,
                    "public_key": public_key}
            raw = json.dumps(data).encode("utf-8")
            salt = secrets.token_bytes(cls.ARGON2_SALT_LEN)
            key = hash_secret_raw(secret=password.encode(), salt=salt,
                                  time_cost=cls.ARGON2_TIME_COST,
                                  memory_cost=cls.ARGON2_MEMORY_COST,
                                  parallelism=cls.ARGON2_PARALLELISM,
                                  hash_len=cls.ARGON2_HASH_LEN,
                                  type=Type.ID)
            nonce = secrets.token_bytes(cls.GCM_NONCE_LEN)
            ciphertext = AESGCM(key).encrypt(nonce, raw, None)
            payload = {
                "version": 2,
                "method": "aes-256-gcm-argon2id",
                "argon2": {"time_cost": cls.ARGON2_TIME_COST,
                           "memory_cost": cls.ARGON2_MEMORY_COST,
                           "parallelism": cls.ARGON2_PARALLELISM,
                           "hash_len": cls.ARGON2_HASH_LEN},
                "salt": base64.b64encode(salt).decode(),
                "nonce": base64.b64encode(nonce).decode(),
                "ciphertext": base64.b64encode(ciphertext).decode(),
            }
            with open(path, "w") as f:
                json.dump(payload, f, indent=2)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            return {"status": "sucesso",
                    "message": f"Carteira salva em {path}",
                    "path": str(path)}
        except Exception as e:
            return {"status": "erro", "message": str(e)}

    @classmethod
    def load_encrypted_wallet(cls, filename, password):
        try:
            path = cls._wallet_path(filename)
            if not path.exists():
                return {"status": "erro", "message": "Arquivo nao encontrado."}
            with open(path) as f:
                payload = json.load(f)
            if payload.get("method") != "aes-256-gcm-argon2id":
                return {"status": "erro", "message": "Formato invalido."}
            salt = base64.b64decode(payload["salt"])
            nonce = base64.b64decode(payload["nonce"])
            ciphertext = base64.b64decode(payload["ciphertext"])
            p = payload["argon2"]
            key = hash_secret_raw(secret=password.encode(), salt=salt,
                                  time_cost=p["time_cost"],
                                  memory_cost=p["memory_cost"],
                                  parallelism=p["parallelism"],
                                  hash_len=p["hash_len"],
                                  type=Type.ID)
            try:
                decrypted = json.loads(
                    AESGCM(key).decrypt(nonce, ciphertext, None).decode())
            except Exception:
                return {"status": "erro", "message": "Senha incorreta."}
            return {"status": "sucesso",
                    "address": decrypted["address"],
                    "spend_secret_key": decrypted["spend_secret_key"],
                    "public_key": decrypted.get("public_key", "")}
        except Exception as e:
            return {"status": "erro", "message": str(e)}

    @staticmethod
    def list_wallets():
        d = Path.cwd() / "wallets"
        if not d.exists(): return []
        return sorted(p.name for p in d.iterdir()
                      if p.is_file() and p.suffix == WalletManager.WALLET_EXT)
