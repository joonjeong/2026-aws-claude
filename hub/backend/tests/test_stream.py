"""StreamCollector: 구독 전송·메시지 격리·재접속 백오프 — fake ws로 검증."""
import asyncio
import json

from labkit.stream import StreamCollector


class FakeWS:
    def __init__(self, messages):
        self.sent: list[str] = []
        self._messages = list(messages)
        self.closed = False

    async def send(self, data):
        self.sent.append(data)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            await asyncio.sleep(3600)  # 연결 유지 상태 흉내 (stop()이 취소)
        return self._messages.pop(0)

    async def close(self):
        self.closed = True


async def test_subscribe_sent_and_bad_message_isolated():
    ws = FakeWS(['{"MessageType":"PositionReport"}', "not-json", '{"a":1}'])
    got = []

    async def connect(url):
        return ws

    c = StreamCollector(
        "t", "wss://x", got.append,
        subscribe=lambda: {"APIKey": "k"}, connect=connect,
    )
    c.start()
    await asyncio.sleep(0.05)
    c.stop()
    await asyncio.sleep(0)
    assert json.loads(ws.sent[0]) == {"APIKey": "k"}
    # 비JSON 1건은 격리되고 나머지 2건 전달
    assert got == [{"MessageType": "PositionReport"}, {"a": 1}]
    assert c.status["msg_count"] == 3
    assert c.status["connected"] is False  # stop 후


async def test_reconnect_with_backoff_on_connect_failure():
    attempts = []

    async def connect(url):
        attempts.append(1)
        raise OSError("refused")

    c = StreamCollector("t", "wss://x", lambda m: None,
                        backoff_initial_s=0.01, backoff_max_s=0.02, connect=connect)
    c.start()
    await asyncio.sleep(0.08)
    c.stop()
    assert len(attempts) >= 2
    assert c.status["reconnects"] >= 2
    assert "refused" in (c.status["last_error"] or "")


async def test_resubscribe_sends_on_live_socket():
    ws = FakeWS([])

    async def connect(url):
        return ws

    payloads = iter([{"box": "kr"}, {"box": "taiwan"}])
    c = StreamCollector("t", "wss://x", lambda m: None,
                        subscribe=lambda: next(payloads), connect=connect)
    c.start()
    await asyncio.sleep(0.02)
    c.resubscribe()
    await asyncio.sleep(0.02)
    c.stop()
    assert [json.loads(s) for s in ws.sent] == [{"box": "kr"}, {"box": "taiwan"}]
