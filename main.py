
import json
import sys
from cripto_wallet import WalletManager


def json_pretty(d): return json.dumps(d, indent=2, ensure_ascii=False)


def menu():
    print("\n=== BRN Bruno - Carteira CLI ===")
    print("1 - Gerar nova carteira")
    print("2 - Salvar carteira cifrada")
    print("3 - Carregar carteira")
    print("4 - Listar carteiras")
    print("5 - Validar endereco")
    print("6 - Sair")
    return input("Escolha: ").strip()


def main():
    while True:
        try: op = menu()
        except (KeyboardInterrupt, EOFError):
            print("\nEncerrando."); return 0
        try:
            if op == "1":
                w = WalletManager.generate_keypair()
                print(json_pretty(w))
                print("\nGUARDE a 'spend_secret_key' com seguranca.")
            elif op == "2":
                name = input("Nome: ").strip()
                pwd  = input("Senha (>=12): ")
                addr = input("Endereco: ").strip()
                sk   = input("Chave privada: ").strip()
                pk   = input("Chave publica: ").strip()
                print(json_pretty(WalletManager.save_encrypted_wallet(
                    name, pwd, addr, sk, pk)))
            elif op == "3":
                name = input("Nome: ").strip()
                pwd  = input("Senha: ")
                r = WalletManager.load_encrypted_wallet(name, pwd)
                if r.get("status") == "sucesso":
                    print(f"\nEndereco: {r['address']}")
                    print(f"SK: {r['spend_secret_key'][:8]}... (oculta)")
                else:
                    print(f"\nErro: {r.get('message')}")
            elif op == "4":
                ws = WalletManager.list_wallets()
                print("\n" + ("\n".join("  " + w for w in ws) if ws else "(vazio)"))
            elif op == "5":
                a = input("Endereco: ").strip()
                print("Valido" if WalletManager.validate_address(a) else "Invalido")
            elif op == "6":
                print("Encerrando."); return 0
            else:
                print("Opcao invalida.")
        except KeyboardInterrupt:
            print("\nCancelado.")
        except Exception as e:
            print(f"Erro: {e}")


if __name__ == "__main__":
    sys.exit(main())
