@echo off
setlocal EnableDelayedExpansion

REM ========================================================
REM  Script de instalacao e execucao do projeto BRN-L2
REM  Usa Miniconda + conda-forge (sem canais defaults)
REM  Python 3.11 (mais estavel com pywin32/pythonnet)
REM ========================================================

echo ========================================================
echo  BRN-L2 - Instalacao e Execucao (GUI)
echo ========================================================
echo.

REM --------------------------------------------------------
REM  1. Verificar se o Conda esta instalado
REM --------------------------------------------------------
echo [INFO] Verificando a presenca do Conda...

where conda >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] Conda encontrado no PATH.
    set "CONDA_FOUND=1"
    goto :conda_found
)

if exist "%UserProfile%\miniconda3\Scripts\conda.exe" (
    set "CONDA_PATH=%UserProfile%\miniconda3"
    goto :conda_found
)
if exist "%UserProfile%\Miniconda3\Scripts\conda.exe" (
    set "CONDA_PATH=%UserProfile%\Miniconda3"
    goto :conda_found
)
if exist "C:\ProgramData\miniconda3\Scripts\conda.exe" (
    set "CONDA_PATH=C:\ProgramData\miniconda3"
    goto :conda_found
)

echo [AVISO] Miniconda nao foi encontrado.
echo [INFO] Iniciando a instalacao automatica do Miniconda...

set "MINICONDA_INSTALLER=%TEMP%\Miniconda3-latest-Windows-x86_64.exe"
set "MINICONDA_URL=https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe"

echo [INFO] Baixando o Miniconda...
powershell -Command "& {Invoke-WebRequest -Uri '%MINICONDA_URL%' -OutFile '%MINICONDA_INSTALLER%'}"
if not exist "%MINICONDA_INSTALLER%" (
    echo [ERRO] Falha ao baixar o instalador do Miniconda.
    pause
    exit /b 1
)

echo [INFO] Instalando o Miniconda silenciosamente...
start /wait "" "%MINICONDA_INSTALLER%" /InstallationType=JustMe /RegisterPython=0 /AddToPath=0 /S /D=%UserProfile%\miniconda3
if %errorlevel% neq 0 (
    echo [ERRO] A instalacao do Miniconda falhou.
    pause
    exit /b 1
)

set "CONDA_PATH=%UserProfile%\miniconda3"
echo [INFO] Miniconda instalado com sucesso.

:conda_found
if not defined CONDA_PATH (
    for /f "tokens=*" %%i in ('where conda 2^>nul') do (
        set "CONDA_PATH=%%~dpi.."
        goto :conda_path_set
    )
)
:conda_path_set

echo [INFO] Usando o Miniconda em: %CONDA_PATH%
echo.

REM --------------------------------------------------------
REM  3. Inicializar o Conda
REM --------------------------------------------------------
call "%CONDA_PATH%\Scripts\activate.bat" "%CONDA_PATH%"

REM --------------------------------------------------------
REM  4. Aceitar TOS automaticamente
REM --------------------------------------------------------
set CONDA_PLUGINS_AUTO_ACCEPT_TOS=yes

REM --------------------------------------------------------
REM  5. Configurar conda-forge como unico canal
REM --------------------------------------------------------
echo [INFO] Configurando o Conda para usar apenas o canal conda-forge...
call conda config --remove-key channels >nul 2>&1
call conda config --add channels conda-forge
call conda config --set channel_priority strict
echo.

REM --------------------------------------------------------
REM  6. Criar ambiente com Python 3.11 (mais estavel)
REM --------------------------------------------------------
if exist "%CONDA_PATH%\envs\brn-l2" (
    echo [INFO] Ambiente brn-l2 ja existe. Pulando criacao.
) else (
    echo [INFO] Criando novo ambiente com Python 3.11...
    call conda create -n brn-l2 python=3.11 --override-channels -c conda-forge -y
    if %errorlevel% neq 0 (
        echo [ERRO] Falha ao criar o ambiente conda.
        pause
        exit /b 1
    )
)
echo.

REM --------------------------------------------------------
REM  7. Instalar dependencias via conda-forge
REM --------------------------------------------------------
echo [INFO] Instalando dependencias via conda-forge...
echo [INFO] Isso pode levar alguns minutos na primeira vez.
echo.

call conda install -n brn-l2 --override-channels -c conda-forge -y ^
    python=3.11 ^
    coincurve ^
    ckzg ^
    lru-dict ^
    orjson ^
    web3 ^
    eth-account ^
    eth-keys ^
    eth-utils ^
    requests ^
    colorama ^
    python-dotenv ^
    loguru ^
    pywebview ^
    pythonnet ^
    cryptography ^
    pywin32 ^
    flask

if %errorlevel% neq 0 (
    echo.
    echo [AVISO] A instalacao em lote falhou. Tentando pacote por pacote...
    for %%p in (coincurve ckzg lru-dict orjson web3 eth-account eth-keys eth-utils requests colorama python-dotenv loguru pywebview pythonnet cryptography pywin32 flask) do (
        echo [INFO] Instalando %%p...
        call conda install -n brn-l2 --override-channels -c conda-forge -y %%p
    )
)

echo.
echo [INFO] Dependencias instaladas.
echo.

REM --------------------------------------------------------
REM  8. Ativar ambiente e verificar pacotes
REM --------------------------------------------------------
call conda activate brn-l2

echo [INFO] Python no ambiente:
python --version
echo.

echo [INFO] Verificando pacotes criticos...
python -c "import orjson; print('  [OK] orjson')"          2>nul || echo [AVISO] orjson ausente
python -c "import web3; print('  [OK] web3')"              2>nul || echo [AVISO] web3 ausente
python -c "import coincurve; print('  [OK] coincurve')"    2>nul || echo [AVISO] coincurve ausente
python -c "import ckzg; print('  [OK] ckzg')"              2>nul || echo [AVISO] ckzg ausente
python -c "import lru; print('  [OK] lru-dict')"           2>nul || echo [AVISO] lru-dict ausente
python -c "import eth_account; print('  [OK] eth-account')" 2>nul || echo [AVISO] eth-account ausente
python -c "import webview; print('  [OK] pywebview')"      2>nul || echo [AVISO] pywebview ausente
python -c "import clr; print('  [OK] pythonnet')"          2>nul || echo [AVISO] pythonnet ausente
echo.

REM --------------------------------------------------------
REM  9. Verificar arquivos do projeto
REM --------------------------------------------------------
if not exist "index.html" (
    echo [ERRO] index.html nao encontrado no diretorio atual.
    echo [INFO] Coloque o run.bat na pasta raiz do projeto.
    pause
    exit /b 1
)
if not exist "main.py" (
    echo [ERRO] main.py nao encontrado.
    pause
    exit /b 1
)

REM --------------------------------------------------------
REM  10. Executar o projeto com GUI (main.py)
REM --------------------------------------------------------
echo [INFO] Executando o projeto com interface grafica...
echo.
python main.py

echo.
echo ========================================================
echo  Processo finalizado.
echo ========================================================
pause >nul
endlocal