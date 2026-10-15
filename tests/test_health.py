import asyncio
import socket

from core.admin.health import NetProbe, systemd_restarts


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_probe_reports_reachable_when_something_listens():
    async def go():
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            return await NetProbe("127.0.0.1", port).check()
        finally:
            server.close()
            await server.wait_closed()

    assert asyncio.run(go()) is True


def test_probe_reports_unreachable_when_nothing_listens():
    assert asyncio.run(NetProbe("127.0.0.1", free_port()).check()) is False


def test_probe_state_starts_unknown_then_updates_in_the_background():
    async def go():
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        probe = NetProbe("127.0.0.1", server.sockets[0].getsockname()[1], every_s=0.05)
        before = probe.ok
        probe.start()
        await asyncio.sleep(0.3)
        await probe.stop()
        server.close()
        await server.wait_closed()
        return before, probe.ok, probe.checked_at

    before, after, checked_at = asyncio.run(go())
    assert before is None and after is True and checked_at is not None


def test_restart_count_is_a_number_or_nothing_and_never_raises():
    # No systemd (laptop): None. Linux with systemd: systemctl reports 0 even for an unknown unit.
    # Either way the page shows a count or "n/a", never an error.
    result = systemd_restarts("kiosk-core-does-not-exist")
    assert result is None or (isinstance(result, int) and result >= 0)
