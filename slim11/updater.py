"""Self-update from GitHub releases.

Two install styles are supported:
- installed from a release wheel (pip / pipx): upgrade with pip to the newest
  release's wheel, in the same Python environment that is running Slim11;
- running from a git clone (slim11.sh / slim11.cmd): fast-forward the clone
  to the newest release tag and reinstall it in place.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import __version__

REPO = os.environ.get("SLIM11_UPDATE_REPO", "NermalYT/slim11-builder")
API = f"https://api.github.com/repos/{REPO}/releases/latest"
SOURCE_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Release:
    version: str
    tag: str
    url: str
    notes: str
    wheel_url: str | None

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def parse_version(text: str) -> tuple[int, ...]:
    """'v0.1.2' -> (0, 1, 2). Pre-release suffixes sort before the release."""
    match = re.match(r"v?(\d+(?:\.\d+)*)", text.strip())
    if not match:
        raise ValueError(f"Not a version: {text}")
    return tuple(int(p) for p in match.group(1).split("."))


def is_newer(candidate: str, current: str = __version__) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def release_from_json(data: dict) -> Release:
    tag = data["tag_name"]
    wheel = next((a["browser_download_url"] for a in data.get("assets", [])
                  if a.get("name", "").endswith(".whl")), None)
    return Release(version=tag.lstrip("v"), tag=tag, url=data.get("html_url", ""),
                   notes=data.get("body") or "", wheel_url=wheel)


def release_from_json_dict(data: dict) -> Release:
    return Release(**data)


def latest_release(timeout: float = 10) -> Release:
    req = urllib.request.Request(API, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"slim11-builder/{__version__}",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return release_from_json(json.load(resp))


def check() -> dict:
    release = latest_release()
    return {"current": __version__, "latest": release.version, "updateAvailable": is_newer(release.version),
            "release": release.to_dict(), "method": install_method()}


def install_method() -> str:
    return "git" if (SOURCE_ROOT / ".git").exists() else "pip"


def _run(args: list[str], log: Callable[[str], None], cwd: Path | None = None) -> None:
    log("$ " + " ".join(args))
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    for line in (proc.stdout + proc.stderr).splitlines():
        if line.strip():
            log(line)
    if proc.returncode != 0:
        raise RuntimeError(f"{Path(args[0]).name} failed with exit code {proc.returncode}")


def apply(log: Callable[[str], None] = print, release: Release | None = None) -> str:
    """Install the newest release. Returns the version now installed."""
    release = release or latest_release()
    if not is_newer(release.version):
        log(f"Slim11 {__version__} is already up to date.")
        return __version__
    if install_method() == "git":
        _run(["git", "fetch", "--tags", "origin"], log, SOURCE_ROOT)
        _run(["git", "merge", "--ff-only", release.tag], log, SOURCE_ROOT)
        _run([sys.executable, "-m", "pip", "install", "-q", "-e", str(SOURCE_ROOT)], log)
    else:
        if not release.wheel_url:
            raise RuntimeError(f"Release {release.tag} has no wheel to install. See {release.url}")
        _run([sys.executable, "-m", "pip", "install", "--upgrade", release.wheel_url], log)
    log(f"Updated to Slim11 {release.version}. Restart Slim11 to use it.")
    return release.version
