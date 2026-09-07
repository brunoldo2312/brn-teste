# 🔒 Correções de Segurança e Bugs Críticos

Este documento descreve todas as vulnerabilidades e erros identificados e corrigidos.

## 🔴 ERROS CRÍTICOS

### 1. Método `to_dict()` Truncado
**Arquivo**: `bruno_blockchain_real.py:89`
**Problema**: O método estava incompleto (`se[...]`), causando erro ao serializar blocos.
**Correção**: Implementado método completo que retorna todos os campos do bloco.

**Antes**:
```python
def to_dict(self):
    return {"index": self.index, ..., "hash": se[...]  # Truncado
```

**Depois**:
```python
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
```

---

### 2. Verificação de IP Incorreta
**Arquivo**: `bruno_blockchain_real.py:124`
**Problema**: `client_addr` é uma tupla `(ip, port)`, não uma string. Comparação sempre falhará.
**Impacto**: Lógica de peer discovery completamente quebrada.

**Antes**:
```python
if client_addr != "127.0.0.1":  # ❌ NUNCA será True
    self.connected_peers.add((client_addr[0], self.p2p_port))
```

**Depois**:
```python
if client_addr[0] != "127.0.0.1":  # ✅ Correto
    self.connected_peers.add((client_addr[0], self.p2p_port))
```

---

## 🟠 VULNERABILIDADES DE SEGURANÇA

### 3. Falta de Validação de Proof-of-Work
**Arquivo**: `bruno_blockchain_real.py:152`
**Problema**: A sincronização apenas valida se hashes estão linkados, mas **não verifica se o nonce é válido**.
**Impacto**: Um atacante pode enviar uma blockchain falsa com hashes "linkados" mas nonce inválido.
**Nível**: CRÍTICO

**Antes**:
```python
def _resolve_consensus(self, remote_chain) -> str:
    if len(remote_chain) <= len(self.db.get_raw_chain()):
        return "Cadeia local ja e dominante."
    for i in range(1, len(remote_chain)):
        if remote_chain[i]["previous_hash"] != remote_chain[i-1]["hash"]:
            return "Hashes corrompidos."
    self.db.replace_chain(remote_chain)  # ❌ Sem validar PoW!
```

**Depois**:
```python
def _validate_block(self, block_data):
    """Valida Proof-of-Work de um bloco"""
    block = BrunoBlock(...)
    calculated_hash = block.calculate_hash()
    if calculated_hash != block_data["hash"]:
        return False, "Hash não corresponde"
    
    # Validar que o hash inicia com difficulty zeros
    target = "0" * block_data["difficulty"]
    if not block_data["hash"].startswith(target):
        return False, "Proof-of-Work inválido"
    
    return True, "OK"

def _resolve_consensus(self, remote_chain) -> str:
    # ... validar linkagem ...
    
    # ✅ Validar Proof-of-Work
    for block_data in remote_chain:
        is_valid, message = self._validate_block(block_data)
        if not is_valid:
            return f"Bloco #{block_data['index']}: {message}"
    
    self.db.replace_chain(remote_chain)
```

---

### 4. Criptografia Fraca (XOR com SHA256)
**Arquivo**: `cripto_wallet.py:18-25`
**Problema**: Usar XOR com stream SHA256 é **criptograficamente inseguro**. SHA256 não foi projetado para ser uma cifra.
**Impacto**: Wallets criptografadas podem ser quebradas.
**Nível**: CRÍTICO

**Antes**:
```python
cipher_stream = hashlib.sha256(key).digest()
for i in range(len(raw_json)):
    if i % 32 == 0 and i > 0:
        cipher_stream = hashlib.sha256(cipher_stream + key).digest()
    encrypted_bytes.append(raw_json[i] ^ cipher_stream[i % 32])  # ❌ Inseguro
```

**Depois**:
```python
# ✅ Usar Fernet (AES-128 + HMAC)
from cryptography.fernet import Fernet

key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
key_b64 = base64.b64encode(key[:32])
cipher = Fernet(key_b64)
ciphertext = cipher.encrypt(raw_json)  # Seguro!
```

**Compatibilidade**: O código tenta usar Fernet, mas fallback para XOR se não estiver disponível. Instalar cryptography:
```bash
pip install cryptography
```

---

### 5. Race Condition no Mempool
**Arquivo**: `bruno_blockchain_real.py:244-245`
**Problema**: Múltiplas threads acessam `self.mempool` sem sincronização.
**Impacto**: Corrupção de dados, transações perdidas ou duplicadas.
**Nível**: ALTO

**Antes**:
```python
# Thread 1
self.mempool.append(nova_tx)  # ❌ Sem lock

# Thread 2 (simultaneamente)
self.mempool.clear()  # ❌ Race condition!
```

**Depois**:
```python
self.mempool_lock = threading.Lock()

# Thread 1
with self.mempool_lock:
    self.mempool.append(nova_tx)  # ✅ Protegido

# Thread 2
with self.mempool_lock:
    self.mempool.clear()  # ✅ Protegido
```

---

### 6. Recebimento Incompleto de Socket
**Arquivo**: `bruno_blockchain_real.py:107-109`
**Problema**: `recv(1024 * 1024)` pode retornar parcialmente. Mensagens maiores que 1MB são truncadas.
**Impacto**: Perda de dados em sincronia de blockchain grande.
**Nível**: ALTO

**Antes**:
```python
data = client_conn.recv(1024 * 1024).decode('utf-8')  # ❌ Pode truncar
```

**Depois**:
```python
def _receive_all(self, sock, buffer_size=4096, max_size=10*1024*1024):
    """Recebe dados completos do socket com proteção de tamanho"""
    data = b""
    try:
        while True:
            chunk = sock.recv(buffer_size)
            if not chunk:
                break
            data += chunk
            if len(data) > max_size:
                raise ValueError(f"Mensagem excede {max_size} bytes")
    except socket.timeout:
        pass
    return data.decode('utf-8', errors='ignore')

# Usar:
data = self._receive_all(client_conn)
```

---

### 7. Endereços sem Validação
**Arquivo**: `bruno_blockchain_real.py:199-200`
**Problema**: Qualquer string é aceita como endereço. Sem validação de formato.
**Impacto**: Consultas de saldo com strings malformadas, injeção de dados.
**Nível**: MÉDIO

**Antes**:
```python
def get_balance(self, address):
    # Aceita qualquer string
    balance = 0.0
    for b in self.db.get_raw_chain():
        # ...
```

**Depois**:
```python
def _validate_address(self, address):
    """Valida formato de endereço BRN1"""
    if not isinstance(address, str):
        raise ValueError("Endereço deve ser uma string")
    if not address.startswith("brn1"):
        raise ValueError("Endereço deve começar com 'brn1'")
    if len(address) != 44:  # brn1 (4) + 40 hex
        raise ValueError(f"Tamanho inválido (esperado 44, recebido {len(address)})")
    try:
        int(address[4:], 16)  # Validar hex
    except ValueError:
        raise ValueError("Endereço contém caracteres inválidos")
    return True

def get_balance(self, address):
    try:
        self._validate_address(address)  # ✅ Validar primeiro
        # ... resto do código
```

---

## 📋 Checklist de Segurança Implementado

- ✅ Validação de Proof-of-Work na sincronização
- ✅ Proteção de mempool com mutex (threading.Lock)
- ✅ Criptografia segura com Fernet (AES + HMAC)
- ✅ Recebimento completo de socket com tamanho máximo
- ✅ Validação de formato de endereço
- ✅ Correção de comparação de tuple (client_addr)
- ✅ Método to_dict() completo

## 🚀 Próximas Melhorias Recomendadas

1. **Assinatura Digital**: Adicionar ECDSA para autenticar transações
2. **Nonce de Transação**: Prevenir replay attacks
3. **Rate Limiting**: Limitar requisições por IP
4. **Logging Seguro**: Registrar tentativas de ataque
5. **Tests Unitários**: Cobertura de casos de segurança
6. **Auditoria**: Review por especialista em blockchain

---

**Data**: Setembro 2026
**Status**: ✅ Críticas resolvidas
