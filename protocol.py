import base64
import hashlib
import struct

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONT = 0x0
OP_TEXT = 0x1
OP_BIN = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


def compute_accept(key: str) -> str:
    digest = hashlib.sha1((key + WS_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def handshake_response(key: str) -> bytes:
    return (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {compute_accept(key)}\r\n\r\n"
    ).encode("ascii")


def _frame(payload: bytes, opcode: int) -> bytes:
    b1 = 0x80 | (opcode & 0x0F)
    n = len(payload)
    if n < 126:
        header = struct.pack("!BB", b1, n)
    elif n < 65536:
        header = struct.pack("!BBH", b1, 126, n)
    else:
        header = struct.pack("!BBQ", b1, 127, n)
    return header + payload


def encode_text(text: str) -> bytes:
    return _frame(text.encode("utf-8"), OP_TEXT)


def encode_pong(data: bytes = b"") -> bytes:
    return _frame(data, OP_PONG)


def encode_close(code: int = 1000) -> bytes:
    return _frame(struct.pack("!H", code), OP_CLOSE)


class FrameBuffer:
    def __init__(self):
        self.buf = bytearray()
        self._frag_op = None
        self._frag = bytearray()

    def feed(self, data: bytes):
        self.buf.extend(data)

    def messages(self):
        out = []
        while True:
            frame = self._take_frame()
            if frame is None:
                break
            fin, opcode, payload = frame
            if opcode == OP_CLOSE:
                out.append(("close", payload))
            elif opcode == OP_PING:
                out.append(("ping", payload))
            elif opcode == OP_PONG:
                out.append(("pong", payload))
            else:
                if opcode == OP_CONT:
                    self._frag.extend(payload)
                else:
                    self._frag_op = opcode
                    self._frag = bytearray(payload)
                if fin:
                    op = self._frag_op
                    raw = bytes(self._frag)
                    self._frag_op, self._frag = None, bytearray()
                    if op == OP_TEXT:
                        out.append(("text", raw.decode("utf-8", "replace")))

        return out

    def _take_frame(self):
        b = self.buf
        if len(b) < 2:
            return None
        b0, b1 = b[0], b[1]
        fin = bool(b0 & 0x80)
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        length = b1 & 0x7F
        idx = 2
        if length == 126:
            if len(b) < idx + 2:
                return None
            length = struct.unpack_from("!H", b, idx)[0]
            idx += 2
        elif length == 127:
            if len(b) < idx + 8:
                return None
            length = struct.unpack_from("!Q", b, idx)[0]
            idx += 8
        mask = None
        if masked:
            if len(b) < idx + 4:
                return None
            mask = b[idx:idx + 4]
            idx += 4
        if len(b) < idx + length:
            return None
        payload = bytearray(b[idx:idx + length])
        idx += length
        if masked:
            for i in range(length):
                payload[i] ^= mask[i & 3]
        del b[:idx]
        return fin, opcode, bytes(payload)
