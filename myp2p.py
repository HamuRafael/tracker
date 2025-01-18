import socket
import threading
import time
import sys


class Tracker:
    

    def __init__(self, host="0.0.0.0", port=5000):
        self.host = host
        self.port = port
        self.peers = {}  
        self.lock = threading.Lock()

    def start(self):
        
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
        
        while True:
            time.sleep(10)
            now = time.time()
            with self.lock:
                remove_list = []
                for pid, info in self.peers.items():
                    last_k = info.get("last_keepalive", None)
                    if not last_k:
                        # Se não tiver keepalive registrado, pode ser que tenha acabado de registrar
                        # ou o peer não implementou keepalive.
                        continue

                    if now - last_k > timeout:
                        remove_list.append(pid)

                for peer_id in remove_list:
                    del self.peers[peer_id]
                    print(f"[TRACKER] Peer '{peer_id}' removido por inatividade (KEEPALIVE).")

    def handle_client(self, conn, addr):
        
        try:
            data = conn.recv(4096).decode().strip()
            if not data:
                return

            parts = data.split()
            cmd = parts[0].upper()


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

class Peer:
    

    def __init__(self, peer_id, tracker_ip, tracker_port, files=None):
        self.peer_id = self.format_peer_id(peer_id)
        self.tracker_ip = tracker_ip
        self.tracker_port = tracker_port

        self.ip = self.get_local_ip()  # detecta IP local
        self.port = self.compute_port_from_id(self.peer_id)
        self.files = files if files else []

        print(f"[PEER-{self.peer_id}] IP local: {self.ip}, Porta local: {self.port}")

        self.keepalive_thread = threading.Thread(target=self._keepalive_loop, daemon=True)
        self.keepalive_thread.start()

    def format_peer_id(self, pid_str):
        
        if pid_str.upper().startswith("PEER"):
            return pid_str.upper()
        else:
            return f"PEER{pid_str}"

    def compute_port_from_id(self, peer_id):
        
        numeric_part = ''.join(filter(str.isdigit, peer_id))
        if numeric_part:
            return 6000 + int(numeric_part)
        else:
            return 6000

    def get_local_ip(self):
        
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
        finally:
            s.close()
        return local_ip

    def _keepalive_loop(self, interval=30):
        
        while True:
            time.sleep(interval)
            self.send_keepalive()

    def send_keepalive(self):
        
        msg = f"KEEPALIVE {self.peer_id}"
        resp = self._send_msg_to_tracker(msg)
        print("[PEER] Resposta KEEPALIVE:", resp)

    def register(self):
        
        msg = f"REGISTER {self.peer_id} {self.ip} {self.port}"
        if self.files:
            files_str = ",".join(self.files)
            msg += f" {files_str}"
        resp = self._send_msg_to_tracker(msg)
        print("[PEER] Resposta REGISTER:", resp)

    def unregister(self):
        
        msg = f"UNREGISTER {self.peer_id}"
        resp = self._send_msg_to_tracker(msg)
        print("[PEER] Resposta UNREGISTER:", resp)

    def search(self, filename):
        
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
            
            p.unregister()
            print("Encerrando Peer...")
            break
        else:
            print("Opção inválida. Digite 1, 2, 3, 4 ou 5.")

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
