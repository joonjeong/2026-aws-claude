"""Derivations: rank delta / NEW / exited vs the previous snapshot,
category shares, and the time-series points for /api/trends."""
from __future__ import annotations

from collections import Counter
from typing import Any


def derive_items(
    latest_items: list[dict[str, Any]],
    previous_items: list[dict[str, Any]] | None,
    category_names: dict[str, str],
) -> tuple[list[dict[str, Any]], int]:
    """Returns (annotated items, exited count).

    delta = previous_rank - rank  (positive = moved up / ▲n, negative = ▼n,
    0 = unchanged, None = NEW). exited = ids present before, gone now.
    """
    prev_ranks: dict[str, int] = {}
    if previous_items:
        prev_ranks = {it["video_id"]: i + 1 for i, it in enumerate(previous_items)}

    latest_ids = {it["video_id"] for it in latest_items}
    exited = sum(1 for vid in prev_ranks if vid not in latest_ids)

    annotated: list[dict[str, Any]] = []
    for i, item in enumerate(latest_items):
        rank = i + 1
        prev_rank = prev_ranks.get(item["video_id"])
        is_new = bool(prev_ranks) and prev_rank is None
        annotated.append({
            **item,
            "rank": rank,
            "delta": (prev_rank - rank) if prev_rank is not None else None,
            "is_new": is_new,
            "category_name": category_names.get(
                item["category_id"], f"카테고리 {item['category_id']}"
            ),
        })
    return annotated, exited


def derive_stats(
    annotated_items: list[dict[str, Any]], exited: int
) -> dict[str, Any]:
    if not annotated_items:
        return {"total_views": 0, "channel_count": 0,
                "top_category": None, "exited": exited}
    top = Counter(it["category_name"] for it in annotated_items).most_common(1)[0][0]
    return {
        "total_views": sum(it["view_count"] for it in annotated_items),
        "channel_count": len({it["channel"] for it in annotated_items}),
        "top_category": top,
        "exited": exited,
    }


def category_shares(
    items: list[dict[str, Any]], category_names: dict[str, str]
) -> dict[str, float]:
    """Share of the (<=30) items per category name."""
    if not items:
        return {}
    counts = Counter(
        category_names.get(it["category_id"], f"카테고리 {it['category_id']}")
        for it in items
    )
    total = len(items)
    return {name: round(count / total, 4) for name, count in counts.items()}


def derive_timeseries(
    pairs: list[tuple[int, dict[str, Any]]],
    interval_s: int,
    category_names: dict[str, str],
) -> list[dict[str, Any]]:
    """One point per snapshot: bucket timestamp, category share map, and
    entered/exited counts vs the immediately preceding snapshot in `pairs`
    (0/0 for the first point, which has no baseline)."""
    points: list[dict[str, Any]] = []
    prev_ids: set[str] | None = None
    for bucket, snapshot in pairs:
        items = snapshot.get("items", [])
        ids = {it["video_id"] for it in items}
        if prev_ids is None:
            entered, exited = 0, 0
        else:
            entered = len(ids - prev_ids)
            exited = len(prev_ids - ids)
        points.append({
            "bucket_ts": bucket * interval_s,
            "shares": category_shares(items, category_names),
            "entered": entered,
            "exited": exited,
        })
        prev_ids = ids
    return points
