import socket
import threading
import time
import sys

class Tracker:
    """
    TRACKER:
      - Mantém uma lista de peers (peer_id => {ip, port, files, last_keepalive, score}).
      - Responde a comandos de registro, busca, etc.
      - Remove peers inativos.
      - Agora também mantém uma 'pontuação' (score) de cada peer.
    """

    def __init__(self, host="0.0.0.0", port=5000):
        self.host = host
        self.port = port
        self.peers = {}  # { peer_id: {"ip":..., "port":..., "files":[], "last_keepalive":..., "score":...} }
        self.lock = threading.Lock()

    def start(self):
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.bind((self.host, self.port))
        server_sock.listen(5)
        print(f"[TRACKER] Servindo em {self.host}:{self.port}")

        # Inicia a thread de remoção de inativos
        t = threading.Thread(target=self.remove_inactive_peers, daemon=True)
        t.start()

        while True:
            conn, addr = server_sock.accept()
            threading.Thread(target=self.handle_client, args=(conn, addr)).start()

    def remove_inactive_peers(self, timeout=60):
        """
        Remove peers que não mandam KEEPALIVE dentro do 'timeout' (padrão: 60s).
        """
        while True:
            time.sleep(10)
            now = time.time()
            with self.lock:
                remove_list = []
                for pid, info in self.peers.items():
                    last_k = info.get("last_keepalive", None)
                    if not last_k:
                        # Se não tiver keepalive, pode ser que tenha acabado de registrar
                        continue
                    if now - last_k > timeout:
                        remove_list.append(pid)

                for peer_id in remove_list:
                    del self.peers[peer_id]
                    print(f"[TRACKER] Peer '{peer_id}' removido por inatividade (KEEPALIVE).")

    def handle_client(self, conn, addr):
        """
        Recebe um comando do peer e responde adequadamente.
        """
        try:
            data = conn.recv(4096).decode().strip()
            if not data:
                return

            parts = data.split()
            cmd = parts[0].upper()

            print(f"[TRACKER] Recebeu comando: '{data}' de {addr}")

            if cmd == "REGISTER":
                # REGISTER <peer_id> <ip> <port> [files]
                if len(parts) >= 4:
                    peer_id = parts[1]
                    peer_ip = parts[2]
                    peer_port = parts[3]

                    file_list = []
                    if len(parts) == 5:
                        file_list = parts[4].split(",") if parts[4] else []

                    with self.lock:
                        if peer_id in self.peers:
                            print(f"[TRACKER] Peer '{peer_id}' já registrado.")
                            conn.sendall(b"ALREADY_REGISTERED\n")
                        else:
                            self.peers[peer_id] = {
                                "ip": peer_ip,
                                "port": int(peer_port),
                                "files": file_list,
                                "last_keepalive": time.time(),
                                "score": 0  # Inicializa o score
                            }
                            print(f"[TRACKER] Peer '{peer_id}' registrado em {peer_ip}:{peer_port}. "
                                  f"Arquivos: {file_list}")
                            conn.sendall(b"REGISTER_OK\n")
                else:
                    conn.sendall(b"ERROR Uso: REGISTER <peer_id> <ip> <port> [files]\n")

            elif cmd == "UNREGISTER":
                # UNREGISTER <peer_id>
                if len(parts) == 2:
                    peer_id = parts[1]
                    with self.lock:
                        if peer_id in self.peers:
                            del self.peers[peer_id]
                            print(f"[TRACKER] Peer '{peer_id}' desconectado via UNREGISTER.")
                            conn.sendall(b"UNREGISTER_OK\n")
                        else:
                            conn.sendall(b"ERROR Peer nao encontrado\n")
                else:
                    conn.sendall(b"ERROR Uso: UNREGISTER <peer_id>\n")

            elif cmd == "SEARCH":
                # SEARCH <filename>
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
                # GET_PEERS
                with self.lock:
                    resp = f"PEER_LIST {len(self.peers)}\n"
                    for pid, info in self.peers.items():
                        resp += f"{pid} {info['ip']} {info['port']} {info['files']} Score={info['score']}\n"
                conn.sendall(resp.encode())

            elif cmd == "KEEPALIVE":
                # KEEPALIVE <peer_id>
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

            elif cmd == "INCREMENT_SCORE":
                # INCREMENT_SCORE <peer_id> <delta>
                if len(parts) == 3:
                    peer_id = parts[1]
                    delta = int(parts[2])
                    with self.lock:
                        if peer_id in self.peers:
                            self.peers[peer_id]["score"] += delta
                            print(f"[TRACKER] Score de '{peer_id}' incrementado em {delta}. Novo score = {self.peers[peer_id]['score']}")
                            conn.sendall(b"INCREMENT_OK\n")
                        else:
                            conn.sendall(b"ERROR Peer nao encontrado para INCREMENT_SCORE\n")
                else:
                    conn.sendall(b"ERROR Uso: INCREMENT_SCORE <peer_id> <delta>\n")

            else:
                conn.sendall(b"ERROR Comando desconhecido\n")

        except Exception as e:
            print(f"[TRACKER] Erro ao processar comando: {e}")
        finally:
            conn.close()
