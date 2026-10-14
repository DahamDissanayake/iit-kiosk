import socket
import sys

import pytest

from core.sdnotify import notify


def test_notify_without_socket_is_a_no_op(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    notify("WATCHDOG=1")


@pytest.mark.skipif(sys.platform == "win32", reason="unix sockets")
def test_notify_sends_datagram(tmp_path, monkeypatch):
    path = str(tmp_path / "notify.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.bind(path)
    monkeypatch.setenv("NOTIFY_SOCKET", path)
    notify("READY=1")
    assert server.recv(100) == b"READY=1"
    server.close()
