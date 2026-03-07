"""Configuration file support for AgentStream.

Reads settings from ``~/.agentstream/config.toml``.  Falls back to built-in
defaults when the file is missing, unreadable, or contains parse errors.

Python 3.11+ uses the stdlib ``tomllib``; on older versions the file is
silently skipped (defaults apply) to avoid adding a third-party dependency.

Supports Claude Code, OpenAI Codex, and Aider agents.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

_CONFIG_DIR = Path.home() / ".agentstream"
_CONFIG_PATH = _CONFIG_DIR / "config.toml"


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass
class DisplayConfig:
    max_content: int = 200
    relative_time: bool = False
    sidebar: bool = True


@dataclass
class NotificationsConfig:
    bell: bool = False


@dataclass
class HistoryConfig:
    enabled: bool = True
    max_days: int = 30


@dataclass
class WatchConfig:
    scan_interval: float = 5.0
    session_max_age: float = 600.0
    idle_timeout: float = 600.0


@dataclass
class Config:
    display: DisplayConfig = field(default_factory=DisplayConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    history: HistoryConfig = field(default_factory=HistoryConfig)
    watch: WatchConfig = field(default_factory=WatchConfig)


# ---------------------------------------------------------------------------
# Known keys per section (for warning on unknowns)
# ---------------------------------------------------------------------------

_KNOWN_KEYS: dict[str, set[str]] = {
    "display": {f.name for f in fields(DisplayConfig)},
    "notifications": {f.name for f in fields(NotificationsConfig)},
    "history": {f.name for f in fields(HistoryConfig)},
    "watch": {f.name for f in fields(WatchConfig)},
}

_SECTION_MAP: dict[str, type] = {
    "display": DisplayConfig,
    "notifications": NotificationsConfig,
    "history": HistoryConfig,
    "watch": WatchConfig,
}


# ---------------------------------------------------------------------------
# TOML loading
# ---------------------------------------------------------------------------

def _load_toml(path: Path) -> dict[str, Any] | None:
    """Parse a TOML file, returning *None* on any failure."""
    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:
        # Python 3.10 — no stdlib TOML support; skip config file.
        return None

    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception as exc:
        print(f"agentstream: warning: cannot parse {path}: {exc}", file=sys.stderr)
        return None


def _warn(msg: str) -> None:
    print(f"agentstream: warning: {msg}", file=sys.stderr)


def _apply_section(data: dict[str, Any], section: str, target: Any) -> None:
    """Apply *data[section]* values onto *target* dataclass instance."""
    section_data = data.get(section)
    if section_data is None:
        return
    if not isinstance(section_data, dict):
        _warn(f"[{section}] should be a table, ignoring")
        return

    known = _KNOWN_KEYS.get(section, set())
    for key, value in section_data.items():
        if key not in known:
            _warn(f"unknown key [{section}].{key}")
            continue
        if hasattr(target, key):
            try:
                # Coerce to the expected type
                expected_type = type(getattr(target, key))
                setattr(target, key, expected_type(value))
            except (TypeError, ValueError) as exc:
                _warn(f"bad value for [{section}].{key}: {exc}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_config(path: Path | None = None) -> Config:
    """Load configuration, falling back to defaults on any error.

    Parameters
    ----------
    path : Path, optional
        Override the default ``~/.agentstream/config.toml`` path (useful for
        testing).
    """
    cfg = Config()
    config_path = path or _CONFIG_PATH

    if not config_path.is_file():
        return cfg

    data = _load_toml(config_path)
    if data is None:
        return cfg

    # Warn about top-level keys that are not known sections
    for key in data:
        if key not in _SECTION_MAP:
            _warn(f"unknown section [{key}]")

    _apply_section(data, "display", cfg.display)
    _apply_section(data, "notifications", cfg.notifications)
    _apply_section(data, "history", cfg.history)
    _apply_section(data, "watch", cfg.watch)

    return cfg
