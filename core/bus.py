"""Local ZeroMQ links between kiosk services (baseline 7.2): [topic, JSON] frames."""

import json

import zmq
import zmq.asyncio


class Publisher:
    def __init__(self, ctx: zmq.asyncio.Context, endpoint: str) -> None:
        self.sock = ctx.socket(zmq.PUB)
        self.sock.setsockopt(zmq.SNDHWM, 100)
        self.sock.setsockopt(zmq.LINGER, 0)
        self.sock.bind(endpoint)

    async def publish(self, topic: str, payload: dict) -> None:
        await self.sock.send_multipart([topic.encode(), json.dumps(payload).encode()])

    def close(self) -> None:
        self.sock.close()


class Subscriber:
    """ZeroMQ filters by prefix, so recv() also checks the topic matches exactly."""

    def __init__(self, ctx: zmq.asyncio.Context, endpoints: list[str], topics: list[str]) -> None:
        self.topics = set(topics)
        self.sock = ctx.socket(zmq.SUB)
        self.sock.setsockopt(zmq.RCVHWM, 100)
        self.sock.setsockopt(zmq.LINGER, 0)
        for endpoint in endpoints:
            self.sock.connect(endpoint)
        for topic in topics:
            self.sock.setsockopt(zmq.SUBSCRIBE, topic.encode())

    async def recv(self) -> tuple[str, dict]:
        while True:
            raw_topic, raw = await self.sock.recv_multipart()
            topic = raw_topic.decode()
            if topic in self.topics:
                return topic, json.loads(raw)

    def close(self) -> None:
        self.sock.close()
