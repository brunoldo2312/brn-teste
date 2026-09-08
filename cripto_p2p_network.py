import socket
import threading
import json
import requests
import time
import logging
from xml.etree import ElementTree

BOOTSTRAP_PEERS = ["localhost:6001"]  # para testes, adicione IPs reais

class AutoPortForwarder:
    @staticmethod
    def open_port_on_router(port, protocol='TCP'):
        """
        Tenta abrir uma porta via UPnP.
        """
        try:
            # Descobre o roteador via SSDP
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2)
            sock.sendto(b'M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\nST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n', ('239.255.255.250', 1900))
            data, addr = sock.recvfrom(1024)
            sock.close()

            # Extrai a URL de descrição
            for line in data.decode().split('\r\n'):
                if line.startswith('Location:'):
                    location = line.split(':', 1)[1].strip()
                    break
            else:
                return False

            # Baixa o XML de descrição
            resp = requests.get(location, timeout=5)
            root = ElementTree.fromstring(resp.content)
            # Encontra a URL de controle para WANIPConnection
            namespace = {'u': 'urn:schemas-upnp-org:service:WANIPConnection:1'}
            control_url = root.find('.//u:controlURL', namespace).text

            # Monta a requisição SOAP para adicionar port forwarding
            soap_body = f'''<?xml version="1.0"?>
            <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
              <s:Body>
                <u:AddPortMapping xmlns:u="urn:schemas-upnp-org:service:WANIPConnection:1">
                  <NewRemoteHost></NewRemoteHost>
                  <NewExternalPort>{port}</NewExternalPort>
                  <NewProtocol>{protocol}</NewProtocol>
                  <NewInternalPort>{port}</NewInternalPort>
                  <NewInternalClient>{socket.gethostbyname(socket.gethostname())}</NewInternalClient>
                  <NewEnabled>1</NewEnabled>
                  <NewPortMappingDescription>BRN Node</NewPortMappingDescription>
                  <NewLeaseDuration>0</NewLeaseDuration>
                </u:AddPortMapping>
              </s:Body>
            </s:Envelope>'''

            headers = {
                'Content-Type': 'text/xml; charset="utf-8"',
                'SOAPAction': '"urn:schemas-upnp-org:service:WANIPConnection:1#AddPortMapping"'
            }
            resp = requests.post(control_url, data=soap_body, headers=headers, timeout=5)
            return resp.status_code == 200
        except Exception as e:
            logging.error(f"Erro ao abrir porta: {e}")
            return False


class P2PNetwork:
    def __init__(self, port, api):
        self.port = port
        self.api = api
        self.peers = set()
        self.sock = None
        self.running = False

    def start_server(self):
        self.running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('0.0.0.0', self.port))
        self.sock.listen(5)
        logging.info(f"Servidor P2P ouvindo na porta {self.port}")

        # Tenta abrir a porta no roteador
        if AutoPortForwarder.open_port_on_router(self.port):
            logging.info("Porta aberta no roteador via UPnP")
        else:
            logging.warning("Não foi possível abrir a porta automaticamente.")

        # Conecta aos peers bootstrap
        for peer in BOOTSTRAP_PEERS:
            self.connect_to_peer(peer)

        while self.running:
            try:
                conn, addr = self.sock.accept()
                threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()
            except Exception as e:
                logging.error(f"Erro no accept: {e}")

    def connect_to_peer(self, peer_address):
        try:
            host, port = peer_address.split(':')
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((host, int(port)))
            self.peers.add(peer_address)
            threading.Thread(target=self.handle_client, args=(sock, None), daemon=True).start()
            logging.info(f"Conectado ao peer {peer_address}")
        except Exception as e:
            logging.error(f"Falha ao conectar a {peer_address}: {e}")

    def handle_client(self, conn, addr):
        while self.running:
            try:
                data = conn.recv(4096)
                if not data:
                    break
                request = json.loads(data.decode())
                self.process_request(conn, request)
            except Exception as e:
                logging.error(f"Erro no handler: {e}")
                break
        conn.close()

    def process_request(self, conn, request):
        cmd = request.get("command")
        if cmd == "GET_HEIGHT":
            chain = self.api.get_chain()
            response = {"height": len(chain)}
        elif cmd == "GET_CHAIN":
            start = request.get("start", 0)
            chain = self.api.get_chain()
            response = {"chain": chain[start:]}
        elif cmd == "BROADCAST_TX":
            tx = request.get("transaction")
            if tx:
                self.api.add_transaction(tx)
                self.broadcast_transaction(tx, exclude=conn)
            response = {"status": "OK"}
        elif cmd == "SYNC_CHAIN":
            # Verifica se a cadeia remota é mais longa
            remote_chain = request.get("chain", [])
            local_chain = self.api.get_chain()
            if len(remote_chain) > len(local_chain):
                self.api.db.replace_chain(remote_chain)
                response = {"status": "replaced"}
            else:
                response = {"status": "already_longer"}
        else:
            response = {"error": "comando desconhecido"}
        conn.send(json.dumps(response).encode())

    def broadcast_block(self, block):
        for peer in list(self.peers):
            try:
                host, port = peer.split(':')
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect((host, int(port)))
                request = {"command": "SYNC_CHAIN", "chain": self.api.get_chain()}
                sock.send(json.dumps(request).encode())
                sock.close()
            except Exception as e:
                logging.error(f"Erro ao broadcast para {peer}: {e}")

    def broadcast_transaction(self, tx, exclude=None):
        for peer in list(self.peers):
            if exclude and peer == exclude:
                continue
            try:
                host, port = peer.split(':')
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect((host, int(port)))
                request = {"command": "BROADCAST_TX", "transaction": tx}
                sock.send(json.dumps(request).encode())
                sock.close()
            except Exception as e:
                logging.error(f"Erro ao transmitir tx para {peer}: {e}")