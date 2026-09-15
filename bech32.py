"""Bech32 (BIP-0173) — endereços BRN no formato brn1..."""
CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

def _polymod(values):
    GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1ffffff) << 5) ^ v
        for i in range(5):
            chk ^= GEN[i] if ((b >> i) & 1) else 0
    return chk

def _hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]

def _create_checksum(hrp, data):
    values = _hrp_expand(hrp) + data
    polymod = _polymod(values + [0, 0, 0, 0, 0, 0]) ^ 1
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]

def _convertbits(data, frombits, tobits, pad=True):
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    for value in data:
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (tobits - bits)) & maxv)
    return ret

def encode(hrp: str, payload: bytes) -> str:
    data = _convertbits(list(payload), 8, 5)
    combined = data + _create_checksum(hrp, data)
    return hrp + "1" + "".join(CHARSET[d] for d in combined)

def decode(addr: str) -> tuple[str, bytes]:
    pos = addr.rfind("1")
    hrp, data = addr[:pos], addr[pos + 1:]
    decoded = [CHARSET.find(c) for c in data]
    if _polymod(_hrp_expand(hrp) + decoded) != 1:
        raise ValueError("checksum inválido")
    payload = _convertbits(decoded[:-6], 5, 8, False)
    return hrp, bytes(payload)

def address_from_pubkey(pubkey: bytes) -> str:
    from crypto import hash160
    return encode("brn", hash160(pubkey))

def validate_address(addr: str) -> bool:
    try:
        hrp, payload = decode(addr)
        return hrp == "brn" and len(payload) == 20
    except Exception:
        return False