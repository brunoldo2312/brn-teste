"""
cripto_p2p_network.py
Módulo de rede P2P da Moeda Bruno v2.

Funcionalidades:
- Descoberta do gateway local (IP da rede)
- Mapeamento automático de porta via UPnP (NAT traversal)
- Descoberta de peers na LAN via UDP broadcast
- Servidor TCP para receber conexões de outros nós
- Sincronização de blocos e transações (modelo UTXO + Merkle)
- Protocolo JSON com mensagens tipadas
"""

import socket
import threading
import json
import time
import os
import urllib.request
import xml.etree.ElementTree as ET

# ============================================================
# CONSTANTES
# ============================================================
P2P_DISCOVERY_PORT = 6010
P2P_BROADCAST_INTERVAL = 15
P2P_MAX_MESSAGE_SIZE = 2 * 1024 * 1024
P2P_SYNC_BATCH = 50
PROTOCOL_VERSION = "BRN2/1.0"
NETWORK_MAGIC = b"BRN2"


# ============================================================
# DESCOBERTA DE GATEWAY
# ============================================================
def discover_gateway():
    """Descobre o IP local e o IP do gateway (roteador)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        parts = local_ip.split(".")
        gateway_ip = ".".join(parts[:3] + ["1"])
        return local_ip, gateway_ip
    except Exception as e:
        print(f"[P2P] Não foi possível descobrir o gateway: {e}")
        return None, None


def get_broadcast_address():
    """Retorna o endereço de broadcast da rede local."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        parts = local_ip.split(".")
        return ".".join(parts[:3] + ["255"])
    except Exception:
        return "255.255.255.255"


# ============================================================
# UPnP (NAT Traversal)
# ============================================================
class UPnPClient:
    """Cliente UPnP minimalista para mapear portas no roteador."""

    def __init__(self):
        self.control_url = None
        self.service_type = "urn:schemas-upnp-org:service:WANIPConnection:1"
        self._discover()

    def _discover(self):
        ssdp_addr = ("239.255.255.250", 1900)
        msg = (
            "M-SEARCH * HTTP/1.1\r\n"
            "HOST: 239.255.255.250:1900\r\n"
            'MAN: "ssdp:discover"\r\n'
            "MX: 2\r\n"
            "ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n"
            "\r\n"
        ).encode()

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.settimeout(3)
        try:
            s.sendto(msg, ssdp_addr)
            while True:
                try:
                    data, addr = s.recvfrom(65507)
                    text = data.decode(errors="ignore")
                    location = self._extract_header(text, "LOCATION")
                    if location:
                        if self._fetch_control_url(location):
                            return True
                except socket.timeout:
                    break
        except Exception as e:
            print(f"[UPnP] Erro na descoberta: {e}")
        finally:
            s.close()
        return False

    @staticmethod
    def _extract_header(response, header):
        for line in response.split("\r\n"):
            if line.upper().startswith(header.upper() + ":"):
                return line.split(":", 1)[1].strip()
        return None

    def _fetch_control_url(self, location):
        try:
            with urllib.request.urlopen(location, timeout=5) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)
            for service in root.iter("{urn:schemas-upnp-org:device-1-0}service"):
                st = service.find("{urn:schemas-upnp-org:device-1-0}serviceType")
                cu = service.find("{urn:schemas-upnp-org:device-1-0}controlURL")
                if st is not None and cu is not None:
                    if "WANIPConnection" in st.text or "WANPPPConnection" in st.text:
                        base = location.rsplit("/", 1)[0]
                        self.service_type = st.text
                        self.control_url = base + cu.text if cu.text.startswith("/") else cu.text
                        return True
        except Exception as e:
            print(f"[UPnP] Erro ao processar XML: {e}")
        return False

    def add_port_mapping(self, external_port, internal_port, internal_ip,
                         description="BRN v2", protocol="TCP", duration=0):
        if not self.control_url:
            print("[UPnP] Sem control_url — mapeamento não é possível.")
            return False

        body = f"""<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:AddPortMapping xmlns:u="{self.service_type}">
      <NewRemoteHost></NewRemoteHost>
      <NewExternalPort>{external_port}</NewExternalPort>
      <NewProtocol>{protocol}</NewProtocol>
      <NewInternalPort>{internal_port}</NewInternalPort>
      <NewInternalClient>{internal_ip}</NewInternalClient>
      <NewEnabled>1</NewEnabled>
      <NewPortMappingDescription>{description}</NewPortMappingDescription>
      <NewLeaseDuration>{duration}</NewLeaseDuration>
    </u:AddPortMapping>
  </s:Body>
</s:Envelope>"""

        headers = {
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": f'"{self.service_type}#AddPortMapping"',
        }
        return self._soap_request(body, headers)

    def delete_port_mapping(self, external_port, protocol="TCP"):
        if not self.control_url:
            return False
        body = f"""<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:DeletePortMapping xmlns:u="{self.service_type}">
      <NewRemoteHost></NewRemoteHost>
      <NewExternalPort>{external_port}</NewExternalPort>
      <NewProtocol>{protocol}</NewProtocol>
    </u:DeletePortMapping>
  </s:Body>
</s:Envelope>"""
        headers = {
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": f'"{self.service_type}#DeletePortMapping"',
        }
        return self._soap_request(body, headers)

    def get_external_ip(self):
        if not self.control_url:
            return None
        body = f"""<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:GetExternalIPAddress xmlns:u="{self.service_type}">
    </u:GetExternalIPAddress>
  </s:Body>
</s:Envelope>"""
        headers = {
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": f'"{self.service_type}#GetExternalIPAddress"',
        }
        try:
            req = urllib.request.Request(self.control_url, data=body.encode(), headers=headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                xml_data = resp.read().decode(errors="ignore")
            root = ET.fromstring(xml_data)
            for elem in root.iter():
                if "ExternalIPAddress" in elem.tag:
                    return elem.text
        except Exception as e:
            print(f"[UPnP] Erro ao obter IP externo: {e}")
        return None

    def _soap_request(self, body, headers):
        try:
            req = urllib.request.Request(self.control_url, data=body.encode(), headers=headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception as e:
            print(f"[UPnP] Erro na requisição SOAP: {e}")
            return False


# ============================================================
# SERVIDOR P2P
# ============================================================
class P2PServer(threading.Thread):
    def __init__(self, blockchain, port, on_new_block=None, on_new_tx=None):
        super().__init__(daemon=True)
        self.bc = blockchain
        self.port = port
        self.on_new_block = on_new_block
        self.on_new_tx = on_new_tx
        self.running = True
        self.sock = None

    def run(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.sock.bind(("0.0.0.0", self.port))
            self.sock.listen(20)
            print(f"[P2P] Servidor TCP escutando na porta {self.port}")
        except Exception as e:
            print(f"[P2P] Erro ao abrir porta {self.port}: {e}")
            return

        while self.running:
            try:
                self.sock.settimeout(1.0)
                conn, addr = self.sock.accept()
                threading.Thread(target=self._handle_conn, args=(conn, addr),
                                 daemon=True).start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[P2P] Erro no accept: {e}")

    def stop(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass

    def _handle_conn(self, conn, addr):
        try:
            conn.settimeout(10)
            raw = conn.recv(P2P_MAX_MESSAGE_SIZE)
            if not raw:
                return
            if not raw.startswith(NETWORK_MAGIC):
                return
            msg = json.loads(raw[4:].decode())
            response = self._process_message(msg, addr)
            if response:
                conn.sendall(NETWORK_MAGIC + json.dumps(response).encode())
        except Exception as e:
            print(f"[P2P] Erro com {addr}: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _process_message(self, msg, addr):
        mtype = msg.get("type")
        if mtype == "ping":
            return {"type": "pong", "version": PROTOCOL_VERSION,
                    "height": self.bc.db.chain_height()}
        elif mtype == "get_chain_height":
            return {"type": "chain_height",
                    "height": self.bc.db.chain_height(),
                    "hash": (self.bc.db.get_last_block() or {}).get("hash", "")}
        elif mtype == "get_block":
            h = msg.get("height", 0)
            block = self.bc.db.get_block(h)
            return {"type": "block", "block": block}
        elif mtype == "get_blocks_range":
            start = msg.get("start", 0)
            end = msg.get("end", start + P2P_SYNC_BATCH)
            blocks = []
            for h in range(start, min(end, self.bc.db.chain_height() + 1)):
                b = self.bc.db.get_block(h)
                if b:
                    blocks.append(b)
            return {"type": "blocks_range", "blocks": blocks}
        elif mtype == "new_block":
            block_dict = msg.get("block")
            if block_dict and self.on_new_block:
                ok = self.on_new_block(block_dict)
                return {"type": "ack", "ok": ok}
            return {"type": "ack", "ok": False}
        elif mtype == "new_tx":
            tx_dict = msg.get("tx")
            if tx_dict and self.on_new_tx:
                ok = self.on_new_tx(tx_dict)
                return {"type": "ack", "ok": ok}
            return {"type": "ack", "ok": False}
        elif mtype == "get_mempool":
            return {"type": "mempool", "txs": self.bc.get_mempool()}
        return {"type": "error", "message": "Tipo desconhecido"}


# ============================================================
# DESCOBERTA DE PEERS NA LAN (UDP broadcast)
# ============================================================
class PeerDiscovery(threading.Thread):
    def __init__(self, port, node_id, blockchain=None):
        super().__init__(daemon=True)
        self.port = port
        self.node_id = node_id
        self.bc = blockchain
        self.running = True
        self.peers = {}
        self.lock = threading.Lock()
        self.on_peer_found = None

    def run(self):
        threading.Thread(target=self._listen, daemon=True).start()
        self._broadcast_loop()

    def stop(self):
        self.running = False

    def _listen(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("", P2P_DISCOVERY_PORT))
        except Exception as e:
            print(f"[P2P] Erro ao bindar porta {P2P_DISCOVERY_PORT}: {e}")
            return

        print(f"[P2P] Descoberta escutando na porta UDP {P2P_DISCOVERY_PORT}")
        while self.running:
            try:
                s.settimeout(1.0)
                data, addr = s.recvfrom(2048)
                if not data.startswith(NETWORK_MAGIC):
                    continue
                info = json.loads(data[4:].decode())
                if info.get("node_id") == self.node_id:
                    continue
                peer_ip = addr[0]
                with self.lock:
                    is_new = peer_ip not in self.peers
                    self.peers[peer_ip] = {
                        "last_seen": time.time(),
                        "port": info.get("port", self.port),
                        "height": info.get("height", -1),
                        "node_id": info.get("node_id"),
                    }
                if is_new:
                    print(f"[P2P] Novo peer descoberto: {peer_ip}:{info.get('port')}")
                    if self.on_peer_found:
                        self.on_peer_found(peer_ip, info.get("port", self.port))
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[P2P] Erro na escuta: {e}")
        s.close()

    def _broadcast_loop(self):
        while self.running:
            try:
                bc_height = self.bc.db.chain_height() if self.bc else -1
                payload = {
                    "node_id": self.node_id,
                    "port": self.port,
                    "height": bc_height,
                    "version": PROTOCOL_VERSION,
                    "ts": time.time(),
                }
                msg = NETWORK_MAGIC + json.dumps(payload).encode()
                broadcast_addr = get_broadcast_address()
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.sendto(msg, (broadcast_addr, P2P_DISCOVERY_PORT))
                s.close()
                self._cleanup_peers()
            except Exception as e:
                print(f"[P2P] Erro no broadcast: {e}")
            time.sleep(P2P_BROADCAST_INTERVAL)

    def _cleanup_peers(self):
        cutoff = time.time() - 60
        with self.lock:
            dead = [ip for ip, info in self.peers.items() if info["last_seen"] < cutoff]
            for ip in dead:
                del self.peers[ip]
                print(f"[P2P] Peer removido por inatividade: {ip}")

    def get_peers(self):
        with self.lock:
            return dict(self.peers)


# ============================================================
# CLIENTE P2P
# ============================================================
class P2PClient:
    @staticmethod
    def send_message(ip, port, message, timeout=5):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect((ip, port))
            payload = NETWORK_MAGIC + json.dumps(message).encode()
            s.sendall(payload)
            raw = s.recv(P2P_MAX_MESSAGE_SIZE)
            s.close()
            if raw.startswith(NETWORK_MAGIC):
                return json.loads(raw[4:].decode())
            return None
        except Exception as e:
            print(f"[P2P] Erro ao enviar para {ip}:{port}: {e}")
            return None

    @staticmethod
    def ping(ip, port):
        return P2PClient.send_message(ip, port, {"type": "ping"})

    @staticmethod
    def get_chain_height(ip, port):
        return P2PClient.send_message(ip, port, {"type": "get_chain_height"})

    @staticmethod
    def get_block(ip, port, height):
        return P2PClient.send_message(ip, port, {"type": "get_block", "height": height})

    @staticmethod
    def get_blocks_range(ip, port, start, end):
        return P2PClient.send_message(ip, port,
                                      {"type": "get_blocks_range", "start": start, "end": end})

    @staticmethod
    def send_block(ip, port, block):
        return P2PClient.send_message(ip, port, {"type": "new_block", "block": block})

    @staticmethod
    def send_tx(ip, port, tx):
        return P2PClient.send_message(ip, port, {"type": "new_tx", "tx": tx})

    @staticmethod
    def get_mempool(ip, port):
        return P2PClient.send_message(ip, port, {"type": "get_mempool"})


# ============================================================
# GERENCIADOR P2P
# ============================================================
class P2PManager:
    def __init__(self, blockchain, port, enable_upnp=True):
        self.bc = blockchain
        self.port = port
        self.node_id = os.urandom(8).hex()
        self.enable_upnp = enable_upnp

        self.upnp = None
        self.external_ip = None
        if enable_upnp:
            threading.Thread(target=self._setup_upnp, daemon=True).start()

        self.server = P2PServer(blockchain, port,
                                on_new_block=self._on_new_block,
                                on_new_tx=self._on_new_tx)
        self.discovery = PeerDiscovery(port, self.node_id, blockchain)
        self.discovery.on_peer_found = self._on_peer_found

    def start(self):
        self.server.start()
        self.discovery.start()
        print(f"[P2P] Manager iniciado (node_id={self.node_id[:8]})")

    def stop(self):
        self.server.stop()
        self.discovery.stop()
        if self.upnp and self.external_ip:
            try:
                self.upnp.delete_port_mapping(self.port, "TCP")
            except Exception:
                pass

    def _setup_upnp(self):
        try:
            print("[UPnP] Descobrindo roteador...")
            self.upnp = UPnPClient()
            if not self.upnp.control_url:
                print("[UPnP] Roteador não suporta UPnP ou está desabilitado.")
                return
            local_ip, _ = discover_gateway()
            if not local_ip:
                return
            ok = self.upnp.add_port_mapping(self.port, self.port, local_ip,
                                            description="BRN v2 Node")
            if ok:
                self.external_ip = self.upnp.get_external_ip()
                print(f"[UPnP] Porta {self.port} mapeada. IP externo: {self.external_ip}")
            else:
                print("[UPnP] Falha ao mapear porta. Pode ser necessário liberar manualmente.")
        except Exception as e:
            print(f"[UPnP] Erro: {e}")

    def _on_peer_found(self, ip, port):
        try:
            resp = P2PClient.get_chain_height(ip, port)
            if resp and resp.get("height", -1) > self.bc.db.chain_height():
                print(f"[P2P] Sincronizando com {ip}:{port} "
                      f"({resp['height']} > {self.bc.db.chain_height()})")
                self.sync_with_peer(ip, port)
        except Exception as e:
            print(f"[P2P] Erro ao sincronizar com {ip}: {e}")

    def sync_with_peer(self, ip, port):
        remote_height = None
        resp = P2PClient.get_chain_height(ip, port)
        if resp:
            remote_height = resp.get("height", -1)
        if remote_height is None or remote_height <= self.bc.db.chain_height():
            return

        start = self.bc.db.chain_height() + 1
        while start <= remote_height:
            end = min(start + P2P_SYNC_BATCH, remote_height + 1)
            resp = P2PClient.get_blocks_range(ip, port, start, end)
            if not resp or "blocks" not in resp:
                break
            for block_dict in resp["blocks"]:
                if block_dict and block_dict.get("height", -1) > self.bc.db.chain_height():
                    try:
                        self.bc.db.save_block(block_dict)
                    except Exception as e:
                        print(f"[P2P] Erro ao salvar bloco {block_dict.get('height')}: {e}")
            start = end
        print(f"[P2P] Sincronização concluída. Altura local: {self.bc.db.chain_height()}")

    def broadcast_block(self, block_dict):
        peers = self.discovery.get_peers()
        for ip, info in peers.items():
            threading.Thread(
                target=P2PClient.send_block,
                args=(ip, info["port"], block_dict),
                daemon=True
            ).start()

    def broadcast_tx(self, tx_dict):
        peers = self.discovery.get_peers()
        for ip, info in peers.items():
            threading.Thread(
                target=P2PClient.send_tx,
                args=(ip, info["port"], tx_dict),
                daemon=True
            ).start()

    def _on_new_block(self, block_dict):
        try:
            h = block_dict.get("height", -1)
            if h > self.bc.db.chain_height():
                self.bc.db.save_block(block_dict)
                print(f"[P2P] Novo bloco recebido: #{h}")
                return True
        except Exception as e:
            print(f"[P2P] Erro ao processar bloco: {e}")
        return False

    def _on_new_tx(self, tx_dict):
        try:
            from bruno_blockchain_v2 import Transaction
            tx = Transaction.from_dict(tx_dict)
            ok, msg = self.bc.submit_transaction(tx)
            if ok:
                print(f"[P2P] Nova transação recebida: {tx.txid[:16]}...")
            return ok
        except Exception as e:
            print(f"[P2P] Erro ao processar tx: {e}")
            return False

    def get_status(self):
        return {
            "node_id": self.node_id,
            "port": self.port,
            "external_ip": self.external_ip,
            "peers": self.discovery.get_peers(),
            "peer_count": len(self.discovery.get_peers()),
            "height": self.bc.db.chain_height(),
        }