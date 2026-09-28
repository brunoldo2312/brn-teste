"""
auto_discovery.py — Descoberta automática de nós na LAN
============================================================
Usa multicast UDP para encontrar outros nós BrunoCoin
na mesma rede local.
============================================================
"""

import socket
import threading
import time
import uuid
import json
import hashlib
import os

# ============================================================
# CONFIGURAÇÃO
# ============================================================
# ✅ BUG #1: faixa de administração local (não conflita com SSDP)
MULTICAST_GROUP = '239.255.42.99'
MULTICAST_PORT  = 50007

# ✅ BUG #6: token compartilhado para autenticação
NETWORK_SECRET = "brunocoin-lan-2026"
TOKEN_ESPERADO = hashlib.sha256(NETWORK_SECRET.encode()).hexdigest()[:8]

# ✅ BUG #2: UUID único desta instância (persistido em arquivo)
UUID_FILE = "node_uuid.txt"

PEER_TIMEOUT    = 60    # peers sem ping por 60s = morto
PEER_CLEANUP_S  = 30    # limpa peers mortos a cada 30s
PING_INTERVAL_INICIAL = 2.0
PING_INTERVAL_MAX     = 30.0
PEERS_FILE      = "peers_discovered.json"


def _obter_ou_criar_uuid() -> str:
    """Retorna UUID persistente do nó."""
    if os.path.exists(UUID_FILE):
        with open(UUID_FILE) as f:
            return f.read().strip()
    novo = str(uuid.uuid4())
    with open(UUID_FILE, "w") as f:
        f.write(novo)
    return novo


class AutoNodeDiscovery:
    """
    Descoberta automática de peers via multicast UDP.
    
    Uso:
        discovery = AutoNodeDiscovery(
            p2p_port=6001,
            on_peer_found=lambda ip, port: print(f"Novo: {ip}:{port}")
        )
        discovery.run()
        # ... depois ...
        discovery.stop()
    """

    def __init__(self, p2p_port: int = 6001, on_peer_found=None):
        self.p2p_port = int(p2p_port)
        self.node_uuid = _obter_ou_criar_uuid()
        self.on_peer_found = on_peer_found

        # ✅ BUG #3: dict com timestamp + lock
        self.discovered_peers = {}   # {"ip:port": timestamp}
        self.peers_lock = threading.Lock()

        # ✅ BUG #9: controle de PONG enviado
        self.peers_respondidos = set()

        self.running = False
        self.server_socket = None
        self.client_socket = None
        self._threads = []

        # ✅ MELHORIA #12: carrega peers anteriores
        self._carregar_peers()

    # ==========================================================
    # UTILITÁRIOS
    # ==========================================================
    def _get_local_ip(self) -> str:
        """Descobre o IP real deste computador."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
        except Exception:
            ip = '127.0.0.1'
        finally:
            s.close()
        return ip

    def _mesma_subnet(self, ip1: str, ip2: str) -> bool:
        """✅ MELHORIA #10: mesma /24?"""
        try:
            return ip1.rsplit('.', 1)[0] == ip2.rsplit('.', 1)[0]
        except Exception:
            return False

    def _token_valido(self, msg: str) -> bool:
        """✅ BUG #6: valida token compartilhado."""
        try:
            return msg.split(":")[-1] == TOKEN_ESPERADO
        except Exception:
            return False

    # ==========================================================
    # PERSISTÊNCIA — MELHORIA #12
    # ==========================================================
    def _salvar_peers(self):
        try:
            with self.peers_lock:
                lista = list(self.discovered_peers.keys())
            with open(PEERS_FILE, "w") as f:
                json.dump(lista, f)
        except Exception:
            pass

    def _carregar_peers(self):
        try:
            if not os.path.exists(PEERS_FILE):
                return
            with open(PEERS_FILE) as f:
                for addr in json.load(f):
                    self.discovered_peers[addr] = 0  # timestamp 0 = desconhecido
        except Exception:
            pass

    # ==========================================================
    # SERVIDOR — ESCUTA MULTICAST
    # ==========================================================
    def _start_server(self):
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # ✅ MELHORIA #8: permitir múltiplas instâncias (Linux)
            try:
                self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except (AttributeError, OSError):
                pass  # Windows não suporta

            self.server_socket.bind(('', MULTICAST_PORT))

            # Entrar no grupo multicast
            mreq = socket.inet_aton(MULTICAST_GROUP) + socket.inet_aton('0.0.0.0')
            self.server_socket.setsockopt(
                socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq
            )

            local_ip = self._get_local_ip()
            print(f"📡 [Discovery] Escutando em {MULTICAST_GROUP}:{MULTICAST_PORT}")
            print(f"📡 [Discovery] IP local: {local_ip}")
            print(f"📡 [Discovery] UUID: {self.node_uuid[:8]}…")

            while self.running:
                try:
                    self.server_socket.settimeout(2.0)
                    data, addr = self.server_socket.recvfrom(2048)
                    remote_ip = addr[0]

                    # ✅ MELHORIA #10: só aceita da mesma subnet
                    if not self._mesma_subnet(remote_ip, local_ip):
                        continue

                    msg = data.decode("utf-8", errors="ignore")

                    # ✅ BUG #6: valida token
                    if not self._token_valido(msg):
                        continue

                    if msg.startswith("BRN_NODE_PING:"):
                        self._processar_ping(msg, remote_ip, addr)
                    elif msg.startswith("BRN_NODE_PONG:"):
                        self._processar_pong(msg, remote_ip)
                    elif msg.startswith("BRN_NODE_BYE:"):
                        self._processar_bye(msg, remote_ip)

                except socket.timeout:
                    continue
                except OSError:
                    # Socket fechado durante shutdown
                    break
                except Exception as e:
                    print(f"[Discovery] Erro: {e}")

        except Exception as e:
            print(f"[Discovery] Falha crítica no servidor: {e}")

    def _processar_ping(self, msg: str, remote_ip: str, addr):
        """PING recebido — registra peer e responde."""
        try:
            partes = msg.split(":")
            if len(partes) < 3:
                return

            remote_port = int(partes[1])
            remote_uuid = partes[2]

            # ✅ BUG #2: compara por UUID
            if remote_uuid == self.node_uuid:
                return  # é eu mesmo

            peer_address = f"{remote_ip}:{remote_port}"

            # ✅ BUG #3: lock
            with self.peers_lock:
                novo = peer_address not in self.discovered_peers
                self.discovered_peers[peer_address] = time.time()

            if novo:
                print(f"✨ [Discovery] Novo peer: {peer_address}")
                self._salvar_peers()
                if self.on_peer_found:
                    try:
                        self.on_peer_found(remote_ip, remote_port)
                    except Exception as e:
                        print(f"[Discovery] Erro no callback: {e}")

            # ✅ BUG #9: só responde 1× por peer
            if remote_ip not in self.peers_respondidos:
                self.peers_respondidos.add(remote_ip)
                response = (
                    f"BRN_NODE_PONG:{self.p2p_port}:"
                    f"{self.node_uuid}:{TOKEN_ESPERADO}"
                )
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.sendto(response.encode("utf-8"), addr)
                    sock.close()
                except Exception:
                    pass

        except Exception as e:
            print(f"[Discovery] Erro em PING: {e}")

    def _processar_pong(self, msg: str, remote_ip: str):
        """PONG recebido — registra peer."""
        try:
            partes = msg.split(":")
            if len(partes) < 3:
                return

            remote_port = int(partes[1])
            remote_uuid = partes[2]

            if remote_uuid == self.node_uuid:
                return

            peer_address = f"{remote_ip}:{remote_port}"

            with self.peers_lock:
                novo = peer_address not in self.discovered_peers
                self.discovered_peers[peer_address] = time.time()

            if novo:
                print(f"🤝 [Discovery] Conexão mútua: {peer_address}")
                self._salvar_peers()
                if self.on_peer_found:
                    try:
                        self.on_peer_found(remote_ip, remote_port)
                    except Exception as e:
                        print(f"[Discovery] Erro no callback: {e}")

        except Exception as e:
            print(f"[Discovery] Erro em PONG: {e}")

    def _processar_bye(self, msg: str, remote_ip: str):
        """BYE recebido — remove peer."""
        try:
            partes = msg.split(":")
            if len(partes) < 3:
                return

            remote_port = int(partes[1])
            peer_address = f"{remote_ip}:{remote_port}"

            with self.peers_lock:
                if peer_address in self.discovered_peers:
                    del self.discovered_peers[peer_address]
                    print(f"👋 [Discovery] Peer saiu: {peer_address}")

        except Exception:
            pass

    # ==========================================================
    # CLIENTE — BROADCAST PERIÓDICO
    # ==========================================================
    def _start_client(self):
        try:
            self.client_socket = socket.socket(
                socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
            )
            self.client_socket.setsockopt(
                socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2
            )
            # Loopback: permite 2 instâncias no mesmo PC
            self.client_socket.setsockopt(
                socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1
            )

            print("🚀 [Discovery] Broadcast ativo")

            intervalo = PING_INTERVAL_INICIAL

            while self.running:
                try:
                    msg = (
                        f"BRN_NODE_PING:{self.p2p_port}:"
                        f"{self.node_uuid}:{TOKEN_ESPERADO}"
                    )
                    self.client_socket.sendto(
                        msg.encode("utf-8"),
                        (MULTICAST_GROUP, MULTICAST_PORT)
                    )

                    # ✅ MELHORIA #11: backoff adaptativo
                    with self.peers_lock:
                        n = len(self.discovered_peers)

                    if n >= 5:
                        intervalo = PING_INTERVAL_MAX
                    elif n >= 2:
                        intervalo = 10.0
                    else:
                        intervalo = PING_INTERVAL_INICIAL

                    time.sleep(intervalo)

                except OSError:
                    break
                except Exception as e:
                    print(f"[Discovery] Erro no broadcast: {e}")
                    time.sleep(5)

        except Exception as e:
            print(f"[Discovery] Falha crítica no cliente: {e}")

    # ==========================================================
    # LIMPEZA — BUG #4
    # ==========================================================
    def _limpar_peers_mortos(self):
        while self.running:
            try:
                time.sleep(PEER_CLEANUP_S)
                agora = time.time()
                removidos = []

                with self.peers_lock:
                    for addr, ts in list(self.discovered_peers.items()):
                        if ts > 0 and (agora - ts) > PEER_TIMEOUT:
                            del self.discovered_peers[addr]
                            removidos.append(addr)

                if removidos:
                    print(f"🧹 [Discovery] Removidos {len(removidos)} peers inativos")
                    self._salvar_peers()

            except Exception:
                pass

    # ==========================================================
    # CONTROLE
    # ==========================================================
    def run(self):
        """Inicia os 3 threads: escuta, broadcast e limpeza."""
        if self.running:
            return
        self.running = True

        t1 = threading.Thread(target=self._start_server,         daemon=True, name="Discovery-Server")
        t2 = threading.Thread(target=self._start_client,         daemon=True, name="Discovery-Client")
        t3 = threading.Thread(target=self._limpar_peers_mortos,  daemon=True, name="Discovery-Cleanup")

        self._threads = [t1, t2, t3]
        for t in self._threads:
            t.start()

    def stop(self):
        """✅ BUG #5: fecha sockets e envia BYE."""
        if not self.running:
            return

        print("[Discovery] Encerrando…")
        self.running = False

        # Envia BYE para avisar a rede
        try:
            if self.client_socket:
                bye = (
                    f"BRN_NODE_BYE:{self.p2p_port}:"
                    f"{self.node_uuid}:{TOKEN_ESPERADO}"
                )
                self.client_socket.sendto(
                    bye.encode("utf-8"),
                    (MULTICAST_GROUP, MULTICAST_PORT)
                )
        except Exception:
            pass

        # Fecha sockets
        for sock in (self.server_socket, self.client_socket):
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass

        # Salva peers
        self._salvar_peers()

    def listar_peers(self) -> list:
        """Retorna lista de peers descobertos."""
        with self.peers_lock:
            return list(self.discovered_peers.keys())


# ============================================================
# TESTE ISOLADO
# ============================================================
if __name__ == "__main__":
    def on_peer(ip, port):
        print(f"🎯 Callback: novo peer {ip}:{port}")

    discovery = AutoNodeDiscovery(p2p_port=6001, on_peer_found=on_peer)
    discovery.run()

    try:
        while True:
            time.sleep(10)
            peers = discovery.listar_peers()
            print(f"[STATUS] Peers descobertos: {len(peers)}")
            for p in peers:
                print(f"  • {p}")
    except KeyboardInterrupt:
        print("\n🛑 Encerrando…")
        discovery.stop()
