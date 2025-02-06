import socket
import threading
import time
import os

class Peer:
    """
    PEER:
      - Registra-se no tracker, envia KEEPALIVE periodicamente.
      - Compartilha lista de arquivos.
      - Responde a mensagens de chat.
      - Agora também responde a pedidos de arquivo (DOWNLOAD).
      - E oferece método para pedir arquivos a outros peers usando múltiplas conexões.
      - Sempre que faz upload, avisa o tracker para incrementar o score.
    """

    def __init__(self, peer_id, tracker_ip, tracker_port, files=None):
        self.peer_id = self.format_peer_id(peer_id)
        self.tracker_ip = tracker_ip
        self.tracker_port = tracker_port

        self.ip = self.get_local_ip()  
        self.port = self.compute_port_from_id(self.peer_id)
        self.files = files if files else []

        print(f"[PEER-{self.peer_id}] IP local: {self.ip}, Porta local: {self.port}")
        
        # Thread para keepalive
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
        # print("[PEER] Resposta KEEPALIVE:", resp)

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
        """Inicia um servidor para receber mensagens de outros peers (chat ou pedido de arquivo)."""
        listener = threading.Thread(target=self._listen_for_messages, daemon=True)
        listener.start()

    def _listen_for_messages(self):
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.bind((self.ip, self.port))
        server_sock.listen(5)
        print(f"[PEER-{self.peer_id}] Escutando mensagens em {self.ip}:{self.port}")

        while True:
            conn, addr = server_sock.accept()
            threading.Thread(target=self._handle_peer_message, args=(conn, addr)).start()

    def _handle_peer_message(self, conn, addr):
        """
        Processa mensagens recebidas de outro peer:
          - Mensagens de chat
          - Solicitação FILE_SIZE
          - Solicitação DOWNLOAD (bloco de um arquivo)
        """
        try:
            msg = conn.recv(4096).decode().strip()
            if not msg:
                return

            # Vamos analisar a 1a palavra (comando).
            parts = msg.split()
            cmd = parts[0].upper()

            if cmd == "CHAT":  # Exemplo de mensagem de chat
                # Formato: CHAT <mensagem>
                mensagem = " ".join(parts[1:])
                print(f"[CHAT] Mensagem recebida de {addr}: {mensagem}")

            elif cmd == "FILE_SIZE":
                # FILE_SIZE <filename>
                if len(parts) == 2:
                    filename = parts[1]
                    self._handle_file_size_request(conn, filename)
                else:
                    conn.sendall(b"ERROR Uso: FILE_SIZE <filename>\n")

            elif cmd == "DOWNLOAD":
                # DOWNLOAD <filename> <start> <end>
                if len(parts) == 4:
                    filename = parts[1]
                    start = int(parts[2])
                    end = int(parts[3])
                    self._handle_file_download_request(conn, filename, start, end)
                else:
                    conn.sendall(b"ERROR Uso: DOWNLOAD <filename> <start> <end>\n")

            else:
                # Se não reconhece, consideramos como mensagem de chat normal
                print(f"[CHAT] Mensagem (desconhecida) de {addr}: {msg}")

        finally:
            conn.close()

    def send_message(self, target_ip, target_port, message):
        """Envia uma mensagem de chat para outro peer."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.connect((target_ip, target_port))
                cmd_msg = f"CHAT {message}"
                sock.sendall(cmd_msg.encode())
                print(f"[CHAT] Mensagem enviada para {target_ip}:{target_port}: {message}")
        except Exception as e:
            print(f"[CHAT] Erro ao enviar mensagem: {e}")

    def request_file(self, target_ip, target_port, filename, num_connections=2):
        download_dir = "downloads"
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)
        # 1) Obter tamanho do arquivo
        file_size = self._get_file_size(target_ip, target_port, filename)
        if file_size <= 0:
            print(f"[DOWNLOAD] Arquivo '{filename}' não encontrado ou erro no peer.")
            return

        print(f"[DOWNLOAD] Tamanho do arquivo '{filename}': {file_size} bytes. Iniciando download em {num_connections} conexões...")

        # Nome do arquivo que vamos salvar localmente
        local_filename = os.path.join(download_dir, filename)

        # Cria um buffer (array de bytes) na memória ou utiliza um arquivo aberto para escrita
        # Vamos direto usar um arquivo e posicionar com seek() para escrever no lugar certo
        with open(local_filename, "wb") as f:
            f.truncate(file_size)  # Garante tamanho

        # 2) Dividir em blocos e criar threads
        chunk_size = file_size // num_connections
        threads = []
        for i in range(num_connections):
            start = i * chunk_size
            # Último chunk vai até o final
            end = (file_size if i == num_connections - 1 else (start + chunk_size))

            t = threading.Thread(
                target=self._download_chunk,
                args=(target_ip, target_port, filename, start, end, local_filename, i)
            )
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        print(f"[DOWNLOAD] Download de '{filename}' concluído. Salvo em '{local_filename}'.")

    def _download_chunk(self, target_ip, target_port, filename, start, end, local_filename, idx):

        
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.connect((target_ip, target_port))
                cmd = f"DOWNLOAD {filename} {start} {end}"
                sock.sendall(cmd.encode())

                total_bytes = end - start
                received = 0
                data_chunks = []
                while received < total_bytes:
                    chunk = sock.recv(min(4096, total_bytes - received))
                    if not chunk:
                        break
                    data_chunks.append(chunk)
                    received += len(chunk)

            # Escreve o bloco na posição correta dentro do arquivo na pasta de downloads
            with open(local_filename, "rb+") as f:
                f.seek(start)
                f.write(b"".join(data_chunks))

            print(f"[DOWNLOAD] Chunk #{idx} (bytes {start}-{end}) baixado com sucesso.")
        except Exception as e:
            print(f"[DOWNLOAD] Erro ao baixar chunk #{idx} do arquivo '{filename}': {e}")

    def _get_file_size(self, target_ip, target_port, filename):
        """
        Faz a requisição FILE_SIZE <filename> e aguarda resposta do peer: "FILE_SIZE_OK <size>".
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.connect((target_ip, target_port))
                cmd = f"FILE_SIZE {filename}"
                sock.sendall(cmd.encode())

                resp = sock.recv(1024).decode().strip()
                if resp.startswith("FILE_SIZE_OK"):
                    # FILE_SIZE_OK <size>
                    parts = resp.split()
                    size = int(parts[1])
                    return size
                else:
                    print("[DOWNLOAD] Resposta inesperada ao FILE_SIZE:", resp)
                    return -1
        except Exception as e:
            print(f"[DOWNLOAD] Erro ao obter FILE_SIZE: {e}")
            return -1

    def _handle_file_size_request(self, conn, filename):
        """
        Envia o tamanho do arquivo (se existir localmente).
        """
        if filename in self.files and os.path.exists(filename):
            size = os.path.getsize(filename)
            resp = f"FILE_SIZE_OK {size}\n"
            conn.sendall(resp.encode())
        else:
            # Arquivo não encontrado ou não compartilhado
            conn.sendall(b"ERROR FILE NOT FOUND\n")

    def _handle_file_download_request(self, conn, filename, start, end):
        """
        Envia o conteúdo do arquivo (ou bloco) do disco para o peer solicitante.
        Também podemos aplicar aqui qualquer limitação de banda ou lógica de incentivo.
        """
        if filename in self.files and os.path.exists(filename):
            file_size = os.path.getsize(filename)
            if start < 0: start = 0
            if end > file_size: end = file_size

            length = end - start
            if length <= 0:
                conn.sendall(b"")  # Nada para mandar
                return

            # LEITURA DO BLOCO
            with open(filename, "rb") as f:
                f.seek(start)
                data = f.read(length)

            # (Opcional) Exemplo de limitação de taxa:
            # Se quisermos "punir" peers com baixo score, poderíamos fazer:
            #   time.sleep(algum_calculo_baseado_no_score)
            # Mas aqui faremos algo simples (sem delay).

            # Envia o bloco de dados
            conn.sendall(data)

            # Agora, incrementamos nosso score no Tracker, pois fizemos um upload.
            # Aqui, consideramos a quantidade de bytes "length" para pontuar.
            self._increment_score(length)

        else:
            conn.sendall(b"ERROR FILE NOT FOUND\n")

    def _increment_score(self, delta):
        """
        Envia comando INCREMENT_SCORE <peer_id> <delta> para o tracker,
        de modo a aumentar nossa 'reputação' ou 'pontuação'.
        """
        msg = f"INCREMENT_SCORE {self.peer_id} {delta}"
        _ = self._send_msg_to_tracker(msg)

    def _send_msg_to_tracker(self, msg):
        """Encapsula o envio de mensagens ao tracker."""
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
