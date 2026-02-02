"""Configuration resolution for claude-session-index.

Priority order:
1. Function arguments (passed directly)
2. Environment variables
3. Config file (~/.session-index/config.json)
4. Sensible defaults
"""

import json
import os
from pathlib import Path
from typing import Optional

DEFAULTS = {
    "projects_dir": str(Path.home() / ".claude" / "projects"),
    "db_path": str(Path.home() / ".session-index" / "sessions.db"),
    "topics_dir": str(Path.home() / ".claude" / "session-topics"),
    "clients": [],
    "project_names": {},
}

CONFIG_FILE = Path.home() / ".session-index" / "config.json"

_cached_config: Optional[dict] = None


def _load_config_file() -> dict:
    """Load config from ~/.session-index/config.json if it exists."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def get_config() -> dict:
    """Resolve config from all sources. Result is cached after first call."""
    global _cached_config
    if _cached_config is not None:
        return _cached_config

    # Start with defaults
    config = dict(DEFAULTS)

    # Layer on config file
    file_config = _load_config_file()
    for key, value in file_config.items():
        if key in config and value is not None:
            config[key] = value

    # Layer on environment variables
    env_map = {
        "SESSION_INDEX_PROJECTS": "projects_dir",
        "SESSION_INDEX_DB": "db_path",
        "SESSION_INDEX_TOPICS": "topics_dir",
    }
    for env_key, config_key in env_map.items():
        val = os.environ.get(env_key)
        if val:
            config[config_key] = val

    _cached_config = config
    return config


def get_projects_dir(override: str = None) -> Path:
    """Get projects directory path."""
    if override:
        return Path(override).expanduser()
    return Path(get_config()["projects_dir"]).expanduser()


def get_db_path(override: str = None) -> Path:
    """Get database path, creating parent directory if needed."""
    if override:
        p = Path(override).expanduser()
    else:
        p = Path(get_config()["db_path"]).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_topics_dir(override: str = None) -> Path:
    """Get topics directory path."""
    if override:
        return Path(override).expanduser()
    return Path(get_config()["topics_dir"]).expanduser()


def get_clients() -> list[str]:
    """Get list of known client names (optional — used for auto-detection)."""
    return get_config().get("clients", [])


def get_project_names() -> dict[str, str]:
    """Get project directory → friendly name mapping.

    If not configured, auto-generates from directory names:
    '-Users-lee-CC-LFI' → 'LFI'
    '-Users-foo-projects-myapp' → 'myapp'
    """
    configured = get_config().get("project_names", {})
    if configured:
        return configured

    # Auto-generate from directory names
    projects_dir = get_projects_dir()
    mapping = {}
    if projects_dir.exists():
        for d in projects_dir.iterdir():
            if d.is_dir():
                name = d.name
                # Take the last meaningful segment
                parts = [p for p in name.split("-") if p]
                if parts:
                    # Use last 1-2 segments as friendly name
                    friendly = " ".join(parts[-2:]) if len(parts) > 1 else parts[-1]
                    mapping[name] = friendly

    return mapping


def init_config():
    """Create a default config file if one doesn't exist."""
    if CONFIG_FILE.exists():
        return False

    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(DEFAULTS, indent=2) + "\n")
    return True
