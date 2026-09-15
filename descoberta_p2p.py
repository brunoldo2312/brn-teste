import socket
import threading
import time

MULTICAST_GROUP = '239.255.255.250'  # Endereço padrão de descoberta local
MULTICAST_PORT = 50007                # Porta exclusiva para o eco de busca


class AutoNodeDiscovery:
    def __init__(self, p2p_port=7777):
        self.p2p_port = p2p_port
        self.discovered_peers = set()
        self.running = True

    def _get_local_ip(self):
        """Descobre o IP real deste computador na rede local."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
        except Exception:
            ip = '127.0.0.1'
        finally:
            s.close()
        return ip

    def start_server(self):
        """Escuta os chamados de broadcast de outros computadores."""
        local_ip = self._get_local_ip()
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # Vincula à porta de multicast
        server_socket.bind(('', MULTICAST_PORT))
        
        # Configura o socket para escutar multicast
        mreq = socket.inet_aton(MULTICAST_GROUP) + socket.inet_aton('0.0.0.0')
        server_socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        
        print(f"📡 Buscador Automático Ativo! Seu IP local é: {local_ip}")
        
        while self.running:
            try:
                server_socket.settimeout(2.0)
                data, addr = server_socket.recvfrom(1024)
                msg = data.decode('utf-8')
                
                if msg.startswith("BRN_NODE_PING:"):
                    remote_p2p_port = msg.split(":")[1]
                    remote_ip = addr[0]
                    
                    # Evita conectar a si mesmo
                    if remote_ip != local_ip:
                        peer_address = f"{remote_ip}:{remote_p2p_port}"
                        if peer_address not in self.discovered_peers:
                            self.discovered_peers.add(peer_address)
                            print(f"✨ [Descoberta] Outro computador encontrado automaticamente: {peer_address}")
                            
                            # Envia uma resposta direta de confirmação
                            response_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                            response_sock.sendto(f"BRN_NODE_PONG:{self.p2p_port}".encode('utf-8'), addr)
                            response_sock.close()
                            
                elif msg.startswith("BRN_NODE_PONG:"):
                    remote_p2p_port = msg.split(":")[1]
                    remote_ip = addr[0]
                    peer_address = f"{remote_ip}:{remote_p2p_port}"
                    if peer_address not in self.discovered_peers:
                        self.discovered_peers.add(peer_address)
                        print(f"🤝 [Descoberta] Conexão mútua estabelecida com: {peer_address}")
                        
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Erro no servidor de descoberta: {e}")

    def start_client_broadcast(self):
        """Dispara um sinal na rede a cada 5 segundos avisando que está online."""
        local_ip = self._get_local_ip()
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        client_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        
        print("🚀 Disparando eco de rede para localizar outros micros...")
        while self.running:
            try:
                msg = f"BRN_NODE_PING:{self.p2p_port}"
                client_socket.sendto(msg.encode('utf-8'), (MULTICAST_GROUP, MULTICAST_PORT))
                time.sleep(5)
            except Exception as e:
                print(f"Erro ao transmitir broadcast: {e}")
                time.sleep(5)

    def run(self):
        # Inicia a escuta e a transmissão em paralelo (threads)
        t1 = threading.Thread(target=self.start_server, daemon=True)
        t2 = threading.Thread(target=self.start_client_broadcast, daemon=True)
        t1.start()
        t2.start()


if __name__ == "__main__":
    # Teste isolado do buscador automático
    discovery = AutoNodeDiscovery(p2p_port=7777)
    discovery.run()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        discovery.running = False
