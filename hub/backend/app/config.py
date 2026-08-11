"""Hub-level config: which modules are mounted. Module-local constants
live in each module's own config.py."""
from labkit.config import env_str

ALL_MODULES = ["quake", "news", "trend", "market", "contrail", "wake"]

ENABLED_MODULES = [
    m.strip()
    for m in env_str("ENABLED_MODULES", ",".join(ALL_MODULES)).split(",")
    if m.strip()
]
