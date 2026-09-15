"""Nó BRN headless — blockchain + P2P + carteira automatica + mineracao."""
import asyncio
import json
import os
import sys
import time
from blockchain import Blockchain
from p2p import PeerManager
from wallet import Wallet

WALLET_FILE = "wallet.brn"
UNIT = 10 ** 8


# ============================================================
# CARTEIRA
# ============================================================
def load_or_create_wallet(path: str = WALLET_FILE) -> Wallet:
    """Carrega a carteira de 'path' ou cria uma nova se nao existir."""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            w = Wallet(private_key_hex=data["private_key"])
            print(f"[WALLET] Carteira carregada de {path}")
            return w
        except Exception as e:
            backup = f"{path}.bak.{int(time.time())}"
            try:
                os.rename(path, backup)
                print(f"[WALLET] Arquivo corrompido movido para {backup}")
            except Exception:
                pass
            print(f"[WALLET] Criando nova carteira...")

    w = Wallet()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(w.to_dict(), f, indent=2)
        print(f"[WALLET] Nova carteira criada e salva em {path}")
        print(f"[WALLET] IMPORTANTE: faca backup do arquivo '{path}'!")
    except Exception as e:
        print(f"[WALLET] Erro ao salvar carteira: {e}")
    return w


def print_banner(wallet: Wallet, bc: Blockchain, port: int):
    saldo = bc.db.balance(wallet.address) / UNIT
    print()
    print("=" * 64)
    print("  BRN - BrunoCoin  |  no headless")
    print("=" * 64)
    print(f"  Porta P2P    : {port}")
    print(f"  Altura       : {bc.db.height()}")
    print(f"  Tip          : {bc.db.tip_hash()[:24]}...")
    print(f"  Endereco     : {wallet.address}")
    print(f"  Pubkey       : {wallet.pub_hex[:44]}...")
    print(f"  Saldo        : {saldo:.8f} BRN")
    print("=" * 64)
    print()


# ============================================================
# LOOPS AUXILIARES
# ============================================================
async def _status_loop(bc: Blockchain, wallet: Wallet):
    """Exibe status a cada 15 segundos quando a altura muda."""
    last_height = bc.db.height()
    while True:
        await asyncio.sleep(15)
        try:
            h = bc.db.height()
            if h != last_height:
                saldo = bc.db.balance(wallet.address) / UNIT
                print(f"[STATUS] Altura={h}  "
                      f"Saldo={saldo:.8f} BRN  "
                      f"tip={bc.db.tip_hash()[:16]}")
                last_height = h
        except Exception as e:
            print(f"[STATUS] erro: {e}")


async def _mine_loop(bc: Blockchain, wallet: Wallet, pm: PeerManager):
    """Mina blocos continuamente para o endereco da carteira."""
    while True:
        try:
            block = await asyncio.to_thread(bc.mine_block, wallet.address)
            if block:
                saldo = bc.db.balance(wallet.address) / UNIT
                print(f"[MINE] bloco #{block['height']} {block['hash'][:16]}  "
                      f"txs={len(block['transactions'])}  "
                      f"diff={block['difficulty']}  "
                      f"saldo={saldo:.8f} BRN")
                try:
                    await pm.broadcast({
                        "type": "inv_block",
                        "height": block["height"],
                        "hash": block["hash"],
                    })
                except Exception as e:
                    print(f"[MINE] falha ao propagar bloco: {e}")
        except Exception as e:
            print(f"[MINE] erro: {e}")
        await asyncio.sleep(2)


# ============================================================
# LOOP PRINCIPAL
# ============================================================
async def run(port: int, db_path: str,
              miner_address: str | None = None, mine: bool = False):
    # 1) Carteira: carrega ou cria automaticamente
    wallet = load_or_create_wallet()
    if not miner_address:
        miner_address = wallet.address

    # 2) Blockchain (usa o endereco da carteira no genesis, se o banco for novo)
    bc = Blockchain(db_path=db_path, genesis_address=miner_address)
    print_banner(wallet, bc, port)

    # 3) P2P
    pm = PeerManager(bc, port)
    await pm.start()

    # 4) Mineração automática
    if mine and miner_address:
        asyncio.create_task(_mine_loop(bc, wallet, pm))
        print(f"[MINE] Mineracao ativa para {miner_address}")

    # 5) Status periodico
    asyncio.create_task(_status_loop(bc, wallet))

    print(f"[BRN] no iniciado. Aguardando conexoes P2P...")
    print(f"[BRN] Pressione Ctrl+C para encerrar.")
    print()

    # 6) Loop infinito de baixo consumo
    while True:
        await asyncio.sleep(3600)


# ============================================================
# ENTRYPOINT
# ============================================================
def main():
    args = sys.argv[1:]

    # ----- Flags -----
    mine = True  # padrao novo: minerar automaticamente
    if "--no-mine" in args:
        mine = False
        args = [a for a in args if a != "--no-mine"]
    if "--mine" in args:
        mine = True
        args = [a for a in args if a != "--mine"]

    # ----- Posicionais: [port] [db_path] [miner_address] -----
    try:
        port = int(args[0]) if len(args) > 0 else 6001
    except ValueError:
        port = 6001

    db_path = args[1] if len(args) > 1 else f"blockchain_node_{port}.db"
    miner_address = args[2] if len(args) > 2 else None

    try:
        asyncio.run(run(port, db_path, miner_address, mine))
    except KeyboardInterrupt:
        print("\n[BRN] encerrado pelo usuario")


if __name__ == "__main__":
    main()
