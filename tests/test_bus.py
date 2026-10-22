import asyncio

import zmq.asyncio

from core.bus import Publisher, Subscriber


def test_subscriber_gets_only_its_exact_topics():
    async def go():
        ctx = zmq.asyncio.Context()
        pub = Publisher(ctx, "inproc://bus-test")
        sub = Subscriber(ctx, ["inproc://bus-test"], ["stt.final"])
        got = None
        for _ in range(100):  # wait out the ZeroMQ slow-joiner gap
            await pub.publish("stt.partial", {"text": "hel"})
            await pub.publish("stt.final", {"text": "hello"})
            try:
                got = await asyncio.wait_for(sub.recv(), 0.05)
                break
            except TimeoutError:
                continue
        pub.close()
        sub.close()
        ctx.term()
        return got

    assert asyncio.run(go()) == ("stt.final", {"text": "hello"})


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_tcp_pub_sub_works_with_the_event_loop_policy_helper():
    """Real TCP sockets, as the services use: needs the selector loop on Windows."""
    from core.bus import use_selector_loop_on_windows

    use_selector_loop_on_windows()
    endpoint = f"tcp://127.0.0.1:{_free_port()}"

    async def go():
        ctx = zmq.asyncio.Context()
        pub = Publisher(ctx, endpoint)
        sub = Subscriber(ctx, [endpoint], ["presence"])
        got = None
        for _ in range(100):
            await pub.publish("presence", {"count": 1})
            try:
                got = await asyncio.wait_for(sub.recv(), 0.05)
                break
            except TimeoutError:
                continue
        pub.close()
        sub.close()
        ctx.term()
        return got

    assert asyncio.run(go()) == ("presence", {"count": 1})
