"""Build profiles and the background build job shared by the GUI and the MCP server.

A profile is plain JSON, so people and AI agents can write, diff and reuse it:

    {
      "source": "/isos/Win11_English_x64.iso",
      "edition": 6,
      "output": "/isos/Win11-slim.iso",
      "preset": "slim",
      "selection": {"apps": [...], "files": [...], "tweaks": [...], "extra_packages": [...]},
      "format": "esd",
      "compact": false,
      "workDir": null
    }

"selection" replaces "preset"; leave it out to start from the preset. Optional
"add" and "remove" objects (same keys as "selection") adjust either one, e.g.
{"preset": "light", "add": {"files": ["onedrive"]}}.
"""

from __future__ import annotations

import json
import threading
import time
import traceback
from pathlib import Path

from . import catalog
from .engine import BuildConfig, build
from .tools import Cancelled, CancelToken

PROFILE_KEYS = {"source", "edition", "output", "preset", "selection", "add", "remove", "format", "compact",
                "workDir", "$schema"}
SELECTION_KEYS = ("apps", "files", "tweaks", "extra_packages")


def selection_from(data: dict | None, preset: str | None = None) -> catalog.Selection:
    if data is None:
        return catalog.preset(preset or "slim")
    unknown = set(data) - set(SELECTION_KEYS)
    if unknown:
        raise ValueError(f"Unknown selection keys: {', '.join(sorted(unknown))}")
    sel = catalog.Selection(
        apps=[str(x) for x in data.get("apps", [])], files=[str(x) for x in data.get("files", [])],
        tweaks=[str(x) for x in data.get("tweaks", [])],
        extra_packages=[str(p) for p in data.get("extra_packages", []) if str(p).strip()],
    )
    sel.validate()
    return sel


def config_from_profile(profile: dict) -> BuildConfig:
    unknown = set(profile) - PROFILE_KEYS
    if unknown:
        raise ValueError(f"Unknown profile keys: {', '.join(sorted(unknown))}")
    for key in ("source", "edition", "output"):
        if profile.get(key) in (None, ""):
            raise ValueError(f"Profile is missing '{key}'.")
    fmt = profile.get("format", "esd")
    if fmt not in ("esd", "wim"):
        raise ValueError("format must be 'esd' or 'wim'.")
    if not str(profile["output"]).lower().endswith(".iso"):
        raise ValueError("output must be a path ending in .iso")
    selection = selection_from(profile.get("selection"), profile.get("preset"))
    for key, adding in (("add", True), ("remove", False)):
        change = profile.get(key) or {}
        unknown = set(change) - set(SELECTION_KEYS)
        if unknown:
            raise ValueError(f"Unknown '{key}' keys: {', '.join(sorted(unknown))}")
        for attr in SELECTION_KEYS:
            current = getattr(selection, attr)
            for item in change.get(attr, []):
                if adding and item not in current:
                    current.append(str(item))
                elif not adding and item in current:
                    current.remove(item)
    selection.validate()
    return BuildConfig(
        source_iso=str(profile["source"]), edition_index=int(profile["edition"]), output_iso=str(profile["output"]),
        selection=selection,
        format=fmt, compact_install=bool(profile.get("compact", False)), work_dir=profile.get("workDir") or None,
    )


def profile_from_config(config: BuildConfig) -> dict:
    return {
        "source": config.source_iso, "edition": config.edition_index, "output": config.output_iso,
        "selection": {k: list(v) for k, v in config.selection.__dict__.items()},
        "format": config.format, "compact": config.compact_install, "workDir": config.work_dir,
    }


def load_profile(path: str) -> dict:
    with open(Path(path).expanduser(), encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("A profile must be a JSON object.")
    return data


def save_profile(path: str, profile: dict) -> None:
    config_from_profile(profile)  # validate before writing
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")


class Job:
    """One build at a time, run on a background thread."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state = "idle"        # idle | running | done | failed | cancelled
        self.stage = ""
        self.progress = 0.0
        self.log: list[str] = []
        self.error = ""
        self.output = ""
        self.started = 0.0
        self.token: CancelToken | None = None

    def snapshot(self, since: int = 0) -> dict:
        with self.lock:
            return {"state": self.state, "stage": self.stage, "progress": self.progress,
                    "log": self.log[since:], "logLength": len(self.log), "error": self.error,
                    "output": self.output, "elapsed": time.time() - self.started if self.started else 0}

    def add_log(self, line: str) -> None:
        with self.lock:
            self.log.append(line)
            del self.log[:-5000]

    def set_progress(self, stage: str, value: float) -> None:
        with self.lock:
            self.stage, self.progress = stage, value

    def start(self, config: BuildConfig) -> None:
        token = CancelToken()
        with self.lock:
            if self.state == "running":
                raise ValueError("A build is already running.")
            self.state, self.stage, self.progress, self.log, self.error, self.output = "running", "prepare", 0.0, [], "", ""
            self.started, self.token = time.time(), token
        threading.Thread(target=self._run, args=(config, token), name="slim11-build", daemon=True).start()

    def _run(self, config: BuildConfig, token: CancelToken) -> None:
        try:
            out = build(config, log=self.add_log, progress=self.set_progress, cancel=token)
            with self.lock:
                self.state, self.output, self.progress = "done", out, 1.0
        except Cancelled:
            self.add_log("Build cancelled.")
            with self.lock:
                self.state = "cancelled"
        except Exception as exc:  # report every failure to the caller
            self.add_log(traceback.format_exc().rstrip())
            with self.lock:
                self.state, self.error = "failed", str(exc)

    def cancel(self) -> None:
        if self.token:
            self.token.cancel()

    def wait(self, timeout: float | None = None) -> str:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self.lock:
                if self.state != "running":
                    return self.state
            if deadline is not None and time.monotonic() >= deadline:
                return "running"
            time.sleep(0.2)
