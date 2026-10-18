"""User settings stored as JSON in the platform's config folder.

Linux:   $XDG_CONFIG_HOME/slim11/settings.json (default ~/.config/slim11)
macOS:   ~/Library/Application Support/Slim11/settings.json
Windows: %APPDATA%\\Slim11\\settings.json
Override with SLIM11_CONFIG=/path/to/settings.json.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DEFAULTS = {
    # Lets AI coding agents (Claude Code, Codex, Antigravity, ...) drive Slim11
    # through `slim11 mcp`. Off unless the user turns it on.
    "ai_features": False,
}


def path() -> Path:
    override = os.environ.get("SLIM11_CONFIG")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Slim11"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Slim11"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "slim11"
    return base / "settings.json"


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        stored = json.loads(path().read_text(encoding="utf-8"))
        if isinstance(stored, dict):
            data.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return data


def save(**changes) -> dict:
    unknown = set(changes) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"Unknown setting: {', '.join(sorted(unknown))}")
    data = load()
    data.update(changes)
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    return data


def ai_enabled() -> bool:
    return bool(load()["ai_features"])
