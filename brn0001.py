# 📦 PROJETO MODULAR COMPLETO: CARTEIRA BRN P2P (EIP-712 OFF-CHAIN)

---

## 📑 ÍNDICE DE MÓDULOS E DIVISÃO DE ARQUIVOS

Para modularizar o projeto no futuro e rodar no seu servidor ou ambiente local, basta picar/recortar o conteúdo abaixo respeitando os marcadores de início e fim de cada módulo.

| Módulo | Arquivo de Destino | Tecnologia | Função no Sistema |
| :--- | :--- | :--- | :--- |
| **Módulo 1** | `EscrowP2POffChain.sol` | Solidity (v0.8.20) | Contrato inteligente para deploy na rede Polygon. |
| **Módulo 2** | `server.py` | Python 3 | Servidor WebSocket/HTTP para rodar no Ubuntu. |
| **Módulo 3** | `index.html` | HTML5 / CSS3 | Interface visual completa com painel e mural P2P. |
| **Módulo 4** | `app.js` | JavaScript (Ethers.js v5) | Lógica Web3, assinaturas EIP-712 e WebSocket client. |

---

<!-- INÍCIO DO MÓDULO 1: CONTRATO INTELIGENTE SOLIDITY -->
## 🧱 MÓDULO 1: SMART CONTRACT (`EscrowP2POffChain.sol`)

> **Caminho para salvar:** `./contracts/EscrowP2POffChain.sol`  
> **Uso:** Copie o trecho abaixo para compilar no Remix IDE ou Hardhat e faça o deploy na Polygon.

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IERC20 {
    function transferFrom(address sender, address recipient, uint256 amount) external returns (bool);
    function transfer(address recipient, uint256 amount) external returns (bool);
}

contract EscrowP2POffChain {
    address public admin;
    IERC20 public usdcToken;

    uint256 public taxaAplicacao = 100; // 1% (100 pontos base)
    uint256 public constant BASE_PORCENTAGEM = 10000;

    bytes32 public constant EIP712_DOMAIN_TYPEHASH = 
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");
    bytes32 public constant ORDEM_TYPEHASH = 
        keccak256("Ordem(address criador,uint256 valorUSDC,uint256 cotacao,uint256 nonce,uint256 expiracao)");

    bytes32 public DOMAIN_SEPARATOR;

    // Proteção contra duplicação de ordens (Replay Attack)
    mapping(address => mapping(uint256 => bool)) public nonceUtilizado;

    event OrdemExecutada(bytes32 indexed hashOrdem, address indexed criador, address indexed comprador, uint256 valorUSDC);
    event OrdemCancelada(address indexed criador, uint256 nonce);

    modifier apenasAdmin() {
        require(msg.sender == admin, "Apenas admin");
        _;
    }

    struct Ordem {
        address payable criador;
        uint256 valorUSDC;
        uint256 cotacao;
        uint256 nonce;
        uint256 expiracao;
    }

    constructor(address _usdcToken, address _admin) {
        usdcToken = IERC20(_usdcToken);
        admin = _admin;

        DOMAIN_SEPARATOR = keccak256(
            abi.encode(
                EIP712_DOMAIN_TYPEHASH,
                keccak256(bytes("CarteiraBRN_P2P")),
                keccak256(bytes("1")),
                block.chainid,
                address(this)
            )
        );
    }

    function getSigner(Ordem memory _ordem, bytes memory _assinatura) public view returns (address) {
        bytes32 structHash = keccak256(
            abi.encode(
                ORDEM_TYPEHASH,
                _ordem.criador,
                _ordem.valorUSDC,
                _ordem.cotacao,
                _ordem.nonce,
                _ordem.expiracao
            )
        );

        bytes32 digest = keccak256(abi.encodePacked("\x19\x01", DOMAIN_SEPARATOR, structHash));
        return recoverSigner(digest, _assinatura);
    }

    function executarOrdem(
        Ordem memory _ordem,
        bytes memory _assinatura,
        address payable _comprador
    ) external {
        require(block.timestamp <= _ordem.expiracao, "Ordem expirada");
        require(!nonceUtilizado[_ordem.criador][_ordem.nonce], "Ordem ja executada ou cancelada");

        address assinadoPor = getSigner(_ordem, _assinatura);
        require(assinadoPor == _ordem.criador, "Assinatura invalida");

        nonceUtilizado[_ordem.criador][_ordem.nonce] = true;

        uint256 valorTaxa = (_ordem.valorUSDC * taxaAplicacao) / BASE_PORCENTAGEM;
        uint256 valorLiquidoComprador = _ordem.valorUSDC - valorTaxa;

        require(usdcToken.transferFrom(_ordem.criador, _comprador, valorLiquidoComprador), "Falha no envio ao comprador");
        if (valorTaxa > 0) {
            require(usdcToken.transferFrom(_ordem.criador, admin, valorTaxa), "Falha no envio da taxa");
        }

        emit OrdemExecutada(keccak256(_assinatura), _ordem.criador, _comprador, _ordem.valorUSDC);
    }

    function cancelarOrdemOffChain(uint256 _nonce) external {
        nonceUtilizado[msg.sender][_nonce] = true;
        emit OrdemCancelada(msg.sender, _nonce);
    }

    function alterarTaxa(uint256 _novaTaxa) external apenasAdmin {
        require(_novaTaxa <= 500, "Taxa maxima 5%");
        taxaAplicacao = _novaTaxa;
    }
}

function recoverSigner(bytes32 _digest, bytes memory _sig) pure returns (address) {
    require(_sig.length == 65, "Assinatura invalida");
    bytes32 r;
    bytes32 s;
    uint8 v;
    assembly {
        r := mload(add(_sig, 32))
        s := mload(add(_sig, 64))
        v := byte(0, mload(add(_sig, 96)))
    }
    return ecrecover(_digest, v, r, s);
}
