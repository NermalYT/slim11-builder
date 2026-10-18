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
import time
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__, catalog
from .engine import BuildConfig, build, inspect_iso
from .tools import Cancelled, CancelToken, find_wimlib, install_hint

WEB_DIR = Path(__file__).resolve().parent / "web"


class Job:
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

    def snapshot(self, since: int) -> dict:
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


JOB = Job()


def _start_build(payload: dict) -> None:
    with JOB.lock:
        if JOB.state == "running":
            raise ValueError("A build is already running.")
    sel = payload.get("selection") or {}
    selection = catalog.Selection(
        apps=list(sel.get("apps", [])), files=list(sel.get("files", [])), tweaks=list(sel.get("tweaks", [])),
        extra_packages=[p for p in sel.get("extra_packages", []) if isinstance(p, str)],
    )
    selection.validate()
    config = BuildConfig(
        source_iso=str(payload["source"]), edition_index=int(payload["edition"]),
        output_iso=str(payload["output"]), selection=selection,
        format=payload.get("format", "esd"), compact_install=bool(payload.get("compact")),
        work_dir=payload.get("workDir") or None,
    )
    token = CancelToken()
    with JOB.lock:
        JOB.state, JOB.stage, JOB.progress, JOB.log, JOB.error, JOB.output = "running", "prepare", 0.0, [], "", ""
        JOB.started, JOB.token = time.time(), token

    def worker() -> None:
        try:
            out = build(config, log=JOB.add_log, progress=JOB.set_progress, cancel=token)
            with JOB.lock:
                JOB.state, JOB.output, JOB.progress = "done", out, 1.0
        except Cancelled:
            JOB.add_log("Build cancelled.")
            with JOB.lock:
                JOB.state = "cancelled"
        except Exception as exc:  # report every failure to the UI
            JOB.add_log(traceback.format_exc().rstrip())
            with JOB.lock:
                JOB.state, JOB.error = "failed", str(exc)

    threading.Thread(target=worker, name="slim11-build", daemon=True).start()


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
                if JOB.token:
                    JOB.token.cancel()
                return self._json({"ok": True})
            if self.path == "/api/exists":
                return self._json({"exists": Path(str(payload["path"])).expanduser().exists()})
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
        if JOB.token:
            JOB.token.cancel()
        httpd.server_close()
