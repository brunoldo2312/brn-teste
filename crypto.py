"""Camada criptográfica BRN — secp256k1 (coincurve), ECDSA + Schnorr."""
import hashlib
from coincurve import PrivateKey, PublicKey

def sha256(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()

def double_sha256(b: bytes) -> bytes:
    return sha256(sha256(b))

def _ripemd160(b: bytes) -> bytes:
    try:
        return hashlib.new("ripemd160", b).digest()
    except ValueError:
        return sha256(b)[:20]

def hash160(b: bytes) -> bytes:
    return _ripemd160(sha256(b))

def generate_private_key() -> bytes:
    return PrivateKey().secret

def pubkey_from_priv(priv_bytes: bytes) -> bytes:
    return PrivateKey(priv_bytes).public_key.format(compressed=True)

def sign_ecdsa(priv_bytes: bytes, msg_hash: bytes) -> bytes:
    return PrivateKey(priv_bytes).sign(msg_hash, hasher=None)

def verify_ecdsa(pubkey: bytes, sig: bytes, msg_hash: bytes) -> bool:
    try:
        return PublicKey(pubkey).verify(sig, msg_hash, hasher=None)
    except Exception:
        return False

def sign_schnorr(priv_bytes: bytes, msg_hash: bytes) -> bytes:
    return PrivateKey(priv_bytes).sign_schnorr(msg_hash)

def verify_schnorr(pubkey: bytes, sig: bytes, msg_hash: bytes) -> bool:
    try:
        return PublicKey(pubkey).verify_schnorr(sig, msg_hash)
    except Exception:
        return False