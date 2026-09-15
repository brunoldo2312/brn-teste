"""P2P assíncrono com headers-first sync, seeds DNS e gossip."""
import asyncio
import socket
import time
import orjson
from protocol import PROTOCOL_VERSION, read_msg, write_msg, pack

MAX_PEERS = 16
SYNC_BATCH = 2000

DNS_SEEDS = ["seed1.brn.network", "seed2.brn.network"]
HARDCODED_SEEDS = [("127.0.0.1", 6001)]


class PeerManager:
    def __init__(self, blockchain, port: int):
        self.bc = blockchain
        self.port = port
        self.peers: dict[tuple[str, int], dict] = {}
        self.known: set[tuple[str, int]] = set(HARDCODED_SEEDS)

    # ---------- servidor ----------
    async def serve(self):
        server = await asyncio.start_server(self._handle, "0.0.0.0", self.port)
        print(f"[P2P] escutando em 0.0.0.0:{self.port}")
        async with server:
            await server.serve_forever()

    async def _handle(self, reader, writer):
        addr = writer.get_extra_info("peername")
        peer_key = (addr[0], addr[1])
        try:
            while True:
                msg = await read_msg(reader)
                if msg is None:
                    break
                reply = await self._dispatch(msg, peer_key, writer)
                if reply is not None:
                    write_msg(writer, reply)
                    await writer.drain()
        except (ConnectionResetError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _dispatch(self, msg: dict, peer, writer) -> dict | None:
        t = msg.get("type")
        if t == "ping":
            return {"type": "pong", "version": PROTOCOL_VERSION,
                    "height": self.bc.db.height(), "tip": self.bc.db.tip_hash()}
        if t == "get_headers":
            start = int(msg.get("start", 0))
            return {"type": "headers", "items": self.bc.db.headers(start, SYNC_BATCH)}
        if t == "get_block":
            h = int(msg.get("height", -1))
            b = self.bc.db.get_block(h)
            return {"type": "block", "block": b} if b else None
        if t == "get_addr":
            return {"type": "addr", "peers": [[h, p] for (h, p) in list(self.known)[:50]]}
        if t == "addr":
            for entry in msg.get("peers", []):
                try:
                    self.known.add((entry[0], int(entry[1])))
                except Exception:
                    pass
            return None
        if t == "inv_tx":
            txid_ = msg["txid"]
            if self.bc.db.has_mempool(txid_):
                return None
            return {"type": "get_tx", "txid": txid_}
        if t == "get_tx":
            tx = self.bc.db.get_mempool_tx(msg["txid"])
            return {"type": "tx", "tx": tx} if tx else None
        if t == "tx":
            tx = msg["tx"]
            ok, _ = self.bc.submit_tx(tx)
            if ok:
                asyncio.create_task(self.broadcast({"type": "inv_tx", "txid": tx["txid"]}))
            return None
        if t == "inv_block":
            return {"type": "get_block", "height": msg["height"]}
        if t == "block":
            block = msg["block"]
            ok, _ = self.bc.accept_block(block)
            if ok:
                asyncio.create_task(self.broadcast({"type": "inv_block",
                                                    "height": block["height"],
                                                    "hash": block["hash"]}))
            return None
        return {"type": "error", "message": "desconhecido"}

    # ---------- cliente ----------
    async def connect(self, host: str, port: int):
        try:
            reader, writer = await asyncio.open_connection(host, port)
        except Exception as e:
            print(f"[P2P] falha ao conectar {host}:{port} — {e}")
            return
        self.peers[(host, port)] = {"reader": reader, "writer": writer, "last": time.time()}
        write_msg(writer, {"type": "ping", "version": PROTOCOL_VERSION})
        await writer.drain()
        try:
            pong = await asyncio.wait_for(read_msg(reader), timeout=5)
        except asyncio.TimeoutError:
            pong = None
        if pong and pong.get("type") == "pong":
            remote_h = pong.get("height", 0)
            local_h = self.bc.db.height()
            print(f"[P2P] conectado {host}:{port} (remoto h={remote_h}, local h={local_h})")
            if remote_h > local_h:
                await self.sync_from(host, port)
        else:
            print(f"[P2P] handshake falhou com {host}:{port}")

    async def sync_from(self, host: str, port: int):
        """Headers-first sync: pega headers, encontra fork, puxa blocos."""
        try:
            reader, writer = await asyncio.open_connection(host, port)
        except Exception:
            return
        try:
            start = 0
            all_headers: list[dict] = []
            while True:
                write_msg(writer, {"type": "get_headers", "start": start})
                await writer.drain()
                resp = await asyncio.wait_for(read_msg(reader), timeout=15)
                if not resp or resp.get("type") != "headers":
                    break
                items = resp.get("items", [])
                if not items:
                    break
                all_headers.extend(items)
                start = items[-1]["height"] + 1
                if len(items) < SYNC_BATCH:
                    break

            print(f"[SYNC] {len(all_headers)} headers recebidos de {host}:{port}")

            # encontra ponto de divergência
            fork_height = 0
            for h in all_headers:
                local = self.bc.db.get_block(h["height"])
                if local and local["hash"] == h["hash"]:
                    fork_height = h["height"]
                else:
                    break

            # baixa blocos a partir do fork
            for h in all_headers:
                if h["height"] <= fork_height:
                    continue
                write_msg(writer, {"type": "get_block", "height": h["height"]})
                await writer.drain()
                resp = await asyncio.wait_for(read_msg(reader), timeout=20)
                if not resp or resp.get("type") != "block":
                    break
                block = resp["block"]
                ok, msg = self.bc.accept_block(block)
                if not ok:
                    print(f"[SYNC] bloco {h['height']} rejeitado: {msg}")
                    break
            print(f"[SYNC] concluído até altura {self.bc.db.height()}")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    # ---------- gossip ----------
    async def broadcast(self, msg: dict):
        frame = pack(msg)
        for key, info in list(self.peers.items()):
            try:
                info["writer"].write(frame)
                await info["writer"].drain()
            except Exception:
                self.peers.pop(key, None)

    # ---------- discovery ----------
    async def resolve_seeds(self):
        for host, port in HARDCODED_SEEDS:
            self.known.add((host, port))
        for seed in DNS_SEEDS:
            try:
                ip = await asyncio.get_event_loop().getaddrinfo(seed, None)
                for entry in ip:
                    self.known.add((entry[4][0], self.port))
            except Exception:
                pass
        # pede addr aos peers atuais
        for key in list(self.peers.keys()):
            try:
                info = self.peers[key]
                write_msg(info["writer"], {"type": "get_addr"})
                await info["writer"].drain()
            except Exception:
                pass

    async def maintenance_loop(self):
        while True:
            await asyncio.sleep(30)
            # reconecta
            if len(self.peers) < MAX_PEERS:
                for host, port in list(self.known):
                    if (host, port) in self.peers:
                        continue
                    if host in ("127.0.0.1",) and port == self.port:
                        continue
                    asyncio.create_task(self.connect(host, port))
                    if len(self.peers) >= MAX_PEERS:
                        break
            # poda peers mortos
            for key, info in list(self.peers.items()):
                try:
                    info["writer"].write(pack({"type": "ping", "version": PROTOCOL_VERSION}))
                    await info["writer"].drain()
                except Exception:
                    self.peers.pop(key, None)

    async def start(self):
        await self.resolve_seeds()
        asyncio.create_task(self.serve())
        asyncio.create_task(self.maintenance_loop())
        # conexões iniciais
        for host, port in list(self.known)[:5]:
            if host in ("127.0.0.1", "0.0.0.0") and port == self.port:
                continue
            asyncio.create_task(self.connect(host, port))