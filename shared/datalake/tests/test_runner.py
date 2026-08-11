import asyncio
import json

from datalake.core.runner import Runner
from datalake.core.source import Job, Record


class ListSink:
    def __init__(self):
        self.records = []

    def write(self, records):
        self.records.extend(records)


class FailingSink:
    def write(self, records):
        raise RuntimeError("boom")


class FakePoll:
    id = "fake"

    def jobs(self):
        async def fetch():
            return [Record(source="fake", kind="k", payload={"v": 1})]

        return [Job("fake-job", 60.0, fetch)]


class BadPoll:
    id = "bad"

    def jobs(self):
        async def fetch():
            raise RuntimeError("upstream down")

        return [Job("bad-job", 60.0, fetch)]


async def test_run_once_delivers_to_sinks():
    sink = ListSink()
    runner = Runner([FakePoll()], [], [sink])
    n = await runner.run_once()
    assert n == 1
    assert len(sink.records) == 1
    assert sink.records[0].kind == "k"


async def test_sink_failure_is_isolated():
    good = ListSink()
    runner = Runner([FakePoll()], [], [FailingSink(), good])
    n = await runner.run_once()
    assert n == 1
    assert len(good.records) == 1  # 앞 싱크가 죽어도 뒤 싱크는 받는다


async def test_fetch_failure_is_isolated():
    sink = ListSink()
    runner = Runner([BadPoll(), FakePoll()], [], [sink])
    n = await runner.run_once()
    assert n == 1  # bad 0건 + fake 1건, 예외 전파 없음


class FakeStreamSource:
    id = "fs"
    url = "wss://example.invalid/stream"

    def subscribe_payload(self):
        return {"APIKey": "secret", "BoundingBoxes": [[[30, 120], [45, 135]]]}

    def parse(self, msg):
        return [Record(source="fs", kind="ais", payload=msg)]


class FakeWS:
    """메시지 소진 후 접속 유지(무한 대기) — 재접속 루프 방지."""

    def __init__(self, messages):
        self._msgs = list(messages)
        self.sent = []

    async def send(self, data):
        self.sent.append(data)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._msgs:
            return self._msgs.pop(0)
        await asyncio.Event().wait()

    async def close(self):
        pass


async def test_stream_subscribe_buffer_flush():
    sink = ListSink()
    ws = FakeWS([json.dumps({"MessageType": "PositionReport"})])

    async def connect(url):
        return ws

    runner = Runner([], [FakeStreamSource()], [sink], flush_s=3600, connect=connect)
    await runner.start()
    try:
        # 메시지가 버퍼에 들어오거나, 기동 직후 플러시 틱(labkit 폴러는 첫
        # 사이클을 즉시 실행)이 이미 싱크로 내보냈거나 — 둘 중 하나까지 대기
        for _ in range(100):
            if runner.buffered() >= 1 or sink.records:
                break
            await asyncio.sleep(0.01)
        assert json.loads(ws.sent[0])["APIKey"] == "secret"  # 구독 프레임 전송됨
        runner.flush()  # 수동 플러시로 잔여 버퍼 드레인 → 총 1건이어야 함
        assert len(sink.records) == 1
        assert sink.records[0].payload == {"MessageType": "PositionReport"}
        assert runner.buffered() == 0
    finally:
        await runner.stop()
