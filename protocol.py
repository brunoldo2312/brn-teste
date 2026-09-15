"""Tipos de mensagem P2P e empacotamento."""
import struct
import orjson

PROTOCOL_VERSION = 2
MAX_MSG = 4 * 1024 * 1024  # 4 MB

def pack(msg: dict) -> bytes:
    payload = orjson.dumps(msg)
    return struct.pack(">I", len(payload)) + payload

async def read_msg(reader) -> dict | None:
    import asyncio
    try:
        header = await reader.readexactly(4)
    except asyncio.IncompleteReadError:
        return None
    (size,) = struct.unpack(">I", header)
    if size == 0 or size > MAX_MSG:
        return None
    try:
        payload = await reader.readexactly(size)
    except asyncio.IncompleteReadError:
        return None
    return orjson.loads(payload)

def write_msg(writer, msg: dict):
    writer.write(pack(msg))