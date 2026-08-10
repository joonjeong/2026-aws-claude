"""Hub module contract.

Each module package (app/modules/<id>/__init__.py) MUST expose:

    META: dict            # {"id","title","tagline","icon"} — launcher card
    router: APIRouter     # paths relative to /api/<id> (e.g. "/quakes", "/brief")
    async def startup()   # start collectors etc. (called in hub lifespan)
    async def shutdown()  # stop collectors etc.
    def health() -> dict  # module status (collector status, item counts, ...)

main.py knows only this contract. Keys/tokens are read from env inside the
module; error contract everywhere: missing LLM token → 503, upstream → 502
with status code only.
"""
