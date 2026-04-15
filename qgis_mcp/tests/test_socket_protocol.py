"""
Smoke tests for the length-prefixed socket protocol.

These tests spin up a minimal mock server and verify that
QgisSocketClient can send/receive framed messages correctly.
"""

import json
import socket
import struct
import threading
import time

import pytest

# QgisSocketClient is importable via conftest.py sys.path setup
from qgis_socket_client import QgisSocketClient

_HEADER_FMT = "!I"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)


def _echo_server(port: int, ready: threading.Event, stop: threading.Event):
    """Minimal echo server that reads a framed command and replies with a
    framed JSON response containing ``{"status": "success", "result": <cmd>}``."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("localhost", port))
    srv.listen(1)
    srv.settimeout(5)
    ready.set()

    try:
        conn, _ = srv.accept()
        while not stop.is_set():
            # Read header
            header = b""
            while len(header) < _HEADER_SIZE:
                chunk = conn.recv(_HEADER_SIZE - len(header))
                if not chunk:
                    return
                header += chunk

            (msg_len,) = struct.unpack(_HEADER_FMT, header)
            body = b""
            while len(body) < msg_len:
                chunk = conn.recv(msg_len - len(body))
                if not chunk:
                    return
                body += chunk

            command = json.loads(body.decode("utf-8"))
            response = {"status": "success", "result": command}
            resp_bytes = json.dumps(response).encode("utf-8")
            conn.sendall(struct.pack(_HEADER_FMT, len(resp_bytes)) + resp_bytes)
    finally:
        srv.close()


@pytest.fixture()
def echo_port():
    """Start an echo server on a random port and yield the port number."""
    port = 0
    # Find a free port
    with socket.socket() as s:
        s.bind(("localhost", 0))
        port = s.getsockname()[1]

    ready = threading.Event()
    stop = threading.Event()
    t = threading.Thread(target=_echo_server, args=(port, ready, stop), daemon=True)
    t.start()
    ready.wait(timeout=3)
    yield port
    stop.set()
    t.join(timeout=3)


def test_ping_roundtrip(echo_port):
    client = QgisSocketClient(host="localhost", port=echo_port)
    assert client.connect()
    result = client.send_command("ping")
    assert result is not None
    assert result["status"] == "success"
    assert result["result"]["type"] == "ping"
    client.disconnect()


def test_command_with_params(echo_port):
    client = QgisSocketClient(host="localhost", port=echo_port)
    assert client.connect()
    result = client.send_command("load_project", {"path": "/tmp/test.qgz"})
    assert result["result"]["params"]["path"] == "/tmp/test.qgz"
    client.disconnect()
