"""
remote_node.py — Nó remoto (VPS headless)
============================================================
Roda 24/7 num VPS, aceita conexões P2P de outros nós.
Sem GUI. Sem mineração (a menos que você queira).
============================================================
"""
import sys
import time
import signal
import threading

from main import CriptoAPI, COIN_NAME, current_reward


class RemoteNode:
    def __init__(self, port: int, minerar: bool = False,
                 miner_address: str = None):
        self.port = port
        self.api = CriptoAPI(port)
        self.rodando = True
        self.minerar = minerar
        self.miner_address = miner_address

        signal.signal(signal.SIGINT, self._shutdown)
        try:
            signal.signal(signal.SIGTERM, self._shutdown)
        except Exception:
            pass

    def _shutdown(self, *_):
        print("\n🛑 Encerrando nó remoto…")
        self.rodando = False
        if self.api.is_mining:
            self.api.is_mining = False
            self.api.mining_stop_event.set()

    def start(self):
        print("=" * 60)
        print(f"🌐 {COIN_NAME} — Nó Remoto (VPS headless)")
        print("=" * 60)
        print(f"📡 Porta P2P: {self.port}")
        print(f"💾 DB: blockchain_node_{self.port}.db")
        print(f"🆔 Network ID: brunocoin-mainnet-v1")
        print(f"⛏️  Mineração: {'ATIVA' if self.minerar else 'inativa'}")
        if self.minerar and self.miner_address:
            print(f"🎯 Minerando para: {self.miner_address}")
        print("=" * 60)
        print("⏳ Aguardando conexões… (Ctrl+C para parar)")
        print()

        # ✅ Inicia mineração se pedido
        if self.minerar and self.miner_address:
            r = self.api.toggle_continuous_mining(self.miner_address)
            print(f"[MINING] {r.get('message', 'erro')}")

        try:
            while self.rodando:
                time.sleep(30)
                altura = len(self.api.db.get_raw_chain())
                peers = len(self.api.connected_peers)
                mempool = len(self.api.mempool)
                mining = "⛏️ ON" if self.api.is_mining else "⛏️ OFF"
                print(f"[STATUS] Altura: {altura} | Peers: {peers} | "
                      f"Mempool: {mempool} | {mining}")
        except KeyboardInterrupt:
            pass

        print("👋 Nó remoto encerrado")


if __name__ == "__main__":
    port = 6001
    minerar = False
    miner_address = None

    # Parse args
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--mine":
            minerar = True
        elif a == "--address" and i + 1 < len(args):
            miner_address = args[i + 1]
            i += 1
        elif a.isdigit():
            port = int(a)
        i += 1

    # Se quer minerar mas não passou endereço, usa GENESIS_ADDRESS
    if minerar and not miner_address:
        from main import GENESIS_ADDRESS
        miner_address = GENESIS_ADDRESS
        print(f"[WARN] Sem --address, minerando para {miner_address}")

    node = RemoteNode(port, minerar=minerar, miner_address=miner_address)
    node.start()
