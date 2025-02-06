import sys
from tracker import Tracker
from peer import Peer

def run_tracker():
    tracker = Tracker(host="0.0.0.0", port=5000)
    tracker.start()

def run_peer():
    print("=== Iniciando Peer ===")
    pid = input("Digite um Peer ID (ex: 1 ou PEER1): ").strip()
    tip = input("Tracker IP (ex: 127.0.0.1): ").strip()
    tport = input("Tracker Port (ex: 5000): ").strip()
    files_str = input("Arquivos compartilhados (ex: file1.txt,file2.jpg) ou vazio: ").strip()

    files_list = files_str.split(",") if files_str else []

    p = Peer(pid, tip, int(tport), files=files_list)
    p.start_lister()

    while True:
        print("\nComandos disponíveis:")
        print("  1 - REGISTER")
        print("  2 - UNREGISTER")
        print("  3 - SEARCH <filename>")
        print("  4 - GET_PEERS")
        print("  5 - CHAT <peer_ip> <peer_port>")
        print("  6 - DOWNLOAD <peer_ip> <peer_port> <filename> [<num_connections>]")
        print("  7 - SAIR")
        opcao = input("Escolha: ").strip()

        if opcao == "1":
            p.register()
        elif opcao == "2":
            p.unregister()
        elif opcao == "3":
            filename = input("Nome do arquivo: ").strip()
            p.search(filename)
        elif opcao == "4":
            p.get_peers()
        elif opcao == "5":
            target_ip = input("IP do peer destino: ").strip()
            target_port = int(input("Porta do peer destino: ").strip())
            message = input("Mensagem: ").strip()
            p.send_message(target_ip, target_port, message)
        elif opcao == "6":
            target_ip = input("IP do peer destino: ").strip()
            target_port = int(input("Porta do peer destino: ").strip())
            filename = input("Nome do arquivo a baixar: ").strip()
            try:
                num_conn = int(input("Número de conexões paralelas (padrão=2): ").strip())
            except:
                num_conn = 2
            p.request_file(target_ip, target_port, filename, num_connections=num_conn)
        elif opcao == "7":
            p.unregister()
            print("Encerrando Peer...")
            break
        else:
            print("Opção inválida.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Modo de uso:")
        print("  python myp2p.py tracker")
        print("  python myp2p.py peer")
        sys.exit(0)

    mode = sys.argv[1].lower()
    if mode == "tracker":
        run_tracker()
    elif mode == "peer":
        run_peer()
    else:
        print("Modo inválido. Use 'tracker' ou 'peer'.")
