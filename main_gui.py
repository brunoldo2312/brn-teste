# -*- coding: utf-8 -*-
"""
BRN GUI — Interface desktop (Tkinter) com:
  • Ativar / Desativar Mineração
  • Enviar Fundos (mempool)
  • Extrato de Transações
  • Mempool
  • Verificação de Cadeia
  • Blockchain (blocos)
"""
import os
import sys
import json
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from blockchain import Blockchain, UNIT, DECIMALS, txid as calc_txid, signing_hash
from wallet import Wallet


WALLET_FILE = "wallet_gui.brn"


# ============================================================
# CARTEIRA PERSISTENTE
# ============================================================
def load_or_create_wallet(path: str = WALLET_FILE) -> Wallet:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return Wallet(private_key_hex=data["private_key"])
        except Exception:
            backup = f"{path}.bak.{int(time.time())}"
            try:
                os.rename(path, backup)
            except Exception:
                pass
    w = Wallet()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"private_key": w.priv_hex, "address": w.address}, f, indent=2)
    except Exception:
        pass
    return w


# ============================================================
# GUI
# ============================================================
class BRNGui:
    def __init__(self, root: tk.Tk, port: int = 6001, db_path: str | None = None):
        self.root = root
        self.root.title("BRN — BrunoCoin Wallet (GUI)")
        self.root.geometry("1150x780")
        self.root.minsize(1000, 640)

        # --- Config ---
        self.port = port
        self.db_path = db_path or f"blockchain_gui_{port}.db"

        # --- Carteira ---
        self.wallet = load_or_create_wallet()

        # --- Blockchain ---
        self.bc = Blockchain(db_path=self.db_path, genesis_address=self.wallet.address)

        # --- Estado de mineração ---
        self.mining = False
        self.mining_thread: threading.Thread | None = None

        # --- Estilo ---
        self._style()

        # --- Constrói UI ---
        self._build_ui()

        # --- Refresh inicial ---
        self.refresh_all()
        self.log(f"Carteira carregada: {self.wallet.address}")
        self.log(f"Banco: {self.db_path}  |  Altura: {self.bc.db.height()}")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------
    def _style(self):
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure("Treeview", rowheight=24)
        s.configure("Green.TLabel", foreground="#0a7d28")
        s.configure("Red.TLabel", foreground="#c0392b")
        s.configure("Gold.TLabel", foreground="#b8860b",
                    font=("Arial", 12, "bold"))
        s.configure("Title.TLabel", font=("Arial", 11, "bold"))

    # ------------------------------------------------------------
    def _build_ui(self):
        # ---------- Cabeçalho ----------
        header = ttk.LabelFrame(self.root, text="Carteira", padding=10)
        header.pack(fill="x", padx=10, pady=(10, 6))

        ttk.Label(header, text="Endereço:", style="Title.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(header, text=self.wallet.address,
                  font=("Consolas", 10)).grid(row=0, column=1, sticky="w", padx=(6, 20))

        ttk.Label(header, text="Altura da cadeia:", style="Title.TLabel").grid(
            row=0, column=2, sticky="w")
        self.lbl_height = ttk.Label(header, text="0", font=("Consolas", 10))
        self.lbl_height.grid(row=0, column=3, sticky="w", padx=6)

        ttk.Label(header, text="Saldo:", style="Title.TLabel").grid(
            row=1, column=0, sticky="w", pady=(6, 0))
        self.lbl_balance = ttk.Label(header, text="0.00000000 BRN",
                                     style="Gold.TLabel")
        self.lbl_balance.grid(row=1, column=1, sticky="w", padx=6, pady=(6, 0))

        ttk.Label(header, text="Disponível:", style="Title.TLabel").grid(
            row=1, column=2, sticky="w", pady=(6, 0))
        self.lbl_available = ttk.Label(header, text="0.00000000 BRN",
                                       font=("Consolas", 10))
        self.lbl_available.grid(row=1, column=3, sticky="w", padx=6, pady=(6, 0))

        # ---------- Toolbar ----------
        toolbar = ttk.Frame(self.root, padding=(10, 4))
        toolbar.pack(fill="x")

        self.btn_mining = ttk.Button(toolbar, text="▶ Ativar Mineração",
                                     width=22, command=self.toggle_mining)
        self.btn_mining.pack(side="left", padx=(0, 6))

        ttk.Button(toolbar, text="💸 Enviar Fundos", width=18,
                   command=self.open_send_dialog).pack(side="left", padx=6)
        ttk.Button(toolbar, text="🔎 Verificar Cadeia", width=18,
                   command=self.verify_chain_dialog).pack(side="left", padx=6)
        ttk.Button(toolbar, text="🔄 Atualizar", width=12,
                   command=self.refresh_all).pack(side="left", padx=6)
        ttk.Button(toolbar, text="🧹 Limpar Log", width=12,
                   command=self.clear_log).pack(side="left", padx=6)

        self.lbl_mining = ttk.Label(toolbar, text="Mineração: PARADA",
                                    style="Red.TLabel",
                                    font=("Arial", 10, "bold"))
        self.lbl_mining.pack(side="right", padx=8)

        # ---------- Notebook ----------
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=6)

        self._build_tab_extrato()
        self._build_tab_mempool()
        self._build_tab_chain()
        self._build_tab_verificacao()

        # ---------- Log ----------
        log_frame = ttk.LabelFrame(self.root, text="Log de atividades", padding=6)
        log_frame.pack(fill="both", padx=10, pady=(4, 10))

        self.txt_log = tk.Text(log_frame, height=7, wrap="word", state="disabled",
                               bg="#111", fg="#8ef58e", insertbackground="#8ef58e",
                               font=("Consolas", 9))
        self.txt_log.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(log_frame, command=self.txt_log.yview)
        sb.pack(side="right", fill="y")
        self.txt_log.configure(yscrollcommand=sb.set)

    # -------------------- Aba Extrato --------------------
    def _build_tab_extrato(self):
        f = ttk.Frame(self.notebook)
        self.notebook.add(f, text="Extrato de Transações")

        top = ttk.Frame(f)
        top.pack(fill="x", pady=(4, 6))
        ttk.Label(top, text="Movimentações da carteira", style="Title.TLabel").pack(side="left")
        ttk.Button(top, text="🔄 Atualizar", command=self.refresh_extrato).pack(side="right")

        cols = ("status", "tipo", "direcao", "contraparte", "valor", "bloco", "data", "txid")
        self.tree_extrato = ttk.Treeview(f, columns=cols, show="headings")

        heads = {
            "status": ("Status", 90),
            "tipo": ("Tipo", 100),
            "direcao": ("Direção", 80),
            "contraparte": ("Contraparte", 240),
            "valor": ("Valor (BRN)", 120),
            "bloco": ("Bloco", 70),
            "data": ("Data/Hora", 150),
            "txid": ("TX ID", 200),
        }
        for c, (txt, w) in heads.items():
            self.tree_extrato.heading(c, text=txt)
            self.tree_extrato.column(c, width=w, anchor="center")

        self.tree_extrato.tag_configure("in", foreground="#0a7d28")
        self.tree_extrato.tag_configure("out", foreground="#c0392b")
        self.tree_extrato.tag_configure("pending", background="#fff8d6")

        self.tree_extrato.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(f, orient="vertical", command=self.tree_extrato.yview)
        sb.pack(side="right", fill="y")
        self.tree_extrato.configure(yscrollcommand=sb.set)

    # -------------------- Aba Mempool --------------------
    def _build_tab_mempool(self):
        f = ttk.Frame(self.notebook)
        self.notebook.add(f, text="Mempool")

        top = ttk.Frame(f)
        top.pack(fill="x", pady=(4, 6))
        self.lbl_mempool = ttk.Label(top, text="Pendentes: 0", style="Title.TLabel")
        self.lbl_mempool.pack(side="left")
        ttk.Button(top, text="🔄 Atualizar",
                   command=self.refresh_mempool).pack(side="right")

        cols = ("txid", "de", "para", "valor", "taxa", "data")
        self.tree_mempool = ttk.Treeview(f, columns=cols, show="headings")
        for c, (txt, w) in {
            "txid": ("TX ID", 220),
            "de": ("De", 220),
            "para": ("Para", 220),
            "valor": ("Valor", 110),
            "taxa": ("Taxa", 80),
            "data": ("Recebida em", 150),
        }.items():
            self.tree_mempool.heading(c, text=txt)
            self.tree_mempool.column(c, width=w, anchor="center")

        self.tree_mempool.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(f, orient="vertical", command=self.tree_mempool.yview)
        sb.pack(side="right", fill="y")
        self.tree_mempool.configure(yscrollcommand=sb.set)

    # -------------------- Aba Blockchain --------------------
    def _build_tab_chain(self):
        f = ttk.Frame(self.notebook)
        self.notebook.add(f, text="Blockchain")

        top = ttk.Frame(f)
        top.pack(fill="x", pady=(4, 6))
        self.lbl_chain = ttk.Label(top, text="Altura: 0", style="Title.TLabel")
        self.lbl_chain.pack(side="left")
        ttk.Button(top, text="🔎 Verificar",
                   command=self.verify_chain_dialog).pack(side="right")
        ttk.Button(top, text="🔄 Atualizar",
                   command=self.refresh_chain).pack(side="right", padx=6)

        cols = ("height", "hash", "prev", "txs", "nonce", "diff", "data")
        self.tree_chain = ttk.Treeview(f, columns=cols, show="headings")
        for c, (txt, w) in {
            "height": ("#", 50),
            "hash": ("Hash", 240),
            "prev": ("Hash anterior", 240),
            "txs": ("Nº TXs", 70),
            "nonce": ("Nonce", 90),
            "diff": ("Diff", 60),
            "data": ("Data/Hora", 150),
        }.items():
            self.tree_chain.heading(c, text=txt)
            self.tree_chain.column(c, width=w, anchor="center")

        self.tree_chain.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(f, orient="vertical", command=self.tree_chain.yview)
        sb.pack(side="right", fill="y")
        self.tree_chain.configure(yscrollcommand=sb.set)

    # -------------------- Aba Verificação --------------------
    def _build_tab_verificacao(self):
        f = ttk.Frame(self.notebook)
        self.notebook.add(f, text="Verificação")

        top = ttk.Frame(f)
        top.pack(fill="x", pady=(4, 6))
        ttk.Label(top, text="Integridade da cadeia",
                  style="Title.TLabel").pack(side="left")
        ttk.Button(top, text="🔎 Verificar agora",
                   command=self.verify_chain_dialog).pack(side="right")

        self.txt_verify = tk.Text(f, wrap="word", font=("Consolas", 10),
                                  bg="#fbfbfb", fg="#222",
                                  relief="flat", padx=10, pady=10)
        self.txt_verify.pack(fill="both", expand=True, padx=4, pady=4)
        self.txt_verify.tag_configure("ok", foreground="#0a7d28",
                                      font=("Consolas", 11, "bold"))
        self.txt_verify.tag_configure("err", foreground="#c0392b",
                                      font=("Consolas", 10, "bold"))
        self.txt_verify.tag_configure("warn", foreground="#b8860b")
        self.txt_verify.tag_configure("dim", foreground="#666")
        self.txt_verify.configure(state="disabled")

    # ============================================================
    # MINERAÇÃO
    # ============================================================
    def toggle_mining(self):
        if self.mining:
            self.mining = False
            self.btn_mining.config(text="▶ Ativar Mineração")
            self.lbl_mining.config(text="Mineração: PARADA", style="Red.TLabel")
            self.log("Mineração DESATIVADA.")
        else:
            self.mining = True
            self.btn_mining.config(text="⏸ Parar Mineração")
            self.lbl_mining.config(text="Mineração: ATIVA", style="Green.TLabel")
            self.mining_thread = threading.Thread(
                target=self._mining_loop, daemon=True)
            self.mining_thread.start()
            self.log(f"Mineração ATIVADA para {self.wallet.address[:16]}…")

    def _mining_loop(self):
        while self.mining:
            try:
                block = self.bc.mine_block_interruptible(
                    self.wallet.address,
                    should_continue=lambda: self.mining,
                )
                if block is None:
                    break
                saldo = self.bc.db.balance(self.wallet.address) / UNIT
                self.root.after(0, self.refresh_all)
                self.root.after(0, lambda b=block, s=saldo: self.log(
                    f"Bloco #{b['height']} minerado | "
                    f"{len(b['transactions'])} tx(s) | "
                    f"diff={b['difficulty']} | saldo={s:.8f} BRN"
                ))
            except Exception as e:
                self.root.after(0, lambda err=e: self.log(f"Erro mineração: {err}"))
                break
            time.sleep(0.05)

    # ============================================================
    # ENVIO DE FUNDOS
    # ============================================================
    def open_send_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Enviar Fundos")
        dlg.geometry("560x320")
        dlg.transient(self.root)
        dlg.grab_set()

        pad = {"padx": 10, "pady": 6}
        ttk.Label(dlg, text="Destino:", style="Title.TLabel").pack(anchor="w", **pad)
        ent_to = ttk.Entry(dlg, width=70, font=("Consolas", 9))
        ent_to.pack(fill="x", **pad)

        ttk.Label(dlg, text="Valor (BRN):", style="Title.TLabel").pack(anchor="w", **pad)
        ent_amt = ttk.Entry(dlg, width=22)
        ent_amt.pack(anchor="w", **pad)

        disp = self.bc.db.balance(self.wallet.address) / UNIT
        ttk.Label(dlg, text=f"Disponível: {disp:.8f} BRN",
                  style="Green.TLabel").pack(anchor="w", **pad)

        def gerar_destino():
            ent_to.delete(0, tk.END)
            ent_to.insert(0, Wallet().address)

        ttk.Button(dlg, text="🎲 Gerar destino aleatório",
                   command=gerar_destino).pack(anchor="w", **pad)

        def confirmar():
            destino = ent_to.get().strip()
            try:
                valor = float(ent_amt.get().strip().replace(",", "."))
            except ValueError:
                messagebox.showerror("Erro", "Valor inválido.", parent=dlg)
                return
            if not destino:
                messagebox.showwarning("Aviso", "Informe o destino.", parent=dlg)
                return
            if destino == self.wallet.address:
                messagebox.showwarning("Aviso", "Destino é a própria carteira.", parent=dlg)
                return
            if valor <= 0:
                messagebox.showerror("Erro", "Valor deve ser > 0.", parent=dlg)
                return

            valor_units = int(round(valor * UNIT))
            ok, msg, tx_id = self._build_and_send_tx(destino, valor_units)
            if not ok:
                messagebox.showerror("Erro", msg, parent=dlg)
                return
            self.log(f"TX enviada para mempool: {valor:.8f} BRN → {destino[:18]}…  id={tx_id[:16]}")
            self.refresh_all()
            dlg.destroy()

        btns = ttk.Frame(dlg)
        btns.pack(fill="x", pady=14)
        ttk.Button(btns, text="Confirmar envio",
                   command=confirmar).pack(side="left", padx=10)
        ttk.Button(btns, text="Cancelar",
                   command=dlg.destroy).pack(side="left")

    def _build_and_send_tx(self, destino: str, valor_units: int) -> tuple[bool, str, str]:
        """Seleciona UTXOs, monta tx assinada e coloca na mempool."""
        utxos = self.bc.db.utxos_for(self.wallet.address)
        if not utxos:
            return False, "Sem UTXOs disponíveis.", ""

        total = 0
        chosen = []
        for u in sorted(utxos, key=lambda x: -x["amount"]):
            chosen.append(u)
            total += u["amount"]
            if total >= valor_units:
                break
        if total < valor_units:
            return False, f"Saldo insuficiente ({total/UNIT:.8f} < {valor_units/UNIT:.8f}).", ""

        # monta outputs
        outputs = [{"address": destino, "amount": valor_units, "pubkey": ""}]
        troco = total - valor_units
        if troco > 0:
            outputs.append({"address": self.wallet.address,
                            "amount": troco, "pubkey": self.wallet.pub_hex})

        inputs = []
        for u in chosen:
            inputs.append({
                "txid": u["txid"],
                "vout": u["vout"],
                "pubkey": self.wallet.pub_hex,
                "signature": "",
            })

        tx = {
            "txid": "",
            "inputs": inputs,
            "outputs": outputs,
            "timestamp": int(time.time()),
            "locktime": 0,
        }
        tx["txid"] = calc_txid(tx)

        # assina cada input
        msg_hash = signing_hash(tx)
        for inp in tx["inputs"]:
            inp["signature"] = self.wallet.sign(msg_hash)

        # recalcula txid (assinaturas não entram no txid, mas por segurança)
        tx["txid"] = calc_txid(tx)

        ok, msg = self.bc.submit_tx(tx)
        if not ok:
            return False, msg, ""
        return True, "ok", tx["txid"]

    # ============================================================
    # VERIFICAÇÃO DE CADEIA
    # ============================================================
    def verify_chain_dialog(self):
        # roda em thread para não travar a UI
        self.txt_verify.configure(state="normal")
        self.txt_verify.delete("1.0", "end")
        self.txt_verify.insert("end", "⏳ Verificando integridade da cadeia...\n", "dim")
        self.txt_verify.configure(state="disabled")

        def run():
            result = self.bc.verify_chain()
            self.root.after(0, lambda r=result: self._render_verification(r))

        threading.Thread(target=run, daemon=True).start()

    def _render_verification(self, result):
        t = self.txt_verify
        t.configure(state="normal")
        t.delete("1.0", "end")

        if result.valid:
            t.insert("end", "✅ CADEIA ÍNTEGRA\n\n", "ok")
        else:
            t.insert("end", "❌ CADEIA INVÁLIDA\n\n", "err")

        t.insert("end",
                 f"Altura verificada    : {result.height}\n"
                 f"Blocos verificados   : {result.blocks_checked}\n"
                 f"Transações verificadas: {result.txs_checked}\n"
                 f"Tip hash             : {result.tip_hash[:32]}…\n")
        t.insert("end", "\n" + "─" * 70 + "\n\n")

        t.insert("end", "Checagens realizadas:\n", "dim")
        for linha in [
            "• Bloco gênese válido (height 0, prev_hash zerado)",
            "• Alturas sequenciais (0, 1, 2, ...)",
            "• Encadeamento (prev_hash == hash anterior)",
            "• Hash do bloco recalculado (não adulterado)",
            "• Prova de trabalho (hash ≤ target)",
            "• Merkle root confere com as txids",
            "• Coinbase única na posição 0",
            "• Coinbase ≤ recompensa + taxas",
            "• Ausência de gasto duplo (UTXO gasto 2x)",
            "• Ausência de txid duplicada",
            "• Saldos nunca negativos",
        ]:
            t.insert("end", "  " + linha + "\n", "dim")
        t.insert("end", "\n" + "─" * 70 + "\n\n")

        if result.errors:
            t.insert("end", f"ERROS ({len(result.errors)}):\n", "err")
            for e in result.errors:
                t.insert("end", f"  ✗ {e}\n", "err")
            t.insert("end", "\n")
        else:
            t.insert("end", "Nenhum erro encontrado. ✅\n\n", "ok")

        if result.warnings:
            t.insert("end", f"AVISOS ({len(result.warnings)}):\n", "warn")
            for w in result.warnings:
                t.insert("end", f"  ⚠ {w}\n", "warn")
        else:
            t.insert("end", "Nenhum aviso.\n", "ok")

        t.configure(state="disabled")
        self.log(f"Verificação de cadeia: {result.summary()}")

    # ============================================================
    # REFRESH
    # ============================================================
    def refresh_all(self):
        try:
            self.refresh_header()
            self.refresh_extrato()
            self.refresh_mempool()
            self.refresh_chain()
        except Exception as e:
            self.log(f"Erro ao atualizar UI: {e}")

    def refresh_header(self):
        addr = self.wallet.address
        saldo = self.bc.db.balance(addr) / UNIT
        pend = self._pending_out(addr) / UNIT
        disp = saldo - pend
        self.lbl_balance.config(text=f"{saldo:.8f} BRN")
        extra = f" (pendente -{pend:.8f})" if pend > 0 else ""
        self.lbl_available.config(text=f"{disp:.8f} BRN{extra}")
        self.lbl_height.config(text=str(self.bc.db.height()))

    def _pending_out(self, addr: str) -> int:
        total = 0
        for tx in self.bc.db.all_mempool(limit=10000):
            for inp in tx.get("inputs", []):
                u = None
                try:
                    u = self.bc.db.get_utxo(inp["txid"], inp["vout"])
                except Exception:
                    pass
                # heurística: se o UTXO está marcado como "gasto" pelo mempool não
                # temos rastreio direto; contamos inputs cuja pubkey == nossa.
            # simplificação: olhamos outputs que NÃO são para nós e inputs com nossa pubkey
        # por ora, retorna 0 (contabilização precisa exige rastreio de UTXO no mempool)
        return total

    def refresh_extrato(self):
        for i in self.tree_extrato.get_children():
            self.tree_extrato.delete(i)

        addr = self.wallet.address
        linhas = []

        # varre cadeia
        for h in range(self.bc.db.height() + 1):
            block = self.bc.db.get_block(h)
            if not block:
                continue
            for tx in block["transactions"]:
                is_cb = tx["inputs"] and tx["inputs"][0]["txid"] == "0" * 64
                envolve = False
                if is_cb:
                    for o in tx["outputs"]:
                        if o["address"] == addr:
                            envolve = True
                            break
                else:
                    for o in tx["outputs"]:
                        if o["address"] == addr:
                            envolve = True
                            break
                    if not envolve:
                        for inp in tx["inputs"]:
                            if inp.get("pubkey") == self.wallet.pub_hex:
                                envolve = True
                                break
                if envolve:
                    linhas.append((tx, "Confirmada", h, is_cb))

        # varre mempool
        for tx in self.bc.db.all_mempool(limit=10000):
            is_cb = tx["inputs"] and tx["inputs"][0]["txid"] == "0" * 64
            envolve = False
            for o in tx["outputs"]:
                if o["address"] == addr:
                    envolve = True
                    break
            if not envolve:
                for inp in tx["inputs"]:
                    if inp.get("pubkey") == self.wallet.pub_hex:
                        envolve = True
                        break
            if envolve:
                linhas.append((tx, "Pendente", "-", is_cb))

        linhas.sort(key=lambda r: r[0].get("timestamp", 0), reverse=True)

        for tx, status, bloco, is_cb in linhas:
            # calcula valor e direção para esta carteira
            recebido = sum(o["amount"] for o in tx["outputs"] if o["address"] == addr)
            enviado = 0
            for inp in tx["inputs"]:
                if inp.get("pubkey") == self.wallet.pub_hex:
                    enviado = 1  # marca presença; valor vem do UTXO

            if is_cb and recebido > 0:
                tipo = "Recompensa"
                direcao = "entrada"
                valor = recebido / UNIT
                tag = "in"
                contraparte = "coinbase"
            elif enviado and recebido >= 0:
                # envio (pode ter troco)
                valor_out = sum(o["amount"] for o in tx["outputs"]
                                if o["address"] != addr) / UNIT
                if valor_out > 0:
                    tipo = "Envio"
                    direcao = "saída"
                    valor = valor_out
                    tag = "out"
                    # contraparte = primeiro output que não é nosso
                    dests = [o["address"] for o in tx["outputs"] if o["address"] != addr]
                    contraparte = dests[0] if dests else "?"
                else:
                    tipo = "Troco"
                    direcao = "entrada"
                    valor = recebido / UNIT
                    tag = "in"
                    contraparte = "próprio"
            else:
                tipo = "Recebimento"
                direcao = "entrada"
                valor = recebido / UNIT
                tag = "in"
                # contraparte: input pubkey
                contraparte = "?"
                for inp in tx["inputs"]:
                    if inp.get("pubkey") and inp["pubkey"] != self.wallet.pub_hex:
                        contraparte = inp["pubkey"][:24] + "…"
                        break

            if status == "Pendente":
                tag = "pending"

            self.tree_extrato.insert(
                "", "end",
                values=(
                    status,
                    tipo,
                    direcao,
                    contraparte[:24] + ("…" if len(contraparte) > 24 else ""),
                    f"{valor:.8f}",
                    bloco,
                    time.strftime("%d/%m/%Y %H:%M:%S",
                                  time.localtime(tx.get("timestamp", 0))),
                    tx["txid"][:20] + "…",
                ),
                tags=(tag,),
            )

    def refresh_mempool(self):
        for i in self.tree_mempool.get_children():
            self.tree_mempool.delete(i)

        txs = self.bc.db.all_mempool(limit=10000)
        self.lbl_mempool.config(text=f"Pendentes: {len(txs)}")

        for tx in txs:
            is_cb = tx["inputs"] and tx["inputs"][0]["txid"] == "0" * 64
            if is_cb:
                continue
            remetente = tx["inputs"][0].get("pubkey", "?")[:20] + "…"
            dest = tx["outputs"][0]["address"][:20] + "…" if tx["outputs"] else "?"
            valor = sum(o["amount"] for o in tx["outputs"]) / UNIT
            taxa = self.bc.tx_fee(tx) / UNIT
            self.tree_mempool.insert(
                "", "end",
                values=(
                    tx["txid"][:20] + "…",
                    remetente,
                    dest,
                    f"{valor:.8f}",
                    f"{taxa:.8f}",
                    time.strftime("%d/%m/%Y %H:%M:%S",
                                  time.localtime(tx.get("timestamp", 0))),
                ),
            )

    def refresh_chain(self):
        for i in self.tree_chain.get_children():
            self.tree_chain.delete(i)

        height = self.bc.db.height()
        self.lbl_chain.config(text=f"Altura: {height} bloco(s)")

        # mostra os últimos 200 blocos
        start = max(0, height - 200)
        for h in range(height, start - 1, -1):
            b = self.bc.db.get_block(h)
            if not b:
                continue
            self.tree_chain.insert(
                "", "end",
                values=(
                    b["height"],
                    b["hash"][:36] + "…",
                    b["prev_hash"][:36] + "…",
                    len(b["transactions"]),
                    b["nonce"],
                    b["difficulty"],
                    time.strftime("%d/%m/%Y %H:%M:%S",
                                  time.localtime(b["timestamp"])),
                ),
            )

    # ============================================================
    # LOG
    # ============================================================
    def log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", f"[{ts}] {msg}\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def clear_log(self):
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

    # ============================================================
    def _on_close(self):
        self.mining = False
        time.sleep(0.1)
        try:
            self.bc.db.close()
        except Exception:
            pass
        self.root.destroy()


# ============================================================
# ENTRYPOINT
# ============================================================
def main():
    port = 6001
    db_path = None
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    if len(sys.argv) > 2:
        db_path = sys.argv[2]

    root = tk.Tk()
    BRNGui(root, port=port, db_path=db_path)
    root.mainloop()


if __name__ == "__main__":
    main()
