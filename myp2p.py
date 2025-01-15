import socket
import threading
import time
import sys

###############################################################################
#                                  TRACKER                                    #
###############################################################################
class Tracker:
    """
    Servidor Tracker que registra, desregistra e lista peers,
    faz buscas (SEARCH) e agora inclui suporte a KEEPALIVE.
    
    self.peers = {
      peer_id: {
         "ip": <str>,
         "port": <int>,
         "files": [<str>, ...],
         "last_keepalive": <float>  # time.time() da última vez que o peer enviou KEEPALIVE
      }
    }
    """

    def __init__(self, host="0.0.0.0", port=5000):
        self.host = host
        self.port = port
        self.peers = {}  # dicionário para manter informações dos peers
        self.lock = threading.Lock()

    def start(self):
        """
        Inicia o servidor e aguarda conexões. Também inicia a thread
        que remove peers inativos por falta de KEEPALIVE.
        """
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.bind((self.host, self.port))
        server_sock.listen(5)
        print(f"[TRACKER] Servindo em {self.host}:{self.port}")

        # Inicia a thread de limpeza de inativos (daemon=True para não bloquear)
        t = threading.Thread(target=self.remove_inactive_peers, daemon=True)
        t.start()

        while True:
            conn, addr = server_sock.accept()
            # Cria uma thread para cada conexão
            threading.Thread(target=self.handle_client, args=(conn, addr)).start()

    def remove_inactive_peers(self, timeout=60):
        """
        A cada 10s, verifica se algum peer ficou tempo demais sem enviar KEEPALIVE.
        Se passar de 'timeout' segundos sem keepalive, remove o peer por inatividade.
        """
        while True:
            time.sleep(10)
            now = time.time()
            with self.lock:
                remove_list = []
                for pid, info in self.peers.items():
                    last_k = info.get("last_keepalive", None)
                    if not last_k:
                        # Se não tiver keepalive registrado, pode ser que tenha acabado de registrar
                        # ou o peer não implementou keepalive. Decida remover ou não.
                        continue

                    if now - last_k > timeout:
                        remove_list.append(pid)

                for peer_id in remove_list:
                    del self.peers[peer_id]
                    print(f"[TRACKER] Peer '{peer_id}' removido por inatividade (KEEPALIVE).")

    def handle_client(self, conn, addr):
        """
        Recebe um comando do Peer e executa:
          REGISTER, UNREGISTER, SEARCH, GET_PEERS, KEEPALIVE
        """
        try:
            data = conn.recv(4096).decode().strip()
            if not data:
                return

            parts = data.split()
            cmd = parts[0].upper()

            # Opcional: log do comando
            print(f"[TRACKER] Recebeu comando: '{data}' de {addr}")

            if cmd == "REGISTER":
                # Formato: REGISTER <peer_id> <ip> <port> [files]
                if len(parts) >= 4:
                    peer_id = parts[1]
                    peer_ip = parts[2]
                    peer_port = parts[3]

                    file_list = []
                    if len(parts) == 5:
                        file_list = parts[4].split(",") if parts[4] else []

                    with self.lock:
                        if peer_id in self.peers:
                            print(f"[TRACKER] Peer '{peer_id}' tentou REGISTER, mas já está registrado.")
                            conn.sendall(b"ALREADY_REGISTERED\n")
                        else:
                            self.peers[peer_id] = {
                                "ip": peer_ip,
                                "port": int(peer_port),
                                "files": file_list,
                                "last_keepalive": time.time()  # registra o horario do registro
                            }
                            print(f"[TRACKER] Peer '{peer_id}' registrado em {peer_ip}:{peer_port}. "
                                  f"Arquivos: {file_list}")
                            conn.sendall(b"REGISTER_OK\n")
                else:
                    conn.sendall(b"ERROR Uso: REGISTER <peer_id> <ip> <port> [files]\n")

            elif cmd == "UNREGISTER":
                # Formato: UNREGISTER <peer_id>
                if len(parts) == 2:
                    peer_id = parts[1]
                    with self.lock:
                        if peer_id in self.peers:
                            del self.peers[peer_id]
                            print(f"[TRACKER] Peer '{peer_id}' desconectado via UNREGISTER.")
                            conn.sendall(b"UNREGISTER_OK\n")
                        else:
                            conn.sendall(b"ERROR Uso: UNREGISTER <peer_id>\n")
                else:
                    conn.sendall(b"ERROR Uso: UNREGISTER <peer_id>\n")

            elif cmd == "SEARCH":
                # Formato: SEARCH <filename>
                if len(parts) == 2:
                    filename = parts[1]
                    result = []
                    with self.lock:
                        for pid, info in self.peers.items():
                            if filename in info["files"]:
                                result.append((pid, info["ip"], info["port"]))

                    if result:
                        resp = f"SEARCH_RESULT {len(result)}\n"
                        for (pid, ip, port) in result:
                            resp += f"{pid} {ip} {port}\n"
                        conn.sendall(resp.encode())
                    else:
                        conn.sendall(b"SEARCH_RESULT 0\n")
                else:
                    conn.sendall(b"ERROR Uso: SEARCH <filename>\n")

            elif cmd == "GET_PEERS":
                # Formato: GET_PEERS
                with self.lock:
                    resp = f"PEER_LIST {len(self.peers)}\n"
                    for pid, info in self.peers.items():
                        resp += f"{pid} {info['ip']} {info['port']} {info['files']}\n"
                conn.sendall(resp.encode())

            elif cmd == "KEEPALIVE":
                # Formato: KEEPALIVE <peer_id>
                if len(parts) == 2:
                    peer_id = parts[1]
                    with self.lock:
                        if peer_id in self.peers:
                            self.peers[peer_id]["last_keepalive"] = time.time()
                            print(f"[TRACKER] Peer '{peer_id}' enviou KEEPALIVE.")
                            conn.sendall(b"KEEPALIVE_OK\n")
                        else:
                            conn.sendall(b"ERROR Peer nao encontrado para KEEPALIVE\n")
                else:
                    conn.sendall(b"ERROR Uso: KEEPALIVE <peer_id>\n")

            else:
                conn.sendall(b"ERROR Comando desconhecido\n")

        except Exception as e:
            print(f"[TRACKER] Erro ao processar comando: {e}")
        finally:
            conn.close()

###############################################################################
#                                   PEER                                      #
###############################################################################
class Peer:
    """
    Classe Peer que se registra no Tracker, envia KeepAlive periodicamente,
    e pode executar:
      - REGISTER
      - UNREGISTER
      - SEARCH <filename>
      - GET_PEERS

    A cada 30s, envia 'KEEPALIVE <peer_id>' ao Tracker.
    """

    def __init__(self, peer_id, tracker_ip, tracker_port, files=None):
        self.peer_id = self.format_peer_id(peer_id)
        self.tracker_ip = tracker_ip
        self.tracker_port = tracker_port

        self.ip = self.get_local_ip()  # detecta IP local
        self.port = self.compute_port_from_id(self.peer_id)
        self.files = files if files else []

        print(f"[PEER-{self.peer_id}] IP local: {self.ip}, Porta local: {self.port}")

        # (Opcional) Thread para mandar KEEPALIVE a cada 30s
        self.keepalive_thread = threading.Thread(target=self._keepalive_loop, daemon=True)
        self.keepalive_thread.start()

    def format_peer_id(self, pid_str):
        """
        Se o usuário digitar "1", vira "PEER1".
        Se digitar "PEER2", mantém "PEER2".
        """
        if pid_str.upper().startswith("PEER"):
            return pid_str.upper()
        else:
            return f"PEER{pid_str}"

    def compute_port_from_id(self, peer_id):
        """
        Extrai o dígito do peer_id (ex.: 'PEER2' -> 2)
        e retorna 6000 + esse número. Se não tiver dígito, retorna 6000.
        """
        numeric_part = ''.join(filter(str.isdigit, peer_id))
        if numeric_part:
            return 6000 + int(numeric_part)
        else:
            return 6000

    def get_local_ip(self):
        """
        Tenta descobrir o IP local, conectando no DNS do Google (8.8.8.8).
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
        finally:
            s.close()
        return local_ip

    def _keepalive_loop(self, interval=30):
        """
        Thread que envia KEEPALIVE ao Tracker a cada 'interval' segundos.
        """
        while True:
            time.sleep(interval)
            self.send_keepalive()

    def send_keepalive(self):
        """
        Envia 'KEEPALIVE <peer_id>' ao Tracker. 
        Imprime a resposta (KEEPALIVE_OK ou erro).
        """
        msg = f"KEEPALIVE {self.peer_id}"
        resp = self._send_msg_to_tracker(msg)
        print("[PEER] Resposta KEEPALIVE:", resp)

    def register(self):
        """
        Envia REGISTER <peer_id> <ip> <port> [files]
        """
        msg = f"REGISTER {self.peer_id} {self.ip} {self.port}"
        if self.files:
            files_str = ",".join(self.files)
            msg += f" {files_str}"
        resp = self._send_msg_to_tracker(msg)
        print("[PEER] Resposta REGISTER:", resp)

    def unregister(self):
        """
        Envia UNREGISTER <peer_id>
        """
        msg = f"UNREGISTER {self.peer_id}"
        resp = self._send_msg_to_tracker(msg)
        print("[PEER] Resposta UNREGISTER:", resp)

    def search(self, filename):
        """
        Envia SEARCH <filename> ao Tracker e exibe os resultados.
        """
        msg = f"SEARCH {filename}"
        resp = self._send_msg_to_tracker(msg)
        if not resp:
            print("[PEER] Erro: Resposta vazia do tracker.")
            return
        lines = resp.splitlines()
        if lines[0].startswith("SEARCH_RESULT"):
            num = int(lines[0].split()[1])
            if num == 0:
                print(f"[PEER] Nenhum peer possui '{filename}'.")
            else:
                print(f"[PEER] {num} peer(s) possuem '{filename}':")
                for line in lines[1:]:
                    print("  ", line)
        else:
            print("[PEER] Resposta inesperada:", resp)

    def get_peers(self):
        """
        Envia GET_PEERS ao Tracker e mostra todos os peers registrados.
        """
        msg = "GET_PEERS"
        resp = self._send_msg_to_tracker(msg)
        if not resp:
            print("[PEER] Erro: Resposta vazia do tracker.")
            return
        lines = resp.splitlines()
        if lines[0].startswith("PEER_LIST"):
            print(f"[PEER] Peers registrados:")
            for line in lines[1:]:
                print("  ", line)
        else:
            print("[PEER] Resposta inesperada:", resp)

    def _send_msg_to_tracker(self, msg):
        """
        Função auxiliar para enviar um comando ao Tracker e retornar a resposta.
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((self.tracker_ip, self.tracker_port))
            sock.sendall((msg + "\n").encode())
            resp = sock.recv(4096).decode()
            sock.close()
            return resp.strip()
        except Exception as e:
            print(f"[PEER] Erro ao comunicar com tracker: {e}")
            return ""

###############################################################################
#                                 FUNÇÕES MAIN                                #
###############################################################################
def run_tracker():
    """
    Inicia apenas o Tracker (porta 5000) e começa a remover peers inativos
    se eles não enviarem KEEPALIVE.
    """
    tracker = Tracker(host="0.0.0.0", port=5000)
    tracker.start()

def run_peer():
    """
    Inicia um Peer, perguntando:
      - Peer ID
      - Tracker IP
      - Tracker Porta
      - Lista de arquivos
    
    O Peer envia KEEPALIVE a cada 30s por padrão.
    """
    print("=== Iniciando Peer ===")
    pid = input("Digite um Peer ID (ex: 1 ou PEER1): ").strip()
    tip = input("Tracker IP (ex: 127.0.0.1): ").strip()
    tport = input("Tracker Port (ex: 5000): ").strip()
    files_str = input("Arquivos compartilhados (ex: file1.txt,file2.jpg) ou vazio: ").strip()

    files_list = files_str.split(",") if files_str else []

    p = Peer(pid, tip, int(tport), files=files_list)

    while True:
        print("\nComandos disponíveis:")
        print("  1 - REGISTER")
        print("  2 - UNREGISTER")
        print("  3 - SEARCH <filename>")
        print("  4 - GET_PEERS")
        print("  5 - SAIR")
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
            # Antes de sair, vamos unregister para aparecer no tracker que desconectou
            p.unregister()
            print("Encerrando Peer...")
            break
        else:
            print("Opção inválida. Digite 1, 2, 3, 4 ou 5.")

if __name__ == "__main__":
    """
    Uso:
      python myp2p.py tracker
        -> Inicia o Tracker e aceita comandos REGISTER, UNREGISTER, SEARCH, GET_PEERS, KEEPALIVE.

      python myp2p.py peer
        -> Inicia um Peer que pode se registrar no Tracker e enviar KEEPALIVE periodicamente.
    """
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
