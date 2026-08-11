"""Append-only SQLite archive shared by the capstones.

In-memory stores stay the hot path; this is the history layer behind them.
Sync sqlite3 on the single asyncio loop is deliberate: writes are a few KB
per poll cycle, so blocking stays under a millisecond (same assumption as
stores.py — one event loop, no locks).

Two tables by data shape:
- entities:  natural-keyed items. INSERT OR IGNORE makes re-observation by
             pollers a no-op. (quake/news moved on to normalized tables via
             ensure_schema; entities stays as the pre-normalization landing
             zone and keeps rows a backfill could not parse.)
- snapshots: keyless time series (market quotes). Append.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
  module     TEXT NOT NULL,
  id         TEXT NOT NULL,
  first_seen REAL NOT NULL,
  payload    TEXT NOT NULL,
  PRIMARY KEY (module, id)
);
CREATE TABLE IF NOT EXISTS snapshots (
  module  TEXT NOT NULL,
  kind    TEXT NOT NULL,
  ts      REAL NOT NULL,
  payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots ON snapshots (module, kind, ts);
"""


def _dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class Archive:
    def __init__(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(p))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._tables: dict[str, str] = {}

    def put_entities(self, module: str, items: Iterable[tuple[str, Any]]) -> int:
        """Insert natural-keyed items; returns how many were NEW."""
        now = time.time()
        rows = [(module, str(i), now, _dump(p)) for i, p in items]
        if not rows:
            return 0
        cur = self._conn.executemany(
            "INSERT OR IGNORE INTO entities (module, id, first_seen, payload)"
            " VALUES (?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()
        return cur.rowcount

    def put_snapshot(self, module: str, kind: str, payload: Any,
                     ts: float | None = None) -> None:
        self._conn.execute(
            "INSERT INTO snapshots (module, kind, ts, payload) VALUES (?, ?, ?, ?)",
            (module, kind, ts if ts is not None else time.time(), _dump(payload)),
        )
        self._conn.commit()

    def counts(self) -> dict[str, int]:
        """Total archived rows per module (entities + snapshots)."""
        out: dict[str, int] = {}
        for table in ("entities", "snapshots"):
            for module, n in self._conn.execute(
                f"SELECT module, COUNT(*) FROM {table} GROUP BY module"  # noqa: S608
            ):
                out[module] = out.get(module, 0) + n
        for table, module in self._tables.items():
            (n,) = self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608
            out[module] = out.get(module, 0) + n
        return out

    def prune_snapshots(self, days: int) -> int:
        """Delete snapshots older than `days`; returns deleted count.
        days <= 0 disables pruning. entities are small — never pruned."""
        if days <= 0:
            return 0
        cur = self._conn.execute(
            "DELETE FROM snapshots WHERE ts < ?", (time.time() - days * 86_400,)
        )
        self._conn.commit()
        return cur.rowcount

    # --- module-defined normalized tables (dim/fact) ---------------------

    def ensure_schema(self, module: str, ddl: str, tables: list[str]) -> None:
        """Run a module's DDL (CREATE IF NOT EXISTS) and register its tables
        so counts()/prune_table() know them. Idempotent."""
        self._conn.executescript(ddl)
        self._conn.commit()
        for t in tables:
            self._tables[t] = module

    def insert_rows(self, sql: str, rows: list[tuple]) -> int:
        if not rows:
            return 0
        cur = self._conn.executemany(sql, rows)
        self._conn.commit()
        return cur.rowcount

    def query(self, sql: str, params: tuple = ()) -> list[tuple]:
        return self._conn.execute(sql, params).fetchall()

    def execute(self, sql: str, params: tuple = ()) -> int:
        """Single DML statement (DELETE/UPDATE); returns affected rowcount."""
        cur = self._conn.execute(sql, params)
        self._conn.commit()
        return cur.rowcount

    def prune_table(self, table: str, ts_col: str, days: int) -> int:
        """Delete rows older than `days` from a REGISTERED table only —
        the registry doubles as an identifier allowlist (no SQL injection
        via table/column names)."""
        if days <= 0 or table not in self._tables:
            return 0
        if not _IDENT_RE.fullmatch(ts_col):
            raise ValueError(f"invalid column name: {ts_col!r}")
        cur = self._conn.execute(
            f"DELETE FROM {table} WHERE {ts_col} < ?",  # noqa: S608 — allowlisted
            (time.time() - days * 86_400,),
        )
        self._conn.commit()
        return cur.rowcount

    def close(self) -> None:
        self._conn.close()
