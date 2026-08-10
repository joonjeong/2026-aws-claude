"""labkit smoke test — run: python smoke.py (expects all OK lines)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from labkit import (
    BedrockError,
    IdempotentStore,
    PollingCollector,
    SnapshotRingBuffer,
    TTLCache,
    converse,
    time_bucket,
)


def check(name: str, cond: bool) -> None:
    print(f"{'OK ' if cond else 'FAIL'} {name}")
    if not cond:
        sys.exit(1)


async def main() -> None:
    # IdempotentStore: new/update semantics + eviction of oldest
    store = IdempotentStore(max_items=3, evict_key=lambda it: it["t"])
    check("store: first upsert is new", store.upsert("a", {"t": 1}) is True)
    check("store: same key is update", store.upsert("a", {"t": 9}) is False)
    for k, t in [("b", 2), ("c", 3), ("d", 4)]:
        store.upsert(k, {"t": t})
    check("store: capped at max_items", len(store) == 3)
    check("store: evicted oldest (b, t=2)", store.get("b") is None and store.get("d") is not None)

    # SnapshotRingBuffer: bucket idempotency + latest/previous + capacity
    ring = SnapshotRingBuffer(capacity=3)
    check("ring: first put accepted", ring.put(100, "s1") is True)
    check("ring: same bucket rejected", ring.put(100, "dup") is False)
    ring.put(101, "s2"); ring.put(102, "s3"); ring.put(103, "s4")
    check("ring: capacity enforced", len(ring) == 3)
    check("ring: latest", ring.latest() == (103, "s4"))
    check("ring: previous", ring.previous() == (102, "s3"))

    # TTLCache: single-flight — 5 concurrent gets, 1 upstream call
    cache = TTLCache()
    calls = 0
    async def fetch():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return "value"
    results = await asyncio.gather(*(cache.get_or_fetch("k", 10, fetch) for _ in range(5)))
    check("cache: all callers got value", all(r == "value" for r in results))
    check("cache: single-flight (1 upstream call)", calls == 1)

    # time_bucket: stable within same window
    check("time_bucket: deterministic", time_bucket(600, 1234567) == 1234567 // 600)

    # PollingCollector: failure isolation — bad cycle recorded, next succeeds
    flag = {"fail": True}
    got = []
    async def flaky():
        if flag["fail"]:
            raise RuntimeError("boom")
        return 42
    p = PollingCollector("t", 0.01, flaky, on_result=got.append)
    await p.run_once()
    check("poller: failure recorded, no raise", p.consecutive_failures == 1 and "boom" in p.last_error)
    flag["fail"] = False
    await p.run_once()
    check("poller: recovered", p.consecutive_failures == 0 and got == [42] and p.last_success is not None)

    # bedrock: missing token → 503
    os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)
    try:
        await converse("s", "u", 10)
        check("bedrock: missing token raises", False)
    except BedrockError as e:
        check("bedrock: missing token → 503", e.status_code == 503)

    print("ALL OK")


asyncio.run(main())
