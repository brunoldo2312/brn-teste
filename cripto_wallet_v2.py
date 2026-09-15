"""
cripto_wallet_v2.py
Gerenciador de carteira: geração de chaves, endereços e backups criptografados.
"""
import os
import json
import hashlib
import secrets
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64


class Wallet:
    def __init__(self, private_key=None, address=None):
        if private_key:
            self.private_key = private_key
            self.address = address or self._derive_address(private_key)
        else:
            self.private_key = self._generate_private_key()
            self.address = self._derive_address(self.private_key)

    @staticmethod
    def _generate_private_key():
        return secrets.token_hex(32)

    @staticmethod
    def _derive_address(private_key):
        # Endereço = "brn1" + primeiros 40 chars do SHA-256 da chave privada
        h = hashlib.sha256(private_key.encode()).hexdigest()
        return "brn1" + h[:40]

    def get_public_info(self):
        return {"address": self.address}

    def sign(self, message: str) -> str:
        """Assinatura simplificada (SHA-256). Em produção, use ECDSA."""
        return hashlib.sha256(f"{self.private_key}{message}".encode()).hexdigest()


def encrypt_wallet(wallet: Wallet, password: str, path: str):
    """Salva um backup .wallet criptografado com PBKDF2 + Fernet."""
    if len(password) < 12:
        raise ValueError("A senha deve ter no mínimo 12 caracteres.")
    salt = os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=600000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    f = Fernet(key)
    payload = json.dumps({
        "private_key": wallet.private_key,
        "address": wallet.address,
    }).encode()
    token = f.encrypt(payload)
    with open(path, "wb") as fp:
        fp.write(salt + token)
    return path


def decrypt_wallet(path: str, password: str) -> Wallet:
    """Lê um backup .wallet criptografado e retorna a Wallet."""
    with open(path, "rb") as fp:
        data = fp.read()
    salt, token = data[:16], data[16:]
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=600000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    f = Fernet(key)
    payload = json.loads(f.decrypt(token).decode())
    return Wallet(private_key=payload["private_key"], address=payload["address"])