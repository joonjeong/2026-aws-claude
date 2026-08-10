"""SIMULATED order book + investor flows (clearly labeled: "simulated": true).

Real order-book / investor-flow feeds are paid; the lab bonus asks for
plausible, DETERMINISTIC simulations instead:

- Order book seeds its RNG from the current price (int(price * 100)), so the
  same price always yields the identical book (verifiable determinism).
- Investor flows seed one RNG per (symbol, date) from a sha256 digest —
  Python's built-in hash() is salted per process, sha256 keeps values stable
  across refreshes AND server restarts.
"""
from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta
from typing import Any

from .kr import is_kr_symbol

_LEVELS = 10


def _tick(price: float, kr: bool) -> float:
    """Sensible price-proportional step (~0.1%); KR prices stay integral."""
    if kr:
        return float(max(1, int(price * 0.001)))
    return max(0.01, round(price * 0.001, 2))


def build_orderbook(symbol: str, price: float, volume: int) -> dict[str, Any]:
    kr = is_kr_symbol(symbol)
    rng = random.Random(int(price * 100))  # same price -> identical book
    tick = _tick(price, kr)
    base_vol = max(volume // 200, 100)

    def level(i: int, sign: int) -> dict[str, Any]:
        p = price + sign * tick * i
        return {
            "price": float(int(round(p))) if kr else round(p, 2),
            "volume": int(base_vol * rng.uniform(0.2, 1.8)),
        }

    asks = [level(i, +1) for i in range(1, _LEVELS + 1)]
    bids = [level(i, -1) for i in range(1, _LEVELS + 1)]
    asks.reverse()  # 최고가부터 (highest ask first); bids already highest-first
    return {
        "symbol": symbol,
        "price": price,
        "simulated": True,
        "asks": asks,
        "bids": bids,
    }


def _day_rng(symbol: str, day: str) -> random.Random:
    digest = hashlib.sha256(f"{symbol}:{day}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def build_investor_flows(symbol: str, volume: int) -> dict[str, Any]:
    """Last 10 weekdays of net-buy flows, ~60/30/10 magnitude split
    (개인/외국인/기관); individual ≈ -(foreign + institution) with noise."""
    base = max(volume, 10_000)
    days: list[dict[str, Any]] = []
    d = date.today()
    while len(days) < 10:
        if d.weekday() < 5:  # weekdays only
            day = d.strftime("%Y-%m-%d")
            rng = _day_rng(symbol, day)
            foreign = rng.uniform(-1.0, 1.0) * 0.30 * base
            institution = rng.uniform(-1.0, 1.0) * 0.10 * base
            # inverted direction; ×~1.5 lifts |individual| toward the 60% share
            individual = -(foreign + institution) * rng.uniform(1.3, 1.7)
            days.append({
                "date": day,
                "individual": int(individual),
                "foreign": int(foreign),
                "institution": int(institution),
            })
        d -= timedelta(days=1)
    days.reverse()  # oldest first
    return {"symbol": symbol, "simulated": True, "days": days}
