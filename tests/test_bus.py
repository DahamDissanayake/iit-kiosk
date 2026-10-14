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
