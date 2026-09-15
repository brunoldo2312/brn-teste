@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM ============================================================
REM  BRN-Estavel - Launcher unificado (Windows)
REM  Cria venv, instala dependencias e roda o programa
REM ============================================================

REM ----- CONFIGURACOES (edite se necessario) -----
set "PORT=6001"
set "MINER=brn1qxyzk7y0v2j4g0a8d9n5t3m2k7h4s6w8c9p2e"
set "MINE=--mine"
set "EXPLORER=--explorer"
set "OPEN_BROWSER=--open-browser"
REM -----------------------------------------------

REM ---- 1) Verifica Python ----
where python >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado no PATH.
    echo        Instale o Python 3.10+ em https://www.python.org/downloads/
    echo        Marque "Add Python to PATH" durante a instalacao.
    pause
    exit /b 1
)

REM ---- 2) Cria o venv se nao existir ----
if not exist "env\Scripts\python.exe" (
    echo [SETUP] Criando ambiente virtual...
    python -m venv env
    if errorlevel 1 (
        echo [ERRO] Falha ao criar o venv.
        pause
        exit /b 1
    )
    set "NEED_INSTALL=1"
) else (
    set "NEED_INSTALL=0"
)

REM ---- 3) Instala dependencias se necessario ----
if "!NEED_INSTALL!"=="1" (
    echo [SETUP] Instalando dependencias...
    call "env\Scripts\python.exe" -m pip install --upgrade pip
    if exist "requirements.txt" (
        call "env\Scripts\python.exe" -m pip install -r requirements.txt
    ) else (
        call "env\Scripts\python.exe" -m pip install ^
            coincurve^>=19.0.0 ^
            orjson^>=3.9 ^
            flask^>=3.0 ^
            cryptography^>=42.0
    )
    if errorlevel 1 (
        echo [ERRO] Falha ao instalar dependencias.
        pause
        exit /b 1
    )
    echo [SETUP] Dependencias instaladas.
)

REM ---- 4) Roda o programa ----
echo [RUN] Iniciando BRN-Estavel na porta %PORT% ...
call "env\Scripts\python.exe" main.py ^
    --port %PORT% ^
    --miner "%MINER%" ^
    %MINE% %EXPLORER% %OPEN_BROWSER%

if errorlevel 1 (
    echo.
    echo [ERRO] O programa encerrou com erro.
    pause
    exit /b 1
)

endlocal

pip install -r requirements.txt

# Nó simples
python node.py 6001 blockchain_node_6001.db

# Nó minerando para um endereço
python node.py 6001 blockchain_node_6001.db brn1qxyzk7y0v2j4g0a8d9n5t3m2k7h4s6w8c9p2e --mine

# Nó + explorador + navegador
python main.py --port 6001 --miner brn1qxyzk7y0v2j4g0a8d9n5t3m2k7h4s6w8c9p2e --mine --explorer --open-browser
📖 Manual de Execução — Moeda Bruno v2 (BRN)

Este manual cobre desde a instalação do ambiente até a execução completa do nó, mineração, explorador de blocos e exposição pública via Ngrok. Siga na ordem apresentada.

---

📋 Pré-requisitos

Item Requisito
Sistema Operacional Windows 10/11, Linux (Ubuntu/Debian) ou macOS
Python Versão 3.8 ou superior
Conexão Internet (para instalação e Ngrok)
Porta TCP 6001 livre (nó P2P)
Porta TCP 8080 livre (explorador)
Porta UDP 6010 livre (descoberta na LAN)

---

🔧 PASSO 1: Instalar o Python

Windows

1. Acesse python.org/downloads e baixe o instalador.
2. Marque a opção "Add Python to PATH" durante a instalação.
3. Para verificar, abra o CMD e digite:
   ```cmd
   python --version
   ```
   Deve aparecer algo como Python 3.11.x.

Linux (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv -y
python3 --version
```

---

📦 PASSO 2: Baixar o Projeto

```cmd
git clone https://github.com/brunoldo2312/brn-estavel.git
cd brn-estavel
```

Ou baixe o ZIP pelo GitHub, extraia e abra o terminal na pasta extraída.

---

🐍 PASSO 3: Criar Ambiente Virtual

Windows

```cmd
python -m venv env
env\Scripts\activate
```

Linux/macOS

```bash
python3 -m venv env
source env/bin/activate
```

Como saber que o ambiente está ativo: O prompt do terminal mostrará (env) no início.

---

📚 PASSO 4: Instalar Dependências

Com o ambiente virtual ativo, execute:

```cmd
pip install --upgrade pip
pip install flask cryptography pywebview pyqt6 PyQt6-WebEngine
```

Dependências opcionais (para Linux)

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1 -y
```

---

📁 PASSO 5: Verificar Arquivos do Projeto

Sua pasta deve conter, no mínimo:

```
brn-estavel/
├── bruno_blockchain_v2.py    ← Motor principal
├── cripto_db_v2.py           ← Banco de dados (UTXO)
├── cripto_wallet_v2.py       ← Carteira
├── cripto_p2p_network.py     ← Módulo P2P completo
├── explorer.py               ← Explorador web
├── main.py                   ← Executor unificado
├── index.html                ← Interface gráfica
└── iniciar_brn_v2.cmd        ← Script Windows
```

Arquivos da v1 que NÃO devem ser usados: bruno_blockchain_real.py, setup_project.py, blockchain_node_6002.db. Mova-os para uma pasta legacy/ ou remova-os.

---

🧹 PASSO 6: Limpar Dados Antigos (Primeira Execução)

Se for a primeira execução ou se quiser começar do zero:

Windows

```cmd
del /q brn_v2_chain_*.db
del /q mempool_node_*.json
rmdir /s /q __pycache__
```

Linux

```bash
rm -f brn_v2_chain_*.db mempool_node_*.json
rm -rf __pycache__
```

⚠️ Atenção: Isso apaga a blockchain local. Só faça isso se quiser recomeçar do zero.

---

🚀 PASSO 7: Iniciar o Nó Principal

Existem três formas de iniciar o programa. Escolha uma:

🖥️ Modo 1: GUI (Interface Gráfica) — Recomendado

```cmd
python main.py 6001
```

O que acontece:

· Inicia o nó P2P na porta 6001
· Inicia o explorador web em http://127.0.0.1:8080
· Abre a janela gráfica (se pywebview estiver instalado)
· Na primeira execução, pede uma senha de carteira (mínimo 12 caracteres)

⌨️ Modo 2: Mineração Automática

```cmd
python main.py 6001 --miner
```

O nó começa a minerar automaticamente para o endereço da carteira padrão.

💻 Modo 3: CLI (Linha de Comando)

```cmd
python main.py 6001 --cli
```

Comandos disponíveis no prompt brn>:

Comando Descrição
status Mostra altura, dificuldade, recompensa, peers
miner start Inicia mineração
miner stop Para a mineração
balance Saldo da carteira
send <endereco> <valor> Envia BRN
chain Últimos 10 blocos
exit Sair

---

⛏️ PASSO 8: Minerar Blocos

Pela GUI

1. Abra a janela da Moeda Bruno v2
2. Clique no botão ⛏️ Minerar
3. O log mostrará os blocos sendo minerados em tempo real

Pela CLI

```
brn> miner start
```

O que esperar

· Dificuldade inicial: 4 (4 zeros no início do hash)
· Tempo médio por bloco: 5 a 30 segundos (varia com a CPU)
· Recompensa inicial: 50 BRN por bloco
· Halving a cada 210.000 blocos

---

🌐 PASSO 9: Acessar o Explorador de Blocos

No próprio computador

Abra o navegador e acesse:

```
http://127.0.0.1:8080
```

Em outro dispositivo na mesma rede Wi-Fi

1. Descubra o IP local do computador que está rodando o nó:
   Windows:
   ```cmd
   ipconfig
   ```
   Procure por "Endereço IPv4" (ex: 192.168.0.17).
   Linux:
   ```bash
   hostname -I
   ```
2. No celular ou outro PC, acesse:
   ```
   http://192.168.0.17:8080
   ```
   (Substitua pelo IP que você encontrou)
3. Se não abrir, libere a porta 8080 no firewall:
   Windows (Prompt como Administrador):
   ```cmd
   netsh advfirewall firewall add rule name="BRN Explorer" dir=in action=allow protocol=TCP localport=8080
   netsh advfirewall firewall add rule name="BRN P2P" dir=in action=allow protocol=TCP localport=6001
   netsh advfirewall firewall add rule name="BRN Discovery" dir=in action=allow protocol=UDP localport=6010
   ```

---

🌍 PASSO 10: Expor o Explorador na Internet (Ngrok)

Este passo é necessário para que a exchange (ou qualquer pessoa fora da sua rede) consiga acessar o explorador.

1. Criar conta no Ngrok

1. Acesse dashboard.ngrok.com/signup
2. Crie uma conta gratuita
3. Copie seu Authtoken no painel

2. Instalar o Ngrok

Windows:

1. Baixe em ngrok.com/download
2. Extraia o ngrok.exe para C:\ngrok\
3. Adicione ao PATH ou use o caminho completo

Linux:

```bash
curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | sudo tee /etc/apt/sources.list.d/ngrok.list
sudo apt update && sudo apt install ngrok
```

3. Configurar o Token (apenas uma vez)

```cmd
ngrok config add-authtoken SEU_TOKEN_AQUI
```

4. Criar o Túnel Público

Em um novo terminal (com o nó já rodando):

```cmd
ngrok http 8080
```

Você verá algo como:

```
Forwarding    https://abcd-1234.ngrok-free.app -> http://localhost:8080
```

Copie o link https://... — esse é o endereço público do seu explorador.

5. Testar

Abra o link no celular (fora do Wi-Fi) e verifique se o explorador carrega.

---

🤖 PASSO 11: Inicialização Automática (Opcional)

Windows: Script .cmd

Edite o arquivo iniciar_brn_v2.cmd e substitua COLE_SEU_NOVO_TOKEN_AQUI pelo seu token Ngrok. Depois, basta dar duplo clique.

Linux: Script .sh

Crie um arquivo iniciar_brn_v2.sh:

```bash
#!/bin/bash
cd "$(dirname "$0")"
source env/bin/activate
export NGROK_AUTHTOKEN="SEU_TOKEN_AQUI"

echo "[1/2] Iniciando nó..."
python main.py 6001 &
sleep 4

echo "[2/2] Abrindo túnel Ngrok..."
ngrok http 8080

wait
```

Torne executável:

```bash
chmod +x iniciar_brn_v2.sh
./iniciar_brn_v2.sh
```

---

🔗 PASSO 12: Sincronizar Dois Nós (Rede Local)

Para rodar a BRN em dois computadores na mesma rede:

Máquina 1 (Nó Principal)

```cmd
python main.py 6001
```

Máquina 2 (Nó Secundário)

```cmd
python main.py 6002
```

Os dois nós vão se descobrir automaticamente via UDP broadcast na porta 6010. O nó com menos blocos vai sincronizar com o mais longo.

Para verificar: No log do terminal, procure mensagens como:

```
[P2P] Novo peer descoberto: 192.168.0.17:6001
[P2P] Sincronizando com 192.168.0.17:6001 (15 > 3)
```

Se não sincronizar, verifique se:

· Ambos estão na mesma rede Wi-Fi
· O firewall permite UDP 6010 e TCP 6001
· O roteador não tem "AP isolation" ativo

---

🛑 Como Parar o Programa

Modo Como parar
GUI Feche a janela
CLI Digite exit ou pressione Ctrl+C
Mineração Clique em ⏹️ Parar ou Ctrl+C
Ngrok Feche a janela do terminal do Ngrok

Ao parar, o nó encerra o mapeamento UPnP e salva o estado no banco SQLite automaticamente.

---

🔧 Solução de Problemas

❌ "Python não é reconhecido como comando"

Causa: Python não está no PATH.
Solução: Reinstale o Python marcando "Add Python to PATH".

❌ "ModuleNotFoundError: No module named 'flask'"

Causa: Ambiente virtual não ativado ou dependência faltando.
Solução:

```cmd
env\Scripts\activate
pip install flask cryptography pywebview
```

❌ "Address already in use" (porta 6001 ou 8080)

Causa: Outro processo está usando a porta.
Solução (Windows):

```cmd
netstat -ano | findstr :6001
taskkill /PID <numero_do_pid> /F
```

Solução (Linux):

```bash
lsof -i :6001
kill -9 <PID>
```

❌ "O explorador não abre no celular"

Causas possíveis:

1. Firewall bloqueando a porta 8080 → libere conforme PASSO 9
2. Celular em rede diferente → conecte no mesmo Wi-Fi
3. Roteador com AP isolation → desative nas configurações do roteador

❌ "Ngrok: ERR_NGROK_108"

Causa: Token expirado ou inválido.
Solução:

```cmd
ngrok config add-authtoken SEU_NOVO_TOKEN
```

❌ "Não sincroniza com outro nó"

Soluções:

1. Verifique se ambos estão na mesma rede
2. Libere UDP 6010 no firewall
3. Desative "AP isolation" no roteador
4. Teste manualmente: ping <IP_do_outro_PC>

❌ "Mineração muito lenta"

Causa: Dificuldade inicial alta para sua CPU.
Solução: Edite bruno_blockchain_v2.py:

```python
INITIAL_DIFFICULTY = 2   # Reduza de 4 para 2
MAX_DIFFICULTY = 6       # Reduza de 8 para 6
```

❌ "Carteira pede senha toda vez"

Causa: Comportamento esperado por segurança.
Solução: Use a mesma senha sempre, ou remova o arquivo .wallet para criar uma nova carteira.

---

📊 Comandos de Referência Rápida

Windows (CMD)

```cmd
:: Criar ambiente
python -m venv env
env\Scripts\activate

:: Instalar dependências
pip install flask cryptography pywebview pyqt6 PyQt6-WebEngine

:: Executar
python main.py 6001
python main.py 6001 --miner
python main.py 6001 --cli

:: Ngrok
ngrok http 8080

:: Limpar dados
del /q brn_v2_chain_*.db
```

Linux/macOS

```bash
# Criar ambiente
python3 -m venv env
source env/bin/activate

# Instalar dependências
pip install flask cryptography pywebview

# Executar
python main.py 6001
python main.py 6001 --miner
python main.py 6001 --cli

# Ngrok
ngrok http 8080

# Limpar dados
rm -f brn_v2_chain_*.db
```

---

✅ Checklist de Primeira Execução

□ Python 3.8+ instalado e no PATH
□ Projeto baixado do GitHub
□ Ambiente virtual criado e ativado
□ Dependências instaladas (flask, cryptography, pywebview)
□ Arquivos da v1 movidos para legacy/ ou removidos
□ Banco de dados antigo deletado (opcional)
□ Nó iniciado (python main.py 6001)
□ Senha de carteira definida (mín. 12 caracteres)
□ Explorador acessível em http://127.0.0.1:8080
□ Mineração iniciada pela GUI ou CLI
□ Ngrok configurado com token (se for expor publicamente)
□ Link público copiado e testado no celular

---

🔒 Recomendações de Segurança

1. Nunca commit o token do Ngrok no GitHub. Use variáveis de ambiente.
2. Nunca compartilhe o arquivo .wallet — ele contém a chave privada criptografada.
3. Use senha forte (mín. 12 caracteres) para o backup da carteira.
4. UPnP é opcional — só ative se realmente precisar expor a porta à internet.
5. Não use para valores reais — este é um projeto educacional.

---

Se precisar de ajuda com algum passo específico (como configurar uma VPS para hospedagem permanente, ou adaptar o index.html para incluir mais funcionalidades), é só pedir.