import socket
import threading
import datetime
import sys

LISTEN_PORT = 2223
# REMOTE = ("27.131.76.20", 2223)
REMOTE = ("192.168.0.30", 2223)
LOG_FILE = "smarttemp_hub.log"

class Logger:
    def __init__(self, filename):
        self.file = open(filename, "a", encoding="utf-8")
        self.lock = threading.Lock()

    def log(self, message):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        formatted_msg = f"[{timestamp}] {message}\n"
        with self.lock:
            self.file.write(formatted_msg)
            self.file.flush()
            # Also print to console so you can see it happening
            if "ASC:" in message or "Connection" in message:
                sys.stdout.write(formatted_msg)
                sys.stdout.flush()

logger = Logger(LOG_FILE)

def pipe(src, dst, label):
    try:
        while True:
            data = src.recv(1024)
            if not data:
                logger.log(f"[{label}] Connection closed")
                break
            
            # 1. Hex representation for bit-perfect analysis
            hex_data = data.hex(' ')
            
            # 2. ASCII representation for JSON readability
            try:
                # Replace control chars so the log file remains readable
                ascii_data = data.decode('ascii', errors='replace').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
            except Exception:
                ascii_data = "[NON-ASCII]"

            logger.log(f"[{label}] RAW: {hex_data}")
            logger.log(f"[{label}] ASC: {ascii_data}")
            
            dst.sendall(data)
    except Exception as e:
        logger.log(f"[{label}] Error: {e}")
    finally:
        src.close()
        dst.close()

def handle(c, addr):
    logger.log(f"[NEW CONN] {addr}")
    try:
        s = socket.create_connection(REMOTE, timeout=10)
        threading.Thread(target=pipe, args=(c, s, "DEV→CLOUD"), daemon=True).start()
        threading.Thread(target=pipe, args=(s, c, "CLOUD→DEV"), daemon=True).start()
    except Exception as e:
        logger.log(f"[CONN ERROR] Could not connect to Cloud: {e}")
        c.close()

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", LISTEN_PORT))
    sock.listen(5)
    logger.log(f"Proxy started. Listening on port {LISTEN_PORT}. Logging to {LOG_FILE}")

    try:
        while True:
            c, addr = sock.accept()
            handle(c, addr)
    except KeyboardInterrupt:
        logger.log("Proxy stopping...")
    finally:
        sock.close()

if __name__ == "__main__":
    main()