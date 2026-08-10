"""Quake module constants (env-overridable via labkit.config helpers)."""
from labkit.config import env_float, env_int, env_str

USGS_FEED_URL = env_str(
    "QUAKE_FEED_URL",
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson",
)
POLL_INTERVAL_S = env_float("QUAKE_POLL_INTERVAL_S", 60.0)
FETCH_TIMEOUT_S = env_float("QUAKE_FETCH_TIMEOUT_S", 10.0)
MAX_EVENTS = env_int("QUAKE_MAX_EVENTS", 500)

BRIEF_MAX_TOKENS = env_int("QUAKE_BRIEF_MAX_TOKENS", 700)
BRIEF_BUCKET_S = env_int("QUAKE_BRIEF_BUCKET_S", 600)
