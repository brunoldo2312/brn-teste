/* ==========================================================================
   CARTEIRA BRN P2P - MÓDULO WEB3 E SINCRONIZAÇÃO OFF-CHAIN
   ========================================================================== */

// --- CONFIGURAÇÕES DE ENDEREÇOS (SUBSTITUA PELOS SEUS ENDEREÇOS) ---
const CONTRATO_ESCROW_ADDRESS = "COLE_AQUI_O_ENDERECO_DO_CONTRATO_IMPLANTADO_NA_POLYGON";
const TOKEN_BRN_ADDRESS       = "COLE_AQUI_O_ENDERECO_DO_CONTRATO_DO_TOKEN_BRN";

// --- VARIÁVEIS GLOBAIS DE ESTADO ---
let provider = null;
let signer = null;
let userAddress = null;
let webSocket = null;

// Configuração da Rede Polygon Mainnet
const POLYGON_CHAIN_ID = 137; // Polygon Mainnet (137 em decimal)

// Configuração dos tipos EIP-712 para Assinatura Sem Gás (Off-Chain)
const EIP712_TYPES = {
  Ordem: [
    { name: 'criador', type: 'address' },
    { name: 'valorUSDC', type: 'uint256' }, // Serve para BRN ou USDC (usando 18 ou 6 decimais)
    { name: 'cotacao', type: 'uint256' },
    { name: 'nonce', type: 'uint256' },
    { name: 'expiracao', type: 'uint256' }
  ]
};

// ==========================================================================
// 1. CONEXÃO COM A CARTEIRA WEB3 (METAMASK OU CARTEIRA BRN)
// ==========================================================================
async function conectarCarteira() {
  if (!window.ethereum) {
    alert("Por favor, instale uma carteira Web3 compatível (MetaMask ou Carteira BRN).");
    return;
  }

  try {
    // Solicita acesso às contas
    provider = new ethers.providers.Web3Provider(window.ethereum);
    await provider.send("eth_requestAccounts", []);
    
    signer = provider.getSigner();
    userAddress = await signer.getAddress();

    // Verifica se o usuário está na rede Polygon
    const network = await provider.getNetwork();
    if (network.chainId !== POLYGON_CHAIN_ID) {
      alert("Por favor, mude a sua carteira para a rede Polygon Mainnet!");
    }

    // Atualiza a interface gráfica
    const element = document.getElementById("walletAddress");
    if (element) {
      element.innerText = `Conectado: ${userAddress.substring(0, 6)}...${userAddress.substring(38)}`;
      element.style.color = "#38bdf8";
    }

    console.log("Carteira Conectada:", userAddress);
  } catch (error) {
    console.error("Erro ao conectar carteira:", error);
    alert("Erro ao conectar à carteira.");
  }
}

// ==========================================================================
// 2. CRIAÇÃO E ASSINATURA DA ORDEM OFF-CHAIN (CUSTO R$ 0,00 DE GÁS)
// ==========================================================================
async function assinarEPublicarOrdem() {
  if (!signer) {
    alert("Conecte sua carteira primeiro!");
    return;
  }

  // Captura os dados digitados na interface
  const inputValor = document.getElementById("valorUSDC").value; // Quantidade de BRN
  const inputCotacao = document.getElementById("cotacao").value;   // Cotação R$
  const inputPix = document.getElementById("chavePix").value;       // Chave PIX

  if (!inputValor || !inputCotacao || !inputPix) {
    alert("Preencha todos os campos do formulário!");
    return;
  }

  try {
    const network = await provider.getNetwork();

    // Estrutura do Domínio EIP-712
    const domain = {
      name: 'CarteiraBRN_P2P',
      version: '1',
      chainId: network.chainId,
      verifyingContract: CONTRATO_ESCROW_ADDRESS
    };

    const nonce = Date.now(); // Identificador único da ordem
    const expiracao = Math.floor(Date.now() / 1000) + (30 * 60); // Válido por 30 minutos
    
    // Converte o valor digitado para a precisão da moeda (18 casas decimais para BRN)
    const valorEmWei = ethers.utils.parseUnits(inputValor, 18).toString();
    const cotacaoEmCentavos = Math.floor(parseFloat(inputCotacao) * 100);

    const ordemData = {
      criador: userAddress,
      valorUSDC: valorEmWei,
      cotacao: cotacaoEmCentavos,
      nonce: nonce,
      expiracao: expiracao
    };

    console.log("Solicitando assinatura off-chain na carteira...");

    // Solicitando Assinatura Sem Taxa de Gás
    const assinatura = await signer._signTypedData(domain, EIP712_TYPES, ordemData);

    // Empacota a ordem completa com os dados PIX
    const payload = {
      type: 'NEW_ORDER',
      payload: {
        ordemData: ordemData,
        assinatura: assinatura,
        chavePix: inputPix,
        valorFormatado: inputValor,
        cotacaoFormatada: inputCotacao
      }
    };

    // Envia a ordem assinada para o servidor Python via WebSocket
    if (webSocket && webSocket.readyState === WebSocket.OPEN) {
      webSocket.send(JSON.stringify(payload));
      alert("Ordem assinada digitalmente e publicada no mural! (Custo: R$ 0,00)");
    } else {
      alert("Erro: O servidor de sincronização em Python está desconectado.");
    }

  } catch (error) {
    console.error("Erro ao assinar a ordem:", error);
    alert("A assinatura foi cancelada ou rejeitada na carteira.");
  }
}

// ==========================================================================
// 3. COMUNICAÇÃO WEBSOCKET COM O SERVIDOR PYTHON NO UBUNTU
// ==========================================================================
function iniciarConexaoWebSocket() {
  // Conecta ao servidor Python local
  webSocket = new WebSocket('ws://localhost:3000');

  webSocket.onopen = () => {
    console.log("Conectado ao Servidor Python da Carteira BRN!");
    const statusElem = document.getElementById("statusConexao");
    if (statusElem) {
      statusElem.innerText = "Sincronizador P2P: ONLINE";
      statusElem.style.color = "#4ade80";
    }
  };

  webSocket.onmessage = (event) => {
    try {
      const resposta = JSON.parse(event.data);
      if (resposta.type === 'SYNC_ORDERS') {
        renderizarMuralDeOrdens(resposta.data);
      }
    } catch (e) {
      console.error("Erro ao ler dados do servidor:", e);
    }
  };

  webSocket.onclose = () => {
    console.warn("Conexão WebSocket perdida. Tentando reconectar em 3 segundos...");
    const statusElem = document.getElementById("statusConexao");
    if (statusElem) {
      statusElem.innerText = "Sincronizador P2P: DESCONECTADO (Tentando Reconectar...)";
      statusElem.style.color = "#f87171";
    }
    setTimeout(iniciarConexaoWebSocket, 3000);
  };
}

// ==========================================================================
// 4. ATUALIZAÇÃO DA INTERFACE VISUAL DO LIVRO DE ORDENS
// ==========================================================================
function renderizarMuralDeOrdens(ordens) {
  const mural = document.getElementById("muralOrdens");
  if (!mural) return;

  mural.innerHTML = "";

  if (ordens.length === 0) {
    mural.innerHTML = '<p style="color: #94a3b8;">Nenhuma ordem ativa no momento.</p>';
    return;
  }

  ordens.forEach((item) => {
    const valorBRN = ethers.utils.formatUnits(item.ordemData.valorUSDC, 18);
    const cotacaoBRL = (item.ordemData.cotacao / 100).toFixed(2);

    mural.innerHTML += `
      <div class="order-item" style="background:#0f172a; padding:15px; border-radius:8px; margin-bottom:10px; border-left:4px solid #38bdf8;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <div>
            <strong style="color:#f8fafc; font-size:1.1rem;">Venda de ${valorBRN} BRN</strong><br>
            <span style="color:#94a3b8; font-size:0.9rem;">Cotação: R$ ${cotacaoBRL} | PIX: ${item.chavePix}</span><br>
            <small style="color:#64748b;">Criador: ${item.ordemData.criador.substring(0,6)}...${item.ordemData.criador.substring(38)}</small>
          </div>
          <div>
            <button onclick="comprarEExecutar('${item.id}')" style="padding:8px 16px; background:#0284c7; color:#fff; border:none; border-radius:5px; cursor:pointer;">
              Comprar / Pagar PIX
            </button>
          </div>
        </div>
      </div>
    `;
  });
}

function comprarEExecutar(idOrdem) {
  alert(`Iniciando negociação para a Ordem ID: ${idOrdem}.\n\nTransfira o valor via PIX diretamente para o vendedor antes da liberação dos tokens.`);
}

// Inicia a escuta do WebSocket assim que a página carregar
window.onload = iniciarConexaoWebSocket;
