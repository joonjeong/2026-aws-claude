import asyncio
import json

from datalake.cli import _common
from datalake.cli.aisstream import run_stream
from datalake.core.env import env_float, env_int, env_str
from datalake.core.source import Record
from datalake.sources.aisstream import AisStreamClient


class ListSink:
    def __init__(self):
        self.records = []

    def write(self, records):
        self.records.extend(records)


class FailingSink:
    def write(self, records):
        raise RuntimeError("boom")


def _rec():
    return Record(source="fake", kind="k", payload={"v": 1})


def test_emit_isolates_sink_failure():
    good = ListSink()
    n = _common.emit([FailingSink(), good], [_rec()])
    assert n == 1
    assert len(good.records) == 1  # 앞 싱크가 죽어도 뒤 싱크는 받는다


def test_emit_empty_is_noop():
    assert _common.emit([ListSink()], []) == 0


# ── env 헬퍼 (labkit 대체 자체 구현) ─────────────────────────
def test_env_helpers(monkeypatch):
    monkeypatch.setenv("X_STR", "abc")
    monkeypatch.setenv("X_INT", "42")
    monkeypatch.setenv("X_BAD", "not-a-number")
    assert env_str("X_STR", "d") == "abc"
    assert env_str("X_MISSING", "d") == "d"
    assert env_int("X_INT", 0) == 42
    assert env_int("X_BAD", 7) == 7      # 비정상 값은 조용히 기본값
    assert env_float("X_BAD", 1.5) == 1.5
    assert env_float("X_MISSING", 2.5) == 2.5


# ── wake 스트림 CLI 경로 (connect 주입 — 실소켓 없음) ────────
class FakeWS:
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


async def test_run_stream_duration_bounded():
    ws = FakeWS([json.dumps({
        "MessageType": "PositionReport",
        "MetaData": {"MMSI": 1},
        "Message": {"PositionReport": {"Latitude": 36.0, "Longitude": 129.0}},
    })])

    async def connect(url):
        return ws

    sink = ListSink()
    client = AisStreamClient(api_key="K", preset="kr")
    n = await run_stream(client, [sink], duration_s=0.3, flush_s=0.05,
                         connect=connect)
    assert n == 1
    assert len(sink.records) == 1
    assert sink.records[0].kind == "wake"
    assert json.loads(ws.sent[0])["APIKey"] == "K"  # 구독 프레임 전송됨
