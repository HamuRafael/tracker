import socket
import threading
import time
import sys


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
    
    def start_lister(self):
        "Inicia um servidor para receber mensagens de outros peers"
        listener = threading.Thread(target=self._listen_for_messages, daemon = True)
        listener.start()

    def _listen_for_messages(self):
        "Escuta mensagens de outros peers"
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.bind((self.ip,self.port))
        server_sock.listen(5)
        print(f"[PEER-{self.peer_id}] Escutando mensagens em {self.ip}:{self.port}")

        while True:
            conn, addr = server_sock.accept()
            threading.Thread(target=self._handle_peer_message, args=(conn,addr)).start()

    def _handle_peer_message(self, conn, addr):
        """Processa mensagens recebidas de outro peer."""
        try:
            msg = conn.recv(4096).decode().strip()
            print(f"[CHAT] Mensagem recebida de {addr}: {msg}")
        finally:
            conn.close()
    
    def send_message(self, target_ip, target_port, message):
        """Envia uma mensagem para outro peer."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.connect((target_ip, target_port))
                sock.sendall(message.encode())
                print(f"[CHAT] Mensagem enviada para {target_ip}:{target_port}: {message}")
        except Exception as e:
            print(f"[CHAT] Erro ao enviar mensagem: {e}")


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
