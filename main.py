"""Inicializador do BRN — GUI pywebview + blockchain + mineração + P2P + verificação."""
import argparse
import asyncio
import json
import os
import socket
import sys
import threading
import time

try:
    import webview
except ImportError:
    print("[ERRO] pywebview não instalado. Execute: pip install pywebview")
    sys.exit(1)

from blockchain import (
    Blockchain, UNIT, DECIMALS,
    txid as calc_txid, signing_hash,
)
from wallet import Wallet


ARQUIVO_CARTEIRA = "wallet_gui.brn"
PORTA_P2P_PADRAO = 6001


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================
def carregar_ou_criar_carteira(caminho: str = ARQUIVO_CARTEIRA) -> Wallet:
    """Carrega a carteira do arquivo ou cria uma nova se não existir."""
    if os.path.exists(caminho):
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                dados = json.load(f)
            return Wallet(private_key_hex=dados["private_key"])
        except Exception:
            backup = f"{caminho}.bak.{int(time.time())}"
            try:
                os.rename(caminho, backup)
            except Exception:
                pass
    w = Wallet()
    try:
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump({"private_key": w.priv_hex, "address": w.address},
                      f, indent=2)
    except Exception:
        pass
    return w


def obter_ips_lan() -> list[str]:
    """Retorna a lista de IPs da máquina na rede local (sem loopback)."""
    ips: list[str] = []

    # 1) Descobre o IP "de saída" via socket UDP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            ips.append(ip)
    except Exception:
        pass

    # 2) Varre as interfaces pelo hostname
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass

    return ips


# ============================================================
# API EXPOSTA AO PYWEBVIEW
# ============================================================
class BrnApi:
    """Todas as funções chamadas pelo index.html via pywebview.api.*"""

    def __init__(self, bc: Blockchain, wallet: Wallet, porta: int):
        self.bc = bc
        self.wallet = wallet
        self.porta = porta

        # P2P
        self.pm = None
        self._p2p_loop: asyncio.AbstractEventLoop | None = None
        self._p2p_thread: threading.Thread | None = None

        # Mineração
        self.minerando = False
        self.mineracao_thread: threading.Thread | None = None
        self.endereco_minerador: str | None = None
        self.trava = threading.Lock()

    # ==========================================================
    # P2P (opcional — iniciado no main())
    # ==========================================================
    def iniciar_p2p(self):
        try:
            from p2p import PeerManager
        except Exception as e:
            print(f"[P2P] indisponível: {e}")
            return
        try:
            self.pm = PeerManager(self.bc, self.porta)
            self._p2p_loop = asyncio.new_event_loop()

            def _rodar():
                asyncio.set_event_loop(self._p2p_loop)
                try:
                    self._p2p_loop.run_until_complete(self.pm.start())
                    self._p2p_loop.run_forever()
                except Exception as e:
                    print(f"[P2P] erro: {e}")

            self._p2p_thread = threading.Thread(target=_rodar, daemon=True)
            self._p2p_thread.start()
            print(f"[P2P] iniciado na porta {self.porta}")
        except Exception as e:
            print(f"[P2P] falha ao iniciar: {e}")

    # ==========================================================
    # CARTEIRA
    # ==========================================================
    def gerar_carteira(self) -> dict:
        """Gera uma nova carteira e a salva no arquivo local."""
        try:
            w = Wallet()
            self.wallet = w
            try:
                with open(ARQUIVO_CARTEIRA, "w", encoding="utf-8") as f:
                    json.dump({"private_key": w.priv_hex, "address": w.address},
                              f, indent=2)
            except Exception:
                pass
            return {
                "status": "ok",
                "address": w.address,
                "public_key": w.pub_hex,
                "spend_secret_key": w.priv_hex,
                "private_key": w.priv_hex,
            }
        except Exception as e:
            return {"status": "erro", "message": str(e)}

    # Alias para compatibilidade com o index.html antigo
    def generate_wallet(self):
        return self.gerar_carteira()

    def obter_endereco_carteira(self) -> str:
        return self.wallet.address if self.wallet else ""

    def salvar_carteira_criptografada(self, nome_arquivo: str, senha: str,
                                       endereco: str, chave_priv: str,
                                       chave_pub: str) -> dict:
        """Salva a carteira em um arquivo criptografado com senha."""
        try:
            if not chave_priv:
                return {"status": "erro", "message": "Chave privada ausente."}
            if not senha or len(senha) < 8:
                return {"status": "erro",
                        "message": "A senha deve ter ao menos 8 caracteres."}
            w = Wallet(private_key_hex=chave_priv)
            blob = w.export_encrypted(senha)
            with open(nome_arquivo, "w", encoding="utf-8") as f:
                f.write(blob)
            return {"status": "ok",
                    "message": f"Carteira salva em {nome_arquivo}"}
        except Exception as e:
            return {"status": "erro", "message": f"Falha: {e}"}

    # Alias em inglês (o index.html usa save_encrypted_wallet)
    def save_encrypted_wallet(self, *args, **kwargs):
        return self.salvar_carteira_criptografada(*args, **kwargs)

    def carregar_carteira_criptografada(self, nome_arquivo: str,
                                         senha: str) -> dict:
        """Lê um arquivo de carteira criptografado e restaura a carteira."""
        try:
            with open(nome_arquivo, "r", encoding="utf-8") as f:
                blob = f.read().strip()
            w = Wallet.import_encrypted(blob, senha)
            self.wallet = w
            try:
                with open(ARQUIVO_CARTEIRA, "w", encoding="utf-8") as f:
                    json.dump({"private_key": w.priv_hex, "address": w.address},
                              f, indent=2)
            except Exception:
                pass
            return {
                "status": "ok",
                "address": w.address,
                "public_key": w.pub_hex,
                "spend_secret_key": w.priv_hex,
                "private_key": w.priv_hex,
            }
        except Exception as e:
            return {"status": "erro", "message": f"Falha ao carregar: {e}"}

    # Alias em inglês
    def load_encrypted_wallet(self, *args, **kwargs):
        return self.carregar_carteira_criptografada(*args, **kwargs)

    # ==========================================================
    # SALDO
    # ==========================================================
    def obter_saldo(self, endereco: str) -> dict:
        """Retorna o saldo confirmado, pendente de saída e disponível."""
        try:
            saldo = self.bc.db.balance(endereco) / UNIT
            pendente_saida = self._pendente_saida(endereco) / UNIT
            pendente_entrada = self._pendente_entrada(endereco) / UNIT
            disponivel = saldo - pendente_saida
            return {
                "status": "ok",
                "balance": saldo,
                "pending_out": pendente_saida,
                "pending_in": pendente_entrada,
                "available": disponivel,
            }
        except Exception as e:
            return {"status": "erro", "message": str(e)}

    # Alias em inglês
    def get_balance(self, endereco: str):
        return self.obter_saldo(endereco)

    def _pendente_saida(self, endereco: str) -> int:
        """Soma das saídas para terceiros em txs da mempool que gastam UTXO nosso."""
        total = 0
        for tx in self.bc.db.all_mempool(limit=10000):
            utxo_nosso = False
            for inp in tx.get("inputs", []):
                u = self.bc.db.get_utxo(inp["txid"], inp["vout"])
                if u and u["address"] == endereco:
                    utxo_nosso = True
                    break
            if utxo_nosso:
                for o in tx["outputs"]:
                    if o["address"] != endereco:
                        total += o["amount"]
        return total

    def _pendente_entrada(self, endereco: str) -> int:
        """Soma das saídas para nós em txs da mempool que NÃO são troco nosso."""
        total = 0
        for tx in self.bc.db.all_mempool(limit=10000):
            utxo_nosso = False
            for inp in tx.get("inputs", []):
                u = self.bc.db.get_utxo(inp["txid"], inp["vout"])
                if u and u["address"] == endereco:
                    utxo_nosso = True
                    break
            if not utxo_nosso:
                for o in tx["outputs"]:
                    if o["address"] == endereco:
                        total += o["amount"]
        return total

    # ==========================================================
    # ENVIO DE FUNDOS
    # ==========================================================
    def enviar_fundos(self, remetente: str, destino: str, valor: float,
                      chave_priv: str, chave_pub: str) -> dict:
        """Monta, assina e envia uma transação para a mempool."""
        try:
            if not destino or valor <= 0:
                return {"status": "erro",
                        "message": "Destinatário e valor obrigatórios."}
            if destino == remetente:
                return {"status": "erro",
                        "message": "Origem e destino iguais."}

            w = Wallet(private_key_hex=chave_priv)
            if w.address != remetente:
                return {"status": "erro",
                        "message": "Chave privada não corresponde ao endereço."}

            valor_em_units = int(round(valor * UNIT))
            utxos = self.bc.db.utxos_for(remetente)
            if not utxos:
                return {"status": "erro", "message": "Sem UTXOs disponíveis."}

            # Seleciona UTXOs (do maior para o menor) até cobrir o valor
            total = 0
            escolhidos = []
            for u in sorted(utxos, key=lambda x: -x["amount"]):
                escolhidos.append(u)
                total += u["amount"]
                if total >= valor_em_units:
                    break
            if total < valor_em_units:
                return {"status": "erro",
                        "message": f"Saldo insuficiente "
                                   f"({total/UNIT:.8f} < {valor:.8f})."}

            # Saídas: destinatário + troco (se houver)
            saidas = [{"address": destino, "amount": valor_em_units, "pubkey": ""}]
            troco = total - valor_em_units
            if troco > 0:
                saidas.append({"address": remetente, "amount": troco,
                                "pubkey": w.pub_hex})

            entradas = [{"txid": u["txid"], "vout": u["vout"],
                         "pubkey": w.pub_hex, "signature": ""}
                        for u in escolhidos]

            tx = {
                "txid": "",
                "inputs": entradas,
                "outputs": saidas,
                "timestamp": int(time.time()),
                "locktime": 0,
            }
            tx["txid"] = calc_txid(tx)

            # Assina cada entrada com a chave privada
            msg_hash = signing_hash(tx)
            for inp in tx["inputs"]:
                inp["signature"] = w.sign(msg_hash)
            tx["txid"] = calc_txid(tx)

            ok, msg = self.bc.submit_tx(tx)
            if not ok:
                return {"status": "erro", "message": msg}

            # Propaga pela rede P2P (best-effort)
            if self.pm and self._p2p_loop:
                try:
                    asyncio.run_coroutine_threadsafe(
                        self.pm.broadcast({"type": "inv_tx", "txid": tx["txid"]}),
                        self._p2p_loop,
                    )
                except Exception:
                    pass

            return {"status": "ok",
                    "message": f"Transação enviada! txid={tx['txid'][:16]}…",
                    "txid": tx["txid"]}
        except Exception as e:
            return {"status": "erro", "message": f"Falha: {e}"}

    # Alias em inglês
    def send_funds(self, *args, **kwargs):
        return self.enviar_fundos(*args, **kwargs)

    # ==========================================================
    # HISTÓRICO / EXTRATO
    # ==========================================================
    def obter_historico(self, endereco: str) -> dict:
        """Retorna o extrato completo (confirmado + mempool) da carteira."""
        try:
            historico = []

            # Percorre toda a cadeia confirmada
            for h in range(self.bc.db.height() + 1):
                bloco = self.bc.db.get_block(h)
                if not bloco:
                    continue
                for tx in bloco["transactions"]:
                    entrada = self._classificar_tx(tx, endereco)
                    if entrada:
                        entrada["block_index"] = h
                        entrada["status"] = "confirmada"
                        historico.append(entrada)

            # Percorre a mempool
            for tx in self.bc.db.all_mempool(limit=10000):
                entrada = self._classificar_tx(tx, endereco)
                if entrada:
                    entrada["block_index"] = None
                    entrada["status"] = "pendente"
                    historico.append(entrada)

            historico.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
            return {"status": "ok", "history": historico}
        except Exception as e:
            return {"status": "erro", "message": str(e)}

    # Alias em inglês
    def get_transaction_history(self, endereco: str):
        return self.obter_historico(endereco)

    def _classificar_tx(self, tx: dict, endereco: str):
        """Classifica uma transação sob o ponto de vista de um endereço."""
        is_coinbase = tx["inputs"] and tx["inputs"][0]["txid"] == "0" * 64

        recebido = sum(o["amount"] for o in tx["outputs"]
                       if o["address"] == endereco)
        enviado_a_terceiros = sum(o["amount"] for o in tx["outputs"]
                                   if o["address"] != endereco)

        sou_remetente = False
        for inp in tx["inputs"]:
            u = self.bc.db.get_utxo(inp["txid"], inp["vout"])
            if u and u["address"] == endereco:
                sou_remetente = True
                break

        ts = tx.get("timestamp", 0)

        # Recompensa de mineração
        if is_coinbase and recebido > 0:
            return {"type": "Recompensa", "direction": "entrada",
                    "amount": recebido / UNIT, "counterparty": "coinbase",
                    "timestamp": ts}

        # Envio (ou troco)
        if sou_remetente:
            if enviado_a_terceiros > 0:
                destino = next((o["address"] for o in tx["outputs"]
                                if o["address"] != endereco), "?")
                return {"type": "Envio", "direction": "saida",
                        "amount": enviado_a_terceiros / UNIT,
                        "counterparty": destino, "timestamp": ts}
            else:
                return {"type": "Troco", "direction": "entrada",
                        "amount": recebido / UNIT,
                        "counterparty": endereco, "timestamp": ts}

        # Recebimento
        if recebido > 0:
            contraparte = "?"
            for inp in tx["inputs"]:
                u = self.bc.db.get_utxo(inp["txid"], inp["vout"])
                if u:
                    contraparte = u["address"]
                    break
            return {"type": "Recebimento", "direction": "entrada",
                    "amount": recebido / UNIT, "counterparty": contraparte,
                    "timestamp": ts}

        return None

    # ==========================================================
    # MEMPOOL
    # ==========================================================
    def obter_mempool(self) -> dict:
        """Retorna todas as transações pendentes na mempool."""
        try:
            txs = self.bc.db.all_mempool(limit=10000)
            saida = []
            for tx in txs:
                is_coinbase = tx["inputs"] and tx["inputs"][0]["txid"] == "0" * 64
                if is_coinbase:
                    continue
                remetente = "?"
                for inp in tx["inputs"]:
                    u = self.bc.db.get_utxo(inp["txid"], inp["vout"])
                    if u:
                        remetente = u["address"]
                        break
                destinatario = tx["outputs"][0]["address"] if tx["outputs"] else "?"
                valor = sum(o["amount"] for o in tx["outputs"]) / UNIT
                saida.append({
                    "txid": tx["txid"],
                    "sender": remetente,
                    "receiver": destinatario,
                    "amount": valor,
                    "timestamp": tx.get("timestamp", 0),
                })
            return {"count": len(saida), "transactions": saida}
        except Exception as e:
            return {"count": 0, "transactions": [], "error": str(e)}

    # Alias em inglês
    def get_mempool(self):
        return self.obter_mempool()

    # ==========================================================
    # CADEIA COMPLETA (usado pelo explorador)
    # ==========================================================
    def obter_cadeia_completa(self) -> dict:
        """Retorna os últimos 200 blocos + mempool para o explorador."""
        try:
            altura = self.bc.db.height()
            cadeia = []
            inicio = max(0, altura - 199)
            for h in range(inicio, altura + 1):
                b = self.bc.db.get_block(h)
                if not b:
                    continue
                txs = []
                for tx in b["transactions"]:
                    is_coinbase = tx["inputs"] and tx["inputs"][0]["txid"] == "0" * 64
                    remetente = "coinbase" if is_coinbase else "?"
                    for inp in tx["inputs"]:
                        u = self.bc.db.get_utxo(inp["txid"], inp["vout"])
                        if u:
                            remetente = u["address"]
                            break
                    destinatario = tx["outputs"][0]["address"] if tx["outputs"] else "?"
                    valor = sum(o["amount"] for o in tx["outputs"]) / UNIT
                    txs.append({
                        "txid": tx["txid"],
                        "sender": remetente,
                        "receiver": destinatario,
                        "amount": valor,
                        "timestamp": tx.get("timestamp", 0),
                    })
                cadeia.append({
                    "index": b["height"],
                    "height": b["height"],
                    "hash": b["hash"],
                    "prev_hash": b["prev_hash"],
                    "timestamp": b["timestamp"],
                    "nonce": b["nonce"],
                    "merkle": b["merkle"],
                    "difficulty": b["difficulty"],
                    "transactions": txs,
                })

            # Mempool resumida
            mp = []
            for tx in self.bc.db.all_mempool(limit=200):
                is_coinbase = tx["inputs"] and tx["inputs"][0]["txid"] == "0" * 64
                if is_coinbase:
                    continue
                remetente = "?"
                for inp in tx["inputs"]:
                    u = self.bc.db.get_utxo(inp["txid"], inp["vout"])
                    if u:
                        remetente = u["address"]
                        break
                destinatario = tx["outputs"][0]["address"] if tx["outputs"] else "?"
                valor = sum(o["amount"] for o in tx["outputs"]) / UNIT
                mp.append({
                    "txid": tx["txid"],
                    "sender": remetente,
                    "receiver": destinatario,
                    "amount": valor,
                    "timestamp": tx.get("timestamp", 0),
                })

            return {
                "length": len(cadeia),
                "height": altura,
                "chain": cadeia,
                "mempool": mp,
                "mempool_size": len(mp),
                "current_difficulty": self.bc.current_difficulty(),
                "is_mining": self.minerando,
            }
        except Exception as e:
            return {"length": 0, "height": 0, "chain": [], "mempool": [],
                    "mempool_size": 0, "current_difficulty": 0,
                    "is_mining": False, "error": str(e)}

    # Alias em inglês
    def get_full_chain(self):
        return self.obter_cadeia_completa()

    # ==========================================================
    # MINERAÇÃO
    # ==========================================================
    def alternar_mineracao(self, endereco: str) -> dict:
        """Liga ou desliga a mineração contínua."""
        with self.trava:
            if self.minerando:
                self.minerando = False
                self.endereco_minerador = None
                return {"status": "ok", "message": "Mineração parada."}

            if not endereco:
                endereco = self.wallet.address
            if not endereco:
                return {"status": "erro", "message": "Endereço inválido."}

            self.minerando = True
            self.endereco_minerador = endereco
            self.mineracao_thread = threading.Thread(
                target=self._laco_mineracao, args=(endereco,), daemon=True)
            self.mineracao_thread.start()
            return {"status": "ok",
                    "message": f"Mineração iniciada para {endereco[:16]}…"}

    # Alias em inglês (o HTML chama toggle_continuous_mining)
    def toggle_continuous_mining(self, endereco: str):
        return self.alternar_mineracao(endereco)

    def _laco_mineracao(self, endereco: str):
        """Roda enquanto self.minerando for True."""
        while self.minerando:
            try:
                bloco = self.bc.mine_block_interruptible(
                    endereco, should_continue=lambda: self.minerando)
                if bloco is None:
                    break

                # Propaga bloco pela rede
                if self.pm and self._p2p_loop:
                    try:
                        asyncio.run_coroutine_threadsafe(
                            self.pm.broadcast({
                                "type": "inv_block",
                                "height": bloco["height"],
                                "hash": bloco["hash"],
                            }), self._p2p_loop)
                    except Exception:
                        pass
            except Exception as e:
                print(f"[MINE] erro: {e}")
                break
            time.sleep(0.05)

    # ==========================================================
    # REDE
    # ==========================================================
    def obter_ips_locais(self) -> dict:
        """Retorna portas e IPs locais para a aba Rede."""
        return {
            "port": self.porta,
            "loopback": "127.0.0.1",
            "lan_addresses": obter_ips_lan(),
        }

    # Alias em inglês
    def get_local_ips(self):
        return self.obter_ips_locais()

    def conectar_e_sincronizar(self, ip: str, porta) -> dict:
        """Conecta a um peer e sincroniza a cadeia."""
        try:
            if not self.pm or not self._p2p_loop:
                return {"status": "erro",
                        "message": "P2P não inicializado (rode sem --no-p2p)."}
            fut = asyncio.run_coroutine_threadsafe(
                self.pm.connect(ip, int(porta)), self._p2p_loop)
            fut.result(timeout=15)
            return {"status": "sucesso",
                    "message": f"Conectado a {ip}:{porta} e sincronizado."}
        except Exception as e:
            return {"status": "erro", "message": f"Falha: {e}"}

    # Alias em inglês
    def connect_and_sync(self, ip: str, porta):
        return self.conectar_e_sincronizar(ip, porta)

    def obter_peers_conectados(self) -> dict:
        """Lista os peers atualmente conectados."""
        try:
            if not self.pm:
                return {"count": 0, "peers": []}
            peers = [{"ip": k[0], "port": k[1]} for k in self.pm.peers.keys()]
            return {"count": len(peers), "peers": peers}
        except Exception:
            return {"count": 0, "peers": []}

    # Alias em inglês
    def get_connected_peers(self):
        return self.obter_peers_conectados()

    # ==========================================================
    # VERIFICAÇÃO DE CADEIA  ← NOVO
    # ==========================================================
    def verificar_cadeia(self) -> dict:
        """
        Verifica a integridade da cadeia inteira e devolve um dicionário
        pronto para o front-end (index.html).
        """
        try:
            resultado = self.bc.verify_chain()
            return resultado.to_dict()
        except Exception as e:
            return {
                "valid": False,
                "errors": [str(e)],
                "warnings": [],
                "blocks_checked": 0,
                "txs_checked": 0,
                "height": 0,
                "tip_hash": "",
                "summary": f"Erro ao verificar: {e}",
            }

    # Alias em inglês (o HTML chama verify_chain)
    def verify_chain(self):
        return self.verificar_cadeia()


# ============================================================
# FUNÇÃO PRINCIPAL
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="BRN BrunoCoin — GUI pywebview")
    parser.add_argument("--port", type=int, default=PORTA_P2P_PADRAO,
                        help="Porta P2P (padrão 6001)")
    parser.add_argument("--db", default=None,
                        help="Caminho do banco SQLite")
    parser.add_argument("--miner", default=None,
                        help="Endereço brn1... que receberá as recompensas")
    parser.add_argument("--mine", action="store_true",
                        help="Inicia mineração automaticamente")
    parser.add_argument("--no-p2p", action="store_true",
                        help="Não inicializa a rede P2P")
    parser.add_argument("--peer", nargs=2, action="append",
                        metavar=("HOST", "PORT"),
                        help="Conectar a um peer no boot (pode repetir)")
    args = parser.parse_args()

    caminho_db = args.db or f"blockchain_gui_{args.port}.db"

    # --- Carteira persistente ---
    carteira = carregar_ou_criar_carteira()

    # --- Blockchain ---
    bc = Blockchain(db_path=caminho_db,
                    genesis_address=args.miner or carteira.address)

    # --- Banner ---
    print("=" * 64)
    print("  BRN — BrunoCoin  |  GUI pywebview")
    print("=" * 64)
    print(f"  Porta P2P   : {args.port}")
    print(f"  Banco       : {caminho_db}")
    print(f"  Altura      : {bc.db.height()}")
    print(f"  Tip         : {bc.db.tip_hash()[:24]}…")
    print(f"  Endereço    : {carteira.address}")
    print(f"  Saldo       : {bc.db.balance(carteira.address)/UNIT:.8f} BRN")
    print("=" * 64)
    print()

    # --- API ---
    api = BrnApi(bc, carteira, args.port)

    # --- P2P ---
    if not args.no_p2p:
        api.iniciar_p2p()

    # --- Mineração automática ---
    if args.mine:
        api.alternar_mineracao(args.miner or carteira.address)

    # --- Peers iniciais ---
    if args.peer:
        time.sleep(1.0)  # deixa o P2P subir
        for host, porta in args.peer:
            try:
                api.conectar_e_sincronizar(host, int(porta))
            except Exception as e:
                print(f"[P2P] falha em {host}:{porta} — {e}")

    # --- Janela pywebview ---
    base = os.path.dirname(os.path.abspath(__file__))
    caminho_html = os.path.join(base, "index.html")
    if not os.path.exists(caminho_html):
        print(f"[ERRO] index.html não encontrado em {caminho_html}")
        sys.exit(1)

    webview.create_window(
        "BRN — BrunoCoin",
        caminho_html,
        js_api=api,
        width=1240,
        height=840,
        min_size=(960, 640),
    )

    # Bloqueia até a janela ser fechada
    webview.start(debug=False, http_server=False)

    # Ao fechar
    api.minerando = False
    time.sleep(0.1)
    try:
        bc.db.close()
    except Exception:
        pass
    print("[BRN] encerrado.")


if __name__ == "__main__":
    main()
