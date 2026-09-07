import hashlib
import time
import json
import sqlite3
import secrets
import socket
import threading
import sys
import logging
import hmac
import ipaddress
from datetime import datetime, timedelta
from collections import defaultdict
from functools import wraps
import webview
from cripto_wallet import WalletManager
from cripto_db import BlockchainDB
from cripto_p2p_network import AutoPortForwarder

# ============================================================================
# CONFIGURAÇÕES DE SEGURANÇA
# ============================================================================
COIN_NAME = "Bruno"
COIN_SYMBOL = "BRN"
BLOCK_REWARD = 50.0
DIFFICULTY_ADJUSTMENT_INTERVAL = 5
TARGET_BLOCK_TIME = 10.0
MONERO_FORK_NETWORK_ID = [0xAA, 0xBB, 0xCC, 0xDD, 0x11, 0x22, 0x33, 0x44]

# Segurança de Rede
BOOTSTRAP_PEERS = [
    ("192.168.0.17", 6001)
]
MAX_PEER_CONNECTIONS = 50
MAX_MESSAGE_SIZE = 50 * 1024 * 1024  # 50MB
SOCKET_TIMEOUT = 10.0
MAX_RECONNECT_ATTEMPTS = 3
PEER_BLACKLIST_DURATION = 3600  # 1 hora

# Rate Limiting e DDoS Protection
RATE_LIMIT_REQUESTS_PER_MINUTE = 100
RATE_LIMIT_TX_PER_MINUTE_PER_IP = 50
RATE_LIMIT_BLOCKS_PER_HOUR = 1000
MAX_TRANSACTIONS_PER_BLOCK = 500
MAX_MEMPOOL_SIZE = 10000
MIN_TX_FEE = 0.0001

# Configurações de Logging
LOG_FILE = "blockchain_security.log"
LOG_LEVEL = logging.INFO

# ============================================================================
# SETUP DE LOGGING E AUDITORIA
# ============================================================================
def setup_logger():
    """Configura logging com segurança e auditoria"""
    logger = logging.getLogger("BlockchainSecurity")
    logger.setLevel(LOG_LEVEL)
    
    # Handler para arquivo com rotação
    from logging.handlers import RotatingFileHandler
    fh = RotatingFileHandler(LOG_FILE, maxBytes=10*1024*1024, backupCount=5)
    fh.setLevel(LOG_LEVEL)
    
    # Formato detalhado com timestamp
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s'
    )
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    
    return logger

logger = setup_logger()

# ============================================================================
# DECORADORES DE SEGURANÇA
# ============================================================================
def rate_limit(max_calls_per_minute=100):
    """Decorator para rate limiting"""
    def decorator(func):
        call_times = defaultdict(list)
        
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            now = time.time()
            ip_or_id = kwargs.get('ip', 'local')
            
            # Limpa chamadas antigas
            call_times[ip_or_id] = [t for t in call_times[ip_or_id] 
                                     if t > now - 60]
            
            if len(call_times[ip_or_id]) >= max_calls_per_minute:
                logger.warning(f"Rate limit excedido para {ip_or_id}: {func.__name__}")
                raise Exception(f"Rate limit excedido. Máximo {max_calls_per_minute} chamadas/minuto")
            
            call_times[ip_or_id].append(now)
            return func(self, *args, **kwargs)
        
        return wrapper
    return decorator

def secure_operation(func):
    """Decorator para operações seguras com logging"""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            logger.debug(f"Iniciando operação segura: {func.__name__}")
            result = func(self, *args, **kwargs)
            logger.debug(f"Operação concluída: {func.__name__}")
            return result
        except Exception as e:
            logger.error(f"Erro em operação segura {func.__name__}: {str(e)}", exc_info=True)
            raise
    
    return wrapper

# ============================================================================
# VALIDADORES E VERIFICADORES DE SEGURANÇA
# ============================================================================
class SecurityValidator:
    """Classe centralizada para validações de segurança"""
    
    @staticmethod
    def validate_ip_address(ip_str):
        """Valida e sanitiza endereço IP"""
        try:
            ipaddress.ip_address(ip_str)
            return True
        except ValueError:
            logger.warning(f"IP inválido detectado: {ip_str}")
            return False
    
    @staticmethod
    def validate_protocol_message(data):
        """Valida estrutura de mensagem do protocolo"""
        if not isinstance(data, str):
            return False, "Mensagem não é string"
        
        if len(data) > MAX_MESSAGE_SIZE:
            return False, f"Mensagem excede limite de {MAX_MESSAGE_SIZE} bytes"
        
        if not data or len(data) < 3:
            return False, "Mensagem muito curta"
        
        return True, "OK"
    
    @staticmethod
    def is_private_network(ip_str):
        """Verifica se IP é de rede privada"""
        try:
            ip = ipaddress.ip_address(ip_str)
            return ip.is_private
        except:
            return False
    
    @staticmethod
    def calculate_hmac_signature(data, secret_key):
        """Calcula assinatura HMAC para autenticação"""
        return hmac.new(
            secret_key.encode('utf-8'),
            data.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    @staticmethod
    def verify_hmac_signature(data, signature, secret_key):
        """Verifica assinatura HMAC"""
        expected = SecurityValidator.calculate_hmac_signature(data, secret_key)
        return hmac.compare_digest(expected, signature)

# ============================================================================
# GERENCIADOR DE LISTA NEGRA DE PARES
# ============================================================================
class PeerBlacklistManager:
    """Gerencia lista negra de pares maliciosos"""
    
    def __init__(self):
        self.blacklist = {}  # {ip: (timestamp, razao)}
        self.lock = threading.Lock()
    
    def add_to_blacklist(self, ip, reason="Comportamento suspeito"):
        """Adiciona IP à lista negra"""
        with self.lock:
            self.blacklist[ip] = (time.time(), reason)
            logger.warning(f"IP adicionado à lista negra: {ip} - Razão: {reason}")
    
    def is_blacklisted(self, ip):
        """Verifica se IP está na lista negra"""
        with self.lock:
            if ip not in self.blacklist:
                return False
            
            timestamp, reason = self.blacklist[ip]
            # Remove da blacklist após PEER_BLACKLIST_DURATION
            if time.time() - timestamp > PEER_BLACKLIST_DURATION:
                del self.blacklist[ip]
                logger.info(f"IP removido da lista negra (expirado): {ip}")
                return False
            
            return True
    
    def get_blacklist_reason(self, ip):
        """Retorna razão da blacklist"""
        with self.lock:
            if ip in self.blacklist:
                return self.blacklist[ip][1]
            return None

# ============================================================================
# CLASSE DE BLOCO SEGURO
# ============================================================================
class BrunoBlock:
    def __init__(self, index, previous_hash, transactions, difficulty=4, 
                 nonce=0, timestamp=None, block_hash=None):
        self.index = int(index)
        self.timestamp = float(timestamp) if timestamp else time.time()
        self.previous_hash = str(previous_hash)
        
        # Validação de transações
        if isinstance(transactions, str):
            try:
                self.transactions = json.loads(transactions)
            except json.JSONDecodeError:
                logger.error(f"Erro ao parsear transações no bloco {index}")
                raise ValueError("Transações JSON inválidas")
        else:
            self.transactions = transactions
        
        # Limite de transações por bloco
        if len(self.transactions) > MAX_TRANSACTIONS_PER_BLOCK:
            logger.error(f"Bloco {index} excede limite de transações")
            raise ValueError(f"Máximo {MAX_TRANSACTIONS_PER_BLOCK} transações por bloco")
        
        self.difficulty = int(difficulty)
        self.nonce = int(nonce)
        self.network_id = MONERO_FORK_NETWORK_ID
        self.hash = str(block_hash) if block_hash else self.calculate_hash()

    def calculate_hash(self) -> str:
        """Calcula hash do bloco com proteção contra modificação"""
        block_data = {
            "index": self.index,
            "timestamp": self.timestamp,
            "previous_hash": self.previous_hash,
            "transactions": self.transactions,
            "difficulty": self.difficulty,
            "nonce": self.nonce,
            "network_id": self.network_id
        }
        
        block_string = json.dumps(block_data, sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()

    def mine_block(self, stop_event=None):
        """Mineração com segurança contra interrupções"""
        target = "0" * self.difficulty
        max_iterations = 2**32  # Limite de iterações
        iteration = 0
        
        while self.hash[:self.difficulty] != target and iteration < max_iterations:
            if stop_event and stop_event.is_set():
                logger.info(f"Mineração do bloco {self.index} interrompida")
                return False
            
            self.nonce += 1
            self.hash = self.calculate_hash()
            iteration += 1
        
        if iteration >= max_iterations:
            logger.error(f"Bloco {self.index} atingiu limite de iterações")
            return False
        
        logger.info(f"Bloco {self.index} minerado com sucesso em {iteration} iterações")
        return True

    def to_dict(self):
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "previous_hash": self.previous_hash,
            "transactions": self.transactions,
            "difficulty": self.difficulty,
            "nonce": self.nonce,
            "hash": self.hash
        }

# ============================================================================
# API CRIPTOGRÁFICA SEGURA
# ============================================================================
class CriptoAPI:
    def __init__(self, node_port):
        self.p2p_port = node_port
        self.db_path = f"blockchain_node_{node_port}.db"
        self.db = BlockchainDB(self.db_path)
        self.mempool = []
        self.mempool_lock = threading.Lock()
        self.connected_peers = set()
        
        # Segurança
        self.peer_blacklist = PeerBlacklistManager()
        self.peer_connection_count = defaultdict(int)
        self.last_request_time = defaultdict(float)
        self.tx_per_ip = defaultdict(list)
        
        # Controle de Mineração
        self.is_mining = False
        self.mining_stop_event = threading.Event()
        self.miner_thread = None
        
        # Auditoria
        self.audit_log = []
        self.audit_lock = threading.Lock()
        
        logger.info(f"🔐 Inicializando nó na porta {self.p2p_port}")
        self._init_database()
        
        self.server_thread = threading.Thread(
            target=self._start_p2p_server, 
            daemon=True,
            name="P2P-Server"
        )
        self.server_thread.start()
        
        threading.Thread(
            target=self._run_bootstrap_discovery, 
            daemon=True,
            name="Bootstrap-Discovery"
        ).start()
    
    def _log_audit(self, event_type, ip, message, status="INFO"):
        """Registra evento de auditoria"""
        with self.audit_lock:
            audit_entry = {
                "timestamp": datetime.now().isoformat(),
                "type": event_type,
                "ip": ip,
                "message": message,
                "status": status
            }
            self.audit_log.append(audit_entry)
            logger.log(
                logging.WARNING if status == "ALERT" else logging.INFO,
                f"[AUDIT] {event_type} - {ip} - {message}"
            )
    
    def _init_database(self):
        """Inicializa banco de dados com integridade"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging
                conn.execute("PRAGMA synchronous=FULL")  # Sincronização completa
                
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS blocks (
                        id_index INTEGER PRIMARY KEY,
                        timestamp REAL NOT NULL,
                        previous_hash TEXT NOT NULL,
                        transactions TEXT NOT NULL,
                        difficulty INTEGER NOT NULL,
                        nonce INTEGER NOT NULL,
                        hash TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Criar índices para performance
                cursor.execute(
                    'CREATE INDEX IF NOT EXISTS idx_hash ON blocks(hash)'
                )
                cursor.execute(
                    'CREATE INDEX IF NOT EXISTS idx_previous_hash ON blocks(previous_hash)'
                )
                
                cursor.execute('SELECT COUNT(*) FROM blocks')
                if cursor.fetchone()[0] == 0:
                    genesis = BrunoBlock(
                        0, "0",
                        [{"sender": "SISTEMA", "receiver": "brn1111cd943fa71e1f91dcd62f52fc6138bc845ab", 
                          "amount": 100000.0}],
                        difficulty=4
                    )
                    genesis.mine_block()
                    self.db.insert_block(genesis)
                    logger.info("✅ Bloco genesis criado com sucesso")
                
                conn.commit()
        except Exception as e:
            logger.critical(f"Erro ao inicializar banco de dados: {e}", exc_info=True)
            raise

    def get_p2p_port(self):
        return self.p2p_port

    def _calculate_next_difficulty(self) -> int:
        """Ajuste dinâmico de dificuldade com segurança"""
        try:
            chain = self.db.get_raw_chain()
            if len(chain) < DIFFICULTY_ADJUSTMENT_INTERVAL + 1:
                return chain[-1]["difficulty"] if chain else 4
            
            latest_block = chain[-1]
            if latest_block["index"] % DIFFICULTY_ADJUSTMENT_INTERVAL != 0:
                return latest_block["difficulty"]
            
            prev_adjustment_block = chain[-DIFFICULTY_ADJUSTMENT_INTERVAL]
            time_expected = TARGET_BLOCK_TIME * DIFFICULTY_ADJUSTMENT_INTERVAL
            time_taken = latest_block["timestamp"] - prev_adjustment_block["timestamp"]
            
            # Proteção contra manipulação de dificuldade
            if time_taken <= 0:
                logger.warning("Tempo negativo detectado no ajuste de dificuldade")
                return latest_block["difficulty"]
            
            current_diff = latest_block["difficulty"]
            
            if time_taken < (time_expected / 2):
                new_diff = min(current_diff + 1, 32)  # Limite máximo
            elif time_taken > (time_expected * 2):
                new_diff = max(1, current_diff - 1)
            else:
                new_diff = current_diff
            
            logger.info(f"Dificuldade ajustada: {current_diff} → {new_diff} "
                       f"(tempo: {time_taken:.2f}s, esperado: {time_expected:.2f}s)")
            return new_diff
        
        except Exception as e:
            logger.error(f"Erro no cálculo de dificuldade: {e}")
            return 4

    def _receive_all(self, sock, buffer_size=4096):
        """Recebe dados com proteção contra ataques de buffer"""
        data = b""
        total_received = 0
        
        try:
            while total_received < MAX_MESSAGE_SIZE:
                chunk = sock.recv(min(buffer_size, MAX_MESSAGE_SIZE - total_received))
                if not chunk:
                    break
                
                data += chunk
                total_received += len(chunk)
                
                if total_received > MAX_MESSAGE_SIZE:
                    logger.warning(f"Mensagem excede tamanho máximo: {total_received} bytes")
                    raise ValueError(f"Mensagem excede {MAX_MESSAGE_SIZE} bytes")
        
        except socket.timeout:
            pass
        except Exception as e:
            logger.error(f"Erro ao receber dados: {e}")
        
        return data.decode('utf-8', errors='ignore')

    @secure_operation
    def _start_p2p_server(self):
        """Servidor P2P seguro com proteção contra ataques"""
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # Proteção contra SYN flood
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        
        try:
            server_socket.bind(('0.0.0.0', self.p2p_port))
            server_socket.listen(20)
            logger.info(f"🔐 Servidor P2P iniciado na porta {self.p2p_port}")
            
            while True:
                try:
                    client_conn, client_addr = server_socket.accept()
                    client_ip = client_addr[0]
                    
                    # Validações de segurança
                    if not SecurityValidator.validate_ip_address(client_ip):
                        logger.warning(f"IP inválido rejeitado: {client_ip}")
                        client_conn.close()
                        continue
                    
                    if self.peer_blacklist.is_blacklisted(client_ip):
                        logger.warning(f"Conexão bloqueada de IP na blacklist: {client_ip}")
                        self._log_audit("CONNECTION_REJECTED", client_ip, "IP blacklisted", "ALERT")
                        client_conn.close()
                        continue
                    
                    # Rate limiting por IP
                    now = time.time()
                    if self.last_request_time[client_ip] > 0:
                        time_diff = now - self.last_request_time[client_ip]
                        if time_diff < (60 / RATE_LIMIT_REQUESTS_PER_MINUTE):
                            logger.debug(f"Rate limit aplicado a {client_ip}")
                            client_conn.close()
                            continue
                    
                    self.last_request_time[client_ip] = now
                    
                    # Limite de conexões simultâneas por IP
                    self.peer_connection_count[client_ip] += 1
                    if self.peer_connection_count[client_ip] > 5:
                        logger.warning(f"Muitas conexões de {client_ip}")
                        self.peer_blacklist.add_to_blacklist(client_ip, "Muitas conexões simultâneas")
                        client_conn.close()
                        self.peer_connection_count[client_ip] -= 1
                        continue
                    
                    client_conn.settimeout(SOCKET_TIMEOUT)
                    
                    # Processa conexão em thread separada
                    threading.Thread(
                        target=self._handle_peer_connection,
                        args=(client_conn, client_ip),
                        daemon=True
                    ).start()
                
                except Exception as e:
                    logger.error(f"Erro ao aceitar conexão: {e}")
        
        finally:
            server_socket.close()

    def _handle_peer_connection(self, client_conn, client_ip):
        """Manipula conexão de par com segurança"""
        try:
            data = self._receive_all(client_conn)
            
            # Validação de protocolo
            is_valid, msg = SecurityValidator.validate_protocol_message(data)
            if not is_valid:
                logger.warning(f"Mensagem inválida de {client_ip}: {msg}")
                self._log_audit("INVALID_MESSAGE", client_ip, msg, "ALERT")
                return
            
            # Logging de auditoria
            self._log_audit("CONNECTION_RECEIVED", client_ip, f"Mensagem: {data[:50]}...")
            
            # Processa diferentes tipos de mensagem
            if data == "GET_HEIGHT":
                response = str(len(self.db.get_raw_chain())).encode('utf-8')
                client_conn.sendall(response)
            
            elif data == "GET_CHAIN":
                chain = self.db.get_raw_chain()
                response = json.dumps(chain).encode('utf-8')
                client_conn.sendall(response)
            
            elif data.startswith("BROADCAST_TX:"):
                self._handle_broadcast_tx(data, client_ip)
            
            elif data.startswith("SYNC_CHAIN:"):
                self._handle_sync_chain(data, client_ip)
            
            else:
                logger.warning(f"Comando desconhecido de {client_ip}: {data[:50]}")
                self._log_audit("UNKNOWN_COMMAND", client_ip, data[:50], "ALERT")
            
            # Adiciona à lista de pares conhecidos
            if client_ip != "127.0.0.1" and not SecurityValidator.is_private_network(client_ip):
                self.connected_peers.add((client_ip, self.p2p_port))
        
        except Exception as e:
            logger.error(f"Erro ao processar conexão de {client_ip}: {e}")
            self._log_audit("CONNECTION_ERROR", client_ip, str(e), "ALERT")
        
        finally:
            self.peer_connection_count[client_ip] -= 1
            client_conn.close()

    def _handle_broadcast_tx(self, data, client_ip):
        """Manipula broadcast de transação com validação"""
        try:
            tx_json = data.split(":", 1)[1]
            tx_data = json.loads(tx_json)
            
            # Rate limiting de transações por IP
            now = time.time()
            self.tx_per_ip[client_ip] = [t for t in self.tx_per_ip[client_ip] 
                                          if t > now - 60]
            
            if len(self.tx_per_ip[client_ip]) >= RATE_LIMIT_TX_PER_MINUTE_PER_IP:
                logger.warning(f"Rate limit TX excedido para {client_ip}")
                self._log_audit("TX_RATE_LIMIT", client_ip, "Limite excedido", "ALERT")
                return
            
            self.tx_per_ip[client_ip].append(now)
            
            # Validação da transação
            if not self._verify_tx_structure(tx_data):
                logger.warning(f"Transação inválida de {client_ip}")
                self._log_audit("INVALID_TX", client_ip, str(tx_data)[:100], "ALERT")
                return
            
            # Verifica tamanho da mempool
            with self.mempool_lock:
                if len(self.mempool) >= MAX_MEMPOOL_SIZE:
                    logger.warning(f"Mempool cheia, rejeitando TX de {client_ip}")
                    return
                
                if tx_data not in self.mempool:
                    self.mempool.append(tx_data)
                    logger.debug(f"Transação adicionada à mempool: {str(tx_data)[:50]}...")
            
            self._log_audit("TX_ACCEPTED", client_ip, str(tx_data)[:100])
        
        except json.JSONDecodeError:
            logger.warning(f"JSON inválido em broadcast TX de {client_ip}")
            self._log_audit("INVALID_JSON", client_ip, data[:100], "ALERT")
        except Exception as e:
            logger.error(f"Erro ao processar broadcast TX: {e}")

    def _handle_sync_chain(self, data, client_ip):
        """Manipula sincronização de cadeia com validação"""
        try:
            chain_json = data.split(":", 1)[1]
            incoming_chain = json.loads(chain_json)
            
            if not isinstance(incoming_chain, list):
                logger.warning(f"Cadeia inválida de {client_ip}")
                self._log_audit("INVALID_CHAIN", client_ip, "Não é lista", "ALERT")
                return
            
            logger.info(f"Cadeia recebida de {client_ip} com {len(incoming_chain)} blocos")
            result = self._resolve_consensus(incoming_chain, client_ip)
            logger.info(f"Resultado da sincronização: {result}")
        
        except json.JSONDecodeError:
            logger.warning(f"JSON inválido em sync chain de {client_ip}")
            self._log_audit("INVALID_JSON_CHAIN", client_ip, data[:100], "ALERT")
        except Exception as e:
            logger.error(f"Erro ao processar sync chain: {e}")

    def _run_bootstrap_discovery(self):
        """Descoberta de bootstrap com retry seguro"""
        time.sleep(2)
        for ip, port in BOOTSTRAP_PEERS:
            if port != self.p2p_port:
                for attempt in range(MAX_RECONNECT_ATTEMPTS):
                    try:
                        logger.info(f"Tentativa {attempt+1}/{MAX_RECONNECT_ATTEMPTS} "
                                   f"de conectar a {ip}:{port}")
                        self.connect_and_sync(ip, port)
                        break
                    except Exception as e:
                        logger.warning(f"Bootstrap falhou (tentativa {attempt+1}): {e}")
                        if attempt < MAX_RECONNECT_ATTEMPTS - 1:
                            time.sleep(2 ** attempt)  # Backoff exponencial

    def _broadcast_transaction_to_network(self, tx):
        """Broadcast de transação com tratamento de erros"""
        broadcast_count = 0
        for ip, port in list(self.connected_peers):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2.0)
                s.connect((ip, int(port)))
                s.sendall(f"BROADCAST_TX:{json.dumps(tx)}".encode('utf-8'))
                s.close()
                broadcast_count += 1
            except Exception as e:
                logger.debug(f"Erro ao fazer broadcast para {ip}:{port}: {e}")
                self.connected_peers.discard((ip, port))
        
        logger.info(f"Transação propagada para {broadcast_count} pares")

    def connect_and_sync(self, ip, port):
        """Conexão e sincronização segura"""
        if not SecurityValidator.validate_ip_address(ip):
            return {"status": "erro", "message": "IP inválido"}
        
        try:
            # Obtém altura
            s_height = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s_height.settimeout(SOCKET_TIMEOUT)
            s_height.connect((ip, int(port)))
            s_height.sendall("GET_HEIGHT".encode('utf-8'))
            remote_height = int(s_height.recv(1024).decode('utf-8'))
            s_height.close()
            
            local_height = len(self.db.get_raw_chain())
            
            if remote_height <= local_height:
                logger.info(f"Blockchain local está atualizada (local: {local_height}, "
                           f"remoto: {remote_height})")
                return {"status": "sucesso", "message": "Sua blockchain ja esta atualizada."}
            
            logger.info(f"Sincronizando: local={local_height}, remoto={remote_height}")
            
            # Obtém cadeia
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(SOCKET_TIMEOUT)
            client_socket.connect((ip, int(port)))
            client_socket.sendall("GET_CHAIN".encode('utf-8'))
            response = self._receive_all(client_socket)
            client_socket.close()
            
            incoming_chain = json.loads(response)
            self.connected_peers.add((ip, int(port)))
            
            result = self._resolve_consensus(incoming_chain, ip)
            return {"status": "sucesso", "message": result}
        
        except json.JSONDecodeError:
            logger.error(f"JSON inválido ao sincronizar com {ip}")
            return {"status": "erro", "message": "Resposta JSON inválida"}
        except Exception as e:
            logger.error(f"Erro ao sincronizar com {ip}:{port}: {e}")
            return {"status": "erro", "message": str(e)}

    def _validate_address(self, address):
        """Validação de endereço com segurança"""
        if not isinstance(address, str):
            raise ValueError("Endereço deve ser string")
        
        if not address.startswith("brn1"):
            raise ValueError("Endereço deve começar com 'brn1'")
        
        if len(address) != 44:
            raise ValueError(f"Endereço inválido: comprimento {len(address)}, esperado 44")
        
        try:
            int(address[4:], 16)
        except ValueError:
            raise ValueError("Endereço contém caracteres hexadecimais inválidos")
        
        return True

    def _verify_tx_structure(self, tx) -> bool:
        """Verifica estrutura e validade de transação"""
        if not isinstance(tx, dict):
            logger.warning(f"Transação não é dicionário: {type(tx)}")
            return False
        
        # Transações do sistema são sempre válidas
        if tx.get("sender") == "SISTEMA":
            return True
        
        required_keys = ["sender", "receiver", "amount", "public_key", "signature", "timestamp"]
        if not all(k in tx for k in required_keys):
            logger.warning(f"Transação faltam chaves obrigatórias: {set(required_keys) - set(tx.keys())}")
            return False
        
        # Validações adicionais
        try:
            self._validate_address(tx["sender"])
            self._validate_address(tx["receiver"])
            
            amount = float(tx.get("amount", 0))
            if amount <= 0:
                logger.warning(f"Valor de transação inválido: {amount}")
                return False
            
            if amount < MIN_TX_FEE:
                logger.warning(f"Taxa de transação insuficiente: {amount} < {MIN_TX_FEE}")
                return False
            
            payload = {
                "sender": tx["sender"],
                "receiver": tx["receiver"],
                "amount": tx["amount"],
                "timestamp": tx["timestamp"]
            }
            
            if not WalletManager.verify_signature(tx["public_key"], payload, tx["signature"]):
                logger.warning("Assinatura de transação inválida")
                return False
            
            return True
        
        except ValueError as e:
            logger.warning(f"Erro na validação de transação: {e}")
            return False

    def _validate_block(self, block_data):
        """Validação robusta de bloco"""
        try:
            if not isinstance(block_data, dict):
                return False, "Bloco não é dicionário"
            
            required_fields = ["index", "previous_hash", "transactions", 
                             "difficulty", "nonce", "timestamp", "hash"]
            if not all(f in block_data for f in required_fields):
                return False, "Campos obrigatórios faltando"
            
            # Reconstrói e valida hash
            block = BrunoBlock(
                block_data["index"], block_data["previous_hash"], 
                block_data["transactions"], block_data["difficulty"], 
                block_data["nonce"], block_data["timestamp"], 
                block_data["hash"]
            )
            
            if block.calculate_hash() != block_data["hash"]:
                return False, "Hash não corresponde"
            
            # Valida Proof of Work
            target = "0" * block_data["difficulty"]
            if not block_data["hash"].startswith(target):
                return False, "Prova de Trabalho inválida"
            
            # Valida cada transação
            for tx in block_data["transactions"]:
                if not self._verify_tx_structure(tx):
                    return False, f"Transação inválida no bloco: {str(tx)[:100]}"
            
            return True, "OK"
        
        except Exception as e:
            logger.error(f"Erro na validação de bloco: {e}")
            return False, f"Erro de validação: {str(e)[:100]}"

    def _resolve_consensus(self, remote_chain, peer_ip="unknown") -> str:
        """Resolve consenso com validação rigorosa"""
        try:
            local_chain = self.db.get_raw_chain()
            
            if not isinstance(remote_chain, list) or len(remote_chain) == 0:
                logger.warning(f"Cadeia remota inválida de {peer_ip}")
                self._log_audit("INVALID_CHAIN_FORMAT", peer_ip, "Não é lista ou vazia", "ALERT")
                return "Cadeia remota inválida."
            
            if len(remote_chain) <= len(local_chain):
                logger.info(f"Cadeia local é dominante")
                return "Cadeia local ja e dominante."
            
            # Valida continuidade
            for i in range(1, len(remote_chain)):
                if remote_chain[i]["previous_hash"] != remote_chain[i-1]["hash"]:
                    logger.warning(f"Hashes corrompidos na cadeia de {peer_ip} no índice {i}")
                    self._log_audit("CORRUPTED_CHAIN", peer_ip, f"Índice {i}", "ALERT")
                    self.peer_blacklist.add_to_blacklist(peer_ip, "Cadeia corrompida")
                    return "Hashes corrompidos na cadeia remota."
            
            # Valida cada bloco
            for block_data in remote_chain:
                is_valid, message = self._validate_block(block_data)
                if not is_valid:
                    logger.warning(f"Bloco inválido no índice {block_data.get('index', '?')}: {message}")
                    self._log_audit("INVALID_BLOCK", peer_ip, f"Índice {block_data.get('index')}", "ALERT")
                    self.peer_blacklist.add_to_blacklist(peer_ip, f"Bloco inválido: {message}")
                    return f"Bloco #{block_data.get('index')} rejeitado: {message}"
            
            # Substitui cadeia
            logger.info(f"✅ Sincronizado com {peer_ip}: {len(local_chain)} → {len(remote_chain)} blocos")
            self.db.replace_chain(remote_chain)
            self._log_audit("CHAIN_SYNCED", peer_ip, f"{len(remote_chain)} blocos", "INFO")
            return f"Sincronizado com sucesso para {len(remote_chain)} blocos."
        
        except Exception as e:
            logger.error(f"Erro ao resolver consenso com {peer_ip}: {e}", exc_info=True)
            self._log_audit("CONSENSUS_ERROR", peer_ip, str(e)[:100], "ALERT")
            return f"Erro de consenso: {str(e)[:100]}"

    def save_encrypted_wallet(self, filename, password, address, 
                             spend_secret_key, public_key=""):
        """Salva carteira criptografada"""
        logger.info(f"Salvando carteira em {filename}")
        result = WalletManager.save_encrypted_wallet(
            filename, password, address, spend_secret_key, public_key
        )
        if result.get("status") == "sucesso":
            self._log_audit("WALLET_SAVED", "local", filename)
        return result

    def load_encrypted_wallet(self, filename, password):
        """Carrega carteira criptografada"""
        logger.info(f"Carregando carteira de {filename}")
        result = WalletManager.load_encrypted_wallet(filename, password)
        if result.get("status") == "sucesso":
            self._log_audit("WALLET_LOADED", "local", filename)
        return result

    def get_full_chain(self):
        """Obtém estado completo da blockchain"""
        with self.mempool_lock:
            mempool_size = len(self.mempool)
        
        chain = self.db.get_raw_chain()
        return {
            "chain": chain,
            "length": len(chain),
            "mempool_size": mempool_size,
            "is_mining": self.is_mining,
            "current_difficulty": chain[-1]["difficulty"] if chain else 4,
            "connected_peers": len(self.connected_peers),
            "timestamp": datetime.now().isoformat()
        }

    def generate_wallet(self):
        """Gera nova carteira"""
        logger.info("Gerando nova carteira")
        wallet = WalletManager.generate_keypair()
        self._log_audit("WALLET_GENERATED", "local", wallet["address"])
        return wallet

    def get_balance(self, address):
        """Obtém saldo de endereço"""
        try:
            self._validate_address(address)
            balance = 0.0
            
            for b in self.db.get_raw_chain():
                for tx in b["transactions"]:
                    if tx.get("sender") == address:
                        balance -= float(tx.get("amount", 0))
                    if tx.get("receiver") == address:
                        balance += float(tx.get("amount", 0))
            
            logger.debug(f"Saldo de {address}: {balance}")
            return {"address": address, "balance": balance}
        
        except ValueError as e:
            logger.warning(f"Erro ao obter saldo: {e}")
            return {"status": "erro", "message": str(e)}

    @secure_operation
    def send_funds(self, sender, receiver, amount, spend_secret_key, public_key):
        """Envia fundos com validação completa"""
        try:
            self._validate_address(sender)
            self._validate_address(receiver)
            
            if sender == receiver:
                return {"status": "erro", "message": "Não pode enviar para si mesmo"}
            
            amount = float(amount)
            if amount <= 0:
                return {"status": "erro", "message": "Quantia invalida."}
            
            # Verifica saldo
            sender_balance = self.get_balance(sender).get("balance", 0)
            if sender_balance < amount:
                logger.warning(f"Saldo insuficiente: {sender_balance} < {amount}")
                return {"status": "erro", "message": "Saldo insuficiente!"}
            
            tx_payload = {
                "sender": str(sender).strip(),
                "receiver": str(receiver).strip(),
                "amount": amount,
                "timestamp": time.time()
            }
            
            signature = WalletManager.sign_transaction(spend_secret_key, tx_payload)
            full_tx = {
                **tx_payload,
                "public_key": public_key,
                "signature": signature
            }
            
            # Adiciona à mempool
            with self.mempool_lock:
                self.mempool.append(full_tx)
            
            logger.info(f"Transação criada: {sender} → {receiver}: {amount} BRN")
            self._log_audit("TX_CREATED", "local", 
                          f"{sender[:10]}... → {receiver[:10]}...: {amount} BRN")
            
            # Broadcast em thread separada
            threading.Thread(
                target=self._broadcast_transaction_to_network,
                args=(full_tx,),
                daemon=True
            ).start()
            
            return {"status": "sucesso", "message": "Transacao assinada e enviada a mempool!"}
        
        except Exception as e:
            logger.error(f"Erro ao enviar fundos: {e}", exc_info=True)
            return {"status": "erro", "message": str(e)}

    def toggle_continuous_mining(self, miner_address):
        """Inicia/para mineração contínua"""
        if self.is_mining:
            self.is_mining = False
            self.mining_stop_event.set()
            logger.info("⛏️ Mineração pausada")
            self._log_audit("MINING_STOPPED", "local", miner_address)
            return {"status": "sucesso", "message": "Mineracao continua pausada.", 
                   "is_mining": False}
        else:
            try:
                self._validate_address(miner_address)
                self.is_mining = True
                self.mining_stop_event.clear()
                
                self.miner_thread = threading.Thread(
                    target=self._continuous_mining_loop,
                    args=(miner_address,),
                    daemon=True,
                    name=f"Miner-{miner_address[:10]}"
                )
                self.miner_thread.start()
                
                logger.info(f"⛏️ Mineração iniciada para {miner_address}")
                self._log_audit("MINING_STARTED", "local", miner_address)
                
                return {"status": "sucesso", "message": "Mineracao continua iniciada!", 
                       "is_mining": True}
            
            except Exception as e:
                logger.error(f"Erro ao iniciar mineração: {e}", exc_info=True)
                return {"status": "erro", "message": str(e)}

    def _continuous_mining_loop(self, miner_address):
        """Loop de mineração contínua com segurança"""
        logger.info(f"⛏️ Loop de mineração iniciado para {miner_address}")
        blocks_mined = 0
        
        while self.is_mining and not self.mining_stop_event.is_set():
            try:
                local_chain = self.db.get_raw_chain()
                last_block = local_chain[-1]
                next_difficulty = self._calculate_next_difficulty()
                
                with self.mempool_lock:
                    bloco_txs = [
                        {"sender": "SISTEMA", "receiver": str(miner_address).strip(), 
                         "amount": BLOCK_REWARD}
                    ] + list(self.mempool)[:MAX_TRANSACTIONS_PER_BLOCK]
                
                new_block = BrunoBlock(
                    last_block["index"] + 1,
                    last_block["hash"],
                    bloco_txs,
                    difficulty=next_difficulty
                )
                
                success = new_block.mine_block(stop_event=self.mining_stop_event)
                
                if success and self.is_mining:
                    self.db.insert_block(new_block)
                    blocks_mined += 1
                    
                    with self.mempool_lock:
                        self.mempool = [tx for tx in self.mempool if tx not in bloco_txs]
                    
                    # Broadcast da cadeia atualizada
                    raw_chain_json = json.dumps(self.db.get_raw_chain())
                    broadcast_count = 0
                    
                    for ip, port in list(self.connected_peers):
                        try:
                            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            s.settimeout(3.0)
                            s.connect((ip, int(port)))
                            s.sendall(f"SYNC_CHAIN:{raw_chain_json}".encode('utf-8'))
                            s.close()
                            broadcast_count += 1
                        except Exception:
                            pass
                    
                    logger.info(f"✅ Bloco #{new_block.index} minerado "
                               f"(Diff: {next_difficulty}, Propagado: {broadcast_count} pares). "
                               f"Hash: {new_block.hash[:16]}...")
                    self._log_audit("BLOCK_MINED", "local", 
                                  f"Bloco #{new_block.index}, Dif: {next_difficulty}")
            
            except Exception as e:
                logger.error(f"⚠️ Erro no loop de mineração: {e}", exc_info=True)
                time.sleep(2)
        
        logger.info(f"🛑 Loop de mineração encerrado. Blocos minerados: {blocks_mined}")

if __name__ == '__main__':
    p2p_port = 6001
    if len(sys.argv) > 1:
        try:
            p2p_port = int(sys.argv[1])
        except ValueError:
            pass
    
    logger.info(f"🔐 Iniciando aplicação na porta {p2p_port}")
    
    try:
        AutoPortForwarder.open_port_on_router(p2p_port)
    except Exception as e:
        logger.warning(f"Erro ao abrir porta no router: {e}")
    
    api_local = CriptoAPI(p2p_port)
    webview.create_window(
        title=f"Carteira Nativa {COIN_NAME} (Porta: {p2p_port})",
        url="index.html",
        js_api=api_local,
        width=740,
        height=800,
        resizable=True
    )
    webview.start()
