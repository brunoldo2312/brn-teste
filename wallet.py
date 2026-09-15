"""Carteira BRN com assinatura Schnorr (padrão) e ECDSA (fallback)."""
import json
import base64
import os
import secrets
from crypto import (
    sha256, pubkey_from_priv, sign_schnorr, verify_schnorr,
    sign_ecdsa, verify_ecdsa, generate_private_key,
)
from bech32 import address_from_pubkey

SIG_MODE = "schnorr"  # "schnorr" ou "ecdsa"

class Wallet:
    def __init__(self, private_key_hex: str | None = None):
        if private_key_hex:
            self.priv = bytes.fromhex(private_key_hex)
        else:
            self.priv = generate_private_key()
        self.pub = pubkey_from_priv(self.priv)
        self.address = address_from_pubkey(self.pub)

    @property
    def priv_hex(self) -> str:
        return self.priv.hex()

    @property
    def pub_hex(self) -> str:
        return self.pub.hex()

    def sign(self, msg_hash: bytes) -> str:
        if SIG_MODE == "schnorr":
            return sign_schnorr(self.priv, msg_hash).hex()
        return sign_ecdsa(self.priv, msg_hash).hex()

    @staticmethod
    def verify(msg_hash: bytes, sig_hex: str, pub_hex: str) -> bool:
        try:
            sig = bytes.fromhex(sig_hex)
            pub = bytes.fromhex(pub_hex)
            if SIG_MODE == "schnorr":
                return verify_schnorr(pub, sig, msg_hash)
            return verify_ecdsa(pub, sig, msg_hash)
        except Exception:
            return False

    def to_dict(self) -> dict:
        return {"private_key": self.priv_hex, "address": self.address, "pubkey": self.pub_hex}

    @classmethod
    def from_dict(cls, d: dict) -> "Wallet":
        w = cls(private_key_hex=d["private_key"])
        return w

    def export_encrypted(self, password: str) -> str:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        salt = os.urandom(16)
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600_000)
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        token = Fernet(key).encrypt(json.dumps(self.to_dict()).encode())
        return base64.b64encode(salt + token).decode()

    @classmethod
    def import_encrypted(cls, blob_b64: str, password: str) -> "Wallet":
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        blob = base64.b64decode(blob_b64)
        salt, token = blob[:16], blob[16:]
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600_000)
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        data = json.loads(Fernet(key).decrypt(token).decode())
        return cls.from_dict(data)