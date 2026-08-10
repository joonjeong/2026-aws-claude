"""Module runtime state — replaces the old standalone app.state.

The hub owns the FastAPI app, so the snapshot store and the polling
collector live here as module-level singletons: created/started by
startup(), stopped by shutdown(), read by the routes and health().
"""
from __future__ import annotations

from typing import Any

from .store.snapshots import SnapshotStore

store = SnapshotStore()
collector: Any = None  # labkit PollingCollector once startup() has run
