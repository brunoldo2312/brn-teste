╔═══════════════════════════════════════════════════════════╗
║                  ECOSSISTEMA BRN                          ║
╠═══════════════════════════════════════════════════════════╣
║                                                           ║
║  🏢 CAMADA 2 (BRN-L2) — EVM, Smart Contracts             ║
║  ┌─────────────────────────────────────────────────────┐  ║
║  │  • Tokens ERC-20 (BRN, USDT, USDC, SHIB...)         │  ║
║  │  • DeFi (swaps, lending, staking)                   │  ║
║  │  • NFTs, DAOs                                        │  ║
║  │  • Contratos inteligentes                           │  ║
║  │  • Interface amigável (MetaMask, web3.js)           │  ║
║  └─────────────────────────────────────────────────────┘  ║
║                           ▲                               ║
║                           │  bridge / rollup              ║
║                           ▼                               ║
║  ⛓️  CAMADA 1 (BRN) — UTXO, PoW, Consenso                 ║
║  ┌─────────────────────────────────────────────────────┐  ║
║  │  • Moeda nativa BRN                                  │  ║
║  │  • Segurança por mineração (PoW)                    │  ║
║  │  • Imutabilidade, descentralização                  │  ║
║  │  • Halving, tail emission                           │  ║
║  │  • Base para ancorar a L2                           │  ║
║  └─────────────────────────────────────────────────────┘  ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
blockchain.py                    ← Core PoW
bruno_blockchain_real.py         ← Implementação real
db.py                            ← SQLite (UTXO)
wallet.py / cripto_wallet.py     ← Carteira ECDSA
p2p.py / cripto_p2p_network.py   ← Rede P2P
main.py / main_gui.py            ← App desktop
node.py                          ← Nó da rede

web3, eth-account, coincurve     ← Stack Ethereum
ckzg, lru-dict                    ← EIP-4844
flask, pywebview                  ← API + GUI
index.html                        ← Frontend



1. Usuário baixa a carteira BRN (main_gui.py)
                  │
                  ▼
2. Minera BRN na L1 (ou compra)
                  │
                  ▼
3. Quer usar em DeFi → abre a bridge
                  │
                  ▼
4. BRN é travado na L1, cunhado como wBRN na L2
                  │
                  ▼
5. Conecta MetaMask na BRN-L2
                  │
                  ▼
6. Faz swaps, staking, NFTs, empréstimos...
                  │
                  ▼
7. Quer sacar → queima wBRN na L2
                  │
                  ▼
8. Bridge libera BRN nativo na L1
