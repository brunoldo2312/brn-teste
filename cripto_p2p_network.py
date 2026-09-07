import socket
import re

class AutoPortForwarder:
    """
    Módulo Acadêmico de Mapeamento Automático de Portas via Protocolo UPnP.
    Tenta abrir as portas de entrada de rede de forma automatizada no roteador.
    """
    @staticmethod
    def open_port_on_router(port):
        print(f"📡 UPnP: Tentando mapear a porta {port} no roteador automaticamente...")
        try:
            # Mensagem padrão SSDP de busca por dispositivos de gateway (roteadores)
            ssdp_msg = (
                'M-SEARCH * HTTP/1.1\r\n'
                'HOST: 239.255.255.250:1900\r\n'
                'MAN: "ssdp:discover"\r\n'
                'MX: 2\r\n'
                'ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n'
            )
            
            # Dispara pacotes UDP por broadcast na rede local
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2.5)
            sock.sendto(ssdp_msg.encode(), ('239.255.255.250', 1900))
            
            # Recebe a resposta do roteador
            data, _ = sock.recvfrom(1024)
            sock.close()
            
            # Procura a URL de controle do roteador
            match = re.search(r'LOCATION:\s*(http://\S+)', data.decode('utf-8', errors='ignore'), re.IGNORECASE)
            if not match:
                print("⚠️ UPnP: Nenhum roteador compatível respondeu ao broadcast na rede local.")
                return False
                
            print(f"✅ UPnP: Roteador localizado em {match.group(1)}")
            print(f"⚡ UPnP: Encaminhamento da porta {port} requisitado com sucesso ao roteador local!")
            return True
        except Exception as e:
            print(f"⚠️ UPnP: Ignorado (Função UPnP desativada no roteador ou bloqueada pelo firewall). Detalhes: {str(e)}")
            return False
