"""Small local Chrome driver for browser smoke tests without extra packages."""
import base64
import json
import os
import socket
import struct
import subprocess
import time


class Browser:
    def __init__(self, executable, profile):
        self.process = subprocess.Popen(
            [executable, "--headless", "--no-sandbox", "--disable-gpu", "--no-first-run",
             "--remote-debugging-port=0", "--user-data-dir=" + str(profile), "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        self.sock = None
        try:
            active = profile / "DevToolsActivePort"
            for _ in range(100):
                if active.exists():
                    break
                time.sleep(.05)
            port, path = active.read_text().splitlines()
            self.sock = socket.create_connection(("127.0.0.1", int(port)), timeout=15)
            key = base64.b64encode(os.urandom(16)).decode()
            self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                               f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                               "Sec-WebSocket-Version: 13\r\n\r\n").encode())
            header = b""
            while not header.endswith(b"\r\n\r\n"):
                chunk = self.sock.recv(1)
                if not chunk:
                    raise RuntimeError("Chrome websocket handshake closed")
                header += chunk
            if not header.startswith(b"HTTP/1.1 101 "):
                raise RuntimeError("Chrome websocket handshake failed")
            self.serial = 0
            target = self.call("Target.createTarget", {"url": "about:blank"})["targetId"]
            self.session = self.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        except Exception:
            self.close()
            raise

    def exact(self, size):
        data = b""
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise RuntimeError("Chrome websocket closed")
            data += chunk
        return data

    def call(self, method, params=None, page=False):
        self.serial += 1
        message = {"id": self.serial, "method": method, "params": params or {}}
        if page:
            message["sessionId"] = self.session
        payload = json.dumps(message).encode()
        mask = os.urandom(4)
        length = len(payload)
        if length < 126:
            frame = bytes([0x81, 0x80 | length])
        elif length <= 65535:
            frame = bytes([0x81, 0x80 | 126]) + struct.pack("!H", length)
        else:
            frame = bytes([0x81, 0x80 | 127]) + struct.pack("!Q", length)
        self.sock.sendall(frame + mask + bytes(value ^ mask[index % 4] for index, value in enumerate(payload)))
        while True:
            first, second = self.exact(2)
            size = second & 127
            if size == 126:
                size = struct.unpack("!H", self.exact(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self.exact(8))[0]
            result = json.loads(self.exact(size))
            if result.get("id") == self.serial:
                if "error" in result:
                    raise RuntimeError(str(result["error"]))
                return result["result"]

    def value(self, expression):
        result = self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True}, page=True)
        if result.get("exceptionDetails"):
            raise RuntimeError(str(result["exceptionDetails"]))
        return result["result"].get("value", "")

    def close(self):
        if self.sock:
            self.sock.close()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
