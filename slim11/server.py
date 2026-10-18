"""Local GUI server.

The interface is a small web app served on 127.0.0.1 and opened in the
default browser, so it looks and behaves the same on Linux, macOS and Windows
with no GUI toolkit to install. Every API call must carry a random per-launch
token, which stops other web pages from driving the builder.
"""

from __future__ import annotations

import json
import mimetypes
import os
import platform
import secrets
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__, catalog
from .engine import inspect_iso
from .jobs import Job, config_from_profile
from .tools import find_wimlib, install_hint

WEB_DIR = Path(__file__).resolve().parent / "web"


JOB = Job()


def _start_build(payload: dict) -> None:
    JOB.start(config_from_profile({
        "source": payload.get("source"), "edition": payload.get("edition"), "output": payload.get("output"),
        "selection": payload.get("selection") or {}, "format": payload.get("format", "esd"),
        "compact": bool(payload.get("compact")), "workDir": payload.get("workDir") or None,
    }))


def _settings_payload() -> dict:
    from . import ai, settings
    data = settings.load()
    return {"ai_features": data["ai_features"], "path": str(settings.path()),
            "snippets": ai.config_snippets(), "detected": ai.detected_tools()}


def _browse(path: str | None) -> dict:
    base = Path(path).expanduser() if path else Path.home()
    if base.is_file():
        base = base.parent
    base = base.resolve()
    entries = []
    try:
        for child in sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if child.name.startswith("."):
                continue
            try:
                is_dir = child.is_dir()
            except OSError:
                continue
            if is_dir or child.suffix.lower() == ".iso":
                entries.append({"name": child.name, "path": str(child), "dir": is_dir,
                                "size": 0 if is_dir else child.stat().st_size})
    except PermissionError:
        pass
    roots = []
    if sys.platform == "win32":
        import string
        roots = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
    else:
        roots = [str(Path.home()), "/"] + ([str(p) for p in Path("/Volumes").iterdir()] if sys.platform == "darwin" else [])
    return {"path": str(base), "parent": str(base.parent) if base.parent != base else None,
            "entries": entries, "roots": roots, "sep": os.sep}


class Handler(BaseHTTPRequestHandler):
    server_version = "Slim11"
    token = ""

    def log_message(self, *_args) -> None:  # keep the terminal quiet
        pass

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status: int = 200) -> None:
        self._send(status, json.dumps(data).encode(), "application/json")

    def _authorized(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost") and secrets.compare_digest(
            self.headers.get("X-Slim11-Token", ""), self.token)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path.startswith("/api/"):
            if not self._authorized():
                return self._json({"error": "unauthorized"}, 403)
            if path == "/api/status":
                return self._json({
                    "version": __version__, "platform": platform.system() or sys.platform,
                    "python": platform.python_version(), "wimlib": find_wimlib(), "hint": install_hint(),
                    "home": str(Path.home()), "sep": os.sep,
                })
            if path == "/api/settings":
                return self._json(_settings_payload())
            if path == "/api/update":
                from . import updater
                try:
                    return self._json(updater.check())
                except Exception as exc:  # offline, rate-limited, no releases yet
                    return self._json({"current": __version__, "updateAvailable": False, "error": str(exc)})
            if path == "/api/catalog":
                return self._json(catalog.as_dict())
            if path == "/api/job":
                since = int((self.path.split("since=")[1:] or ["0"])[0].split("&")[0] or 0)
                return self._json(JOB.snapshot(since))
            return self._json({"error": "not found"}, 404)
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        file = (WEB_DIR / name).resolve()
        if WEB_DIR not in file.parents or not file.is_file():
            return self._send(404, b"Not found", "text/plain")
        ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(200, file.read_bytes(), ctype)

    def do_POST(self) -> None:
        if not self._authorized():
            return self._json({"error": "unauthorized"}, 403)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "invalid JSON"}, 400)
        try:
            if self.path == "/api/browse":
                return self._json(_browse(payload.get("path")))
            if self.path == "/api/inspect":
                editions = inspect_iso(str(payload["iso"]))
                return self._json({"editions": [e.to_dict() for e in editions]})
            if self.path == "/api/build":
                _start_build(payload)
                return self._json({"ok": True})
            if self.path == "/api/cancel":
                JOB.cancel()
                return self._json({"ok": True})
            if self.path == "/api/exists":
                return self._json({"exists": Path(str(payload["path"])).expanduser().exists()})
            if self.path == "/api/settings":
                from . import ai
                if "ai_features" in payload:
                    ai.set_enabled(bool(payload["ai_features"]))
                return self._json(_settings_payload())
            if self.path == "/api/update":
                from . import updater
                if JOB.state == "running":
                    raise ValueError("Wait for the build to finish before updating.")
                lines: list[str] = []
                version = updater.apply(log=lines.append)
                return self._json({"version": version, "log": lines})
            if self.path == "/api/quit":
                self._json({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return None
        except Exception as exc:  # surface errors to the UI
            return self._json({"error": str(exc)}, 400)
        return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)


def serve(port: int = 0, open_browser: bool = True) -> None:
    Handler.token = secrets.token_urlsafe(24)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/#t={Handler.token}"
    print(f"Slim11 Builder is running at:\n  {url}\nPress Ctrl+C to quit.", flush=True)
    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        JOB.cancel()
        httpd.server_close()
