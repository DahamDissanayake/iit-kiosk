"""Tiny sd_notify for Type=notify units and WatchdogSec (no extra dependency)."""

import os
import socket


def notify(message: str) -> None:
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr or not hasattr(socket, "AF_UNIX"):
        return
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        sock.sendto(message.encode(), addr)
