import os
import sys
import json
import time
import socket
import select

import http_parser as hp
import protocol as wsp
from coordinator import GameCoordinator, log

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(HERE, "web", "index.html")
HOST = "0.0.0.0"
PORT = 8080
TICK_RATE = 20
TICK_INTERVAL = 1.0 / TICK_RATE


class WSConn:
    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
        self.inbuf = bytearray()
        self.frames = wsp.FrameBuffer()
        self.mode = "http"
        self.outbuf = bytearray()
        self.player_id = None
        self.alive = True
        self.close_after = False

    def send(self, msg):
        if self.alive and self.mode == "ws":
            self.outbuf.extend(wsp.encode_text(json.dumps(msg)))


class WSServer:
    def __init__(self, host=HOST, port=PORT):
        self.host = host
        self.port = port
        self.server_sock = None
        self.clients = {}
        self.coord = GameCoordinator()
        self.last_tick = 0.0
        try:
            with open(INDEX_PATH, "rb") as f:
                self.index_html = f.read()
        except OSError:
            self.index_html = b"<h1>index.html tidak ditemukan</h1>"

    def run(self):
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind((self.host, self.port))
        self.server_sock.listen(32)
        self.server_sock.setblocking(False)
        log("INFO", f"Bomberman server di http://{self.host}:{self.port}")
        self.last_tick = time.time()
        try:
            while True:
                rlist = [self.server_sock] + [c.sock for c in self.clients.values()]
                wlist = [c.sock for c in self.clients.values() if c.outbuf]
                try:
                    readable, writable, _ = select.select(rlist, wlist, [], 0.01)
                except (OSError, ValueError):
                    self._reap()
                    continue
                for s in readable:
                    if s is self.server_sock:
                        self._accept()
                    else:
                        self._on_readable(s)
                for s in writable:
                    self._on_writable(s)
                now = time.time()
                if now - self.last_tick >= TICK_INTERVAL:
                    self.last_tick = now
                    self.coord.tick(now)
        except KeyboardInterrupt:
            log("INFO", "Server dihentikan.")
        finally:
            try:
                self.server_sock.close()
            except OSError:
                pass

    def _accept(self):
        try:
            sock, addr = self.server_sock.accept()
        except OSError:
            return
        sock.setblocking(False)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.clients[sock.fileno()] = WSConn(sock, addr)

    def _on_readable(self, sock):
        c = self.clients.get(sock.fileno())
        if not c:
            try:
                sock.close()
            except OSError:
                pass
            return
        try:
            data = sock.recv(8192)
        except (ConnectionResetError, OSError):
            data = b""
        if not data:
            self._disconnect(c)
            return
        if c.mode == "http":
            self._on_http(c, data)
        else:
            c.frames.feed(data)
            self._process_ws(c)

    def _on_http(self, c, data):
        c.inbuf.extend(data)
        req = hp.parse_request(bytes(c.inbuf))
        if req is None:
            return
        if req.path == "/ws" and req.is_websocket_upgrade():
            key = req.header("sec-websocket-key")
            c.outbuf.extend(wsp.handshake_response(key))
            c.mode = "ws"
            extra = bytes(c.inbuf[req.header_len:])
            c.inbuf = bytearray()
            log("INFO", f"WebSocket tersambung dari {c.addr[0]}:{c.addr[1]}")
            if extra:
                c.frames.feed(extra)
                self._process_ws(c)
        elif req.path in ("/", "/index.html"):
            c.outbuf.extend(hp.build_response(self.index_html))
            c.close_after = True
        else:
            c.outbuf.extend(hp.build_response(b"Not Found",
                            content_type="text/plain", status="404 Not Found"))
            c.close_after = True

    def _process_ws(self, c):
        for kind, payload in c.frames.messages():
            if kind == "text":
                try:
                    msg = json.loads(payload)
                except (ValueError, TypeError):
                    continue
                try:
                    self.coord.on_message(c, msg)
                except Exception as e:
                    log("WARN", f"Gagal memproses {msg.get('type')}: {e}")
            elif kind == "ping":
                c.outbuf.extend(wsp.encode_pong(payload))
            elif kind == "close":
                self._disconnect(c)
                return

    def _on_writable(self, sock):
        c = self.clients.get(sock.fileno())
        if not c or not c.outbuf:
            return
        try:
            sent = sock.send(c.outbuf)
            del c.outbuf[:sent]
        except BlockingIOError:
            return
        except (ConnectionResetError, OSError):
            self._disconnect(c)
            return
        if c.close_after and not c.outbuf:
            self._disconnect(c)

    def _reap(self):
        for fn, c in list(self.clients.items()):
            if (not c.alive) or c.sock.fileno() == -1:
                self.clients.pop(fn, None)

    def _disconnect(self, c):
        if not c.alive:
            return
        c.alive = False
        try:
            self.clients.pop(c.sock.fileno(), None)
            c.sock.close()
        except OSError:
            pass
        self.coord.on_disconnect(c)


def main():
    port = PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    WSServer(port=port).run()


if __name__ == "__main__":
    main()
