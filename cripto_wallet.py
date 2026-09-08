import hashlib
import json
import secrets
import base64
import os
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.fernet import Fernet
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend


class Wallet:
    def __init__(self):
        self.private_key = None
        self.public_key = None
        self.address = None
        self._generate_keypair()

    def _generate_keypair(self):
        """Gera par de chaves ECDSA (curva SECP256k1)."""
        private = ec.generate_private_key(ec.SECP256K1(), default_backend())
        self.private_key = private
        public = private.public_key()
        self.public_key = public
        # Endereço = hash SHA256 da chave pública (hex)
        pub_bytes = public.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint
        )
        self.address = hashlib.sha256(pub_bytes).hexdigest()[:40]

    def sign_transaction(self, tx_dict):
        """Assina uma transação com a chave privada."""
        tx_string = json.dumps(tx_dict, sort_keys=True).encode()
        signature = self.private_key.sign(tx_string, ec.ECDSA(hashes.SHA256()))
        return base64.b64encode(signature).decode()

    def verify_transaction(self, tx_dict):
        """Verifica a assinatura de uma transação."""
        if "signature" not in tx_dict:
            return False
        signature = base64.b64decode(tx_dict["signature"])
        tx_copy = {k: v for k, v in tx_dict.items() if k != "signature"}
        tx_bytes = json.dumps(tx_copy, sort_keys=True).encode()
        pub_key_pem = tx_dict.get("public_key")
        if not pub_key_pem:
            return False
        try:
            public_key = serialization.load_pem_public_key(pub_key_pem.encode(), backend=default_backend())
            public_key.verify(signature, tx_bytes, ec.ECDSA(hashes.SHA256()))
            return True
        except InvalidSignature:
            return False
        except Exception:
            return False

    def get_public_key_pem(self):
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()

    def encrypt_wallet(self, password):
        """Criptografa a chave privada com Fernet (PBKDF2)."""
        salt = os.urandom(16)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        f = Fernet(key)
        data = {
            "private_key": self.private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            ).decode(),
            "address": self.address
        }
        encrypted = f.encrypt(json.dumps(data).encode())
        return {"salt": base64.b64encode(salt).decode(), "data": base64.b64encode(encrypted).decode()}

    def decrypt_wallet(self, encrypted_data, password):
        """Descriptografa e restaura a carteira."""
        salt = base64.b64decode(encrypted_data["salt"])
        data = base64.b64decode(encrypted_data["data"])
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        f = Fernet(key)
        decrypted = f.decrypt(data)
        wallet_data = json.loads(decrypted.decode())
        self.private_key = serialization.load_pem_private_key(
            wallet_data["private_key"].encode(),
            password=None,
            backend=default_backend()
        )
        self.public_key = self.private_key.public_key()
        self.address = wallet_data["address"]