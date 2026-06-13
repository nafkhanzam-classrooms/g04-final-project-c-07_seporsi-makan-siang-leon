class HTTPRequest:
    def __init__(self, method, path, version, headers, header_len):
        self.method = method
        self.path = path
        self.version = version
        self.headers = headers
        self.header_len = header_len

    def header(self, name, default=""):
        return self.headers.get(name.lower(), default)

    def is_websocket_upgrade(self):
        return ("websocket" in self.header("upgrade").lower()
                and self.header("sec-websocket-key") != "")


def parse_request(data: bytes):
    idx = data.find(b"\r\n\r\n")
    if idx == -1:
        return None
    header_len = idx + 4
    head = data[:idx].decode("latin1", "replace")
    lines = head.split("\r\n")
    request_line = lines[0].split(" ")
    if len(request_line) < 2:
        return None
    method = request_line[0]
    path = request_line[1]
    version = request_line[2] if len(request_line) > 2 else "HTTP/1.1"

    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    return HTTPRequest(method, path, version, headers, header_len)


def build_response(body: bytes,
                   content_type: str = "text/html; charset=utf-8",
                   status: str = "200 OK") -> bytes:
    if isinstance(body, str):
        body = body.encode("utf-8")
    head = (
        f"HTTP/1.1 {status}\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Cache-Control: no-cache\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    return head + body
