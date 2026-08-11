"""news — Newsroom Lens as a hub module (contract: app/modules/__init__.py).

Migrated from newsroom/backend/app (design:
docs/specs/2026-08-10-newsroom-lens-design.md; original spec docs/newsroom.md).
Router paths are relative — the hub mounts them under /api/news.
"""
from ...archive import archive_ensure_schema
from . import schema, service
from .api.routes import router  # noqa: F401  (contract export)
from .migrate import migrate_entities

META = {
    "id": "news",
    "title": "Newsroom Lens",
    "tagline": "BBC·Guardian·NHK·연합뉴스·Al Jazeera — 5개 매체 관점 비교 뉴스룸",
    "icon": "📰",
}


async def startup() -> None:
    archive_ensure_schema("news", schema.DDL, schema.TABLES)
    migrate_entities()  # entities 잔여분 멱등 백필 (비면 no-op)
    await service.start()


async def shutdown() -> None:
    await service.stop()


def health() -> dict:
    return service.health()
