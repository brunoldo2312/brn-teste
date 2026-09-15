"""Carteira HD (BIP32) — derivação m/44'/0'/0'/0/i."""
import hmac
import secrets
from hashlib import sha512
from coincurve import PrivateKey

HARDENED = 0x80000000

class HDWallet:
    def __init__(self, seed_hex: str | None = None):
        if seed_hex is None:
            seed_hex = secrets.token_hex(32)
        self.seed = bytes.fromhex(seed_hex)
        self.master_key = self._master(self.seed)

    @staticmethod
    def _master(seed: bytes) -> bytes:
        return hmac.new(b"BRN seed", seed, sha512).digest()[:32]

    def _ckd_priv(self, key: bytes, index: int, hardened: bool) -> bytes:
        if hardened:
            data = b"\x00" + key + index.to_bytes(4, "big")
        else:
            pub = PrivateKey(key).public_key.format(compressed=True)
            data = pub + index.to_bytes(4, "big")
        I = hmac.new(key, data, sha512).digest()
        il = int.from_bytes(I[:32], "big")
        kr = int.from_bytes(key, "big")
        return ((il + kr) % 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141).to_bytes(32, "big")

    def derive_path(self, path: str) -> bytes:
        """path: m/44'/0'/0'/0/0 → retorna private key de 32 bytes."""
        if path == "m":
            return self.master_key
        key = self.master_key
        for seg in path.split("/")[1:]:
            hardened = seg.endswith("'")
            idx = int(seg.rstrip("'"))
            if hardened:
                idx |= HARDENED
            key = self._ckd_priv(key, idx, hardened)
        return key

    def derive_account(self, account: int = 0, change: int = 0, index: int = 0) -> bytes:
        path = f"m/44'/0'/{account}'/{change}/{index}"
        return self.derive_path(path)