"""
Socket client that communicates with the QGIS MCP plugin over TCP.

Supports two framing modes:
1. **Length-prefixed** (default) — 4-byte big-endian header + JSON payload.
2. **Raw JSON** (legacy) — plain JSON, response terminated by valid JSON parse.
"""

import json
import socket
import struct


_HEADER_FMT = "!I"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)


class QgisSocketClient:
    """Persistent TCP client for the QGIS MCP plugin socket server."""

    # Timeout for recv operations (seconds). Prevents indefinite hangs on
    # large payloads or unresponsive servers.
    RECV_TIMEOUT = 120

    def __init__(self, host: str = "localhost", port: int = 9876):
        self.host = host
        self.port = port
        self.socket: socket.socket | None = None

    def connect(self) -> bool:
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.RECV_TIMEOUT)
            self.socket.connect((self.host, self.port))
            return True
        except Exception as e:
            print(f"Error connecting to server: {e}")
            return False

    def disconnect(self) -> None:
        if self.socket:
            self.socket.close()
            self.socket = None

    def send_command(self, command_type: str, params: dict | None = None) -> dict | None:
        """Send a framed JSON command and return the parsed response."""
        if not self.socket:
            print("Not connected to server")
            return None

        command = {"type": command_type, "params": params or {}}
        payload = json.dumps(command).encode("utf-8")

        try:
            # Send with length-prefix
            self.socket.sendall(struct.pack(_HEADER_FMT, len(payload)) + payload)

            # Read response — length-prefixed
            header = self._recv_exact(_HEADER_SIZE)
            if header is None:
                return self._recv_raw_json()  # fallback
            (msg_len,) = struct.unpack(_HEADER_FMT, header)
            body = self._recv_exact(msg_len)
            if body is None:
                return None
            return json.loads(body.decode("utf-8"))
        except Exception as e:
            print(f"Error sending command: {e}")
            return None

    # ── helpers ─────────────────────────────────────────────────────────────

    def _recv_exact(self, n: int) -> bytes | None:
        """Read exactly *n* bytes from the socket."""
        data = b""
        while len(data) < n:
            chunk = self.socket.recv(n - len(data))
            if not chunk:
                return None
            data += chunk
        return data

    def _recv_raw_json(self) -> dict | None:
        """Fallback: accumulate until valid JSON."""
        buf = b""
        while True:
            chunk = self.socket.recv(4096)
            if not chunk:
                return None
            buf += chunk
            try:
                return json.loads(buf.decode("utf-8"))
            except json.JSONDecodeError:
                continue
