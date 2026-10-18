"""External tool discovery and process running with progress and cancellation."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

APP_DIR = Path(__file__).resolve().parent


class Cancelled(Exception):
    pass


class ToolError(RuntimeError):
    pass


def find_wimlib() -> str | None:
    """Locate wimlib-imagex: $SLIM11_WIMLIB, a bundled copy, then PATH."""
    env = os.environ.get("SLIM11_WIMLIB")
    if env and Path(env).is_file():
        return env
    exe = "wimlib-imagex.exe" if sys.platform == "win32" else "wimlib-imagex"
    for base in (APP_DIR / "bin", APP_DIR.parent / "tools"):
        if base.is_dir():
            found = sorted(base.glob(f"**/{exe}"))
            if found:
                return str(found[0])
    return shutil.which(exe) or shutil.which("wimlib-imagex")


def install_hint() -> str:
    if sys.platform == "darwin":
        return "Install wimlib with Homebrew: brew install wimlib"
    if sys.platform == "win32":
        return ("Download the Windows build of wimlib from https://wimlib.net/downloads/ and extract "
                "wimlib-imagex.exe and libwim-15.dll into the tools folder next to Slim11, "
                "or set SLIM11_WIMLIB to its path.")
    return ("Install wimlib: sudo apt install wimtools (Debian/Ubuntu), sudo dnf install wimlib-utils "
            "(Fedora), sudo pacman -S wimlib (Arch).")


@dataclass
class CancelToken:
    _event: threading.Event = None  # type: ignore[assignment]
    _proc: subprocess.Popen | None = None

    def __post_init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()
        proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self.cancelled:
            raise Cancelled()


_PERCENT = re.compile(r"\((\d{1,3})%\)")


def run(args: list[str], *, log: Callable[[str], None], progress: Callable[[float], None] | None = None,
        cancel: CancelToken | None = None, stdin: str | None = None) -> str:
    """Run a command, streaming lines to log and NN% markers to progress."""
    if cancel:
        cancel.check()
    log("$ " + " ".join(_display(a) for a in args))
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # type: ignore[attr-defined]
    proc = subprocess.Popen(
        args, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=creationflags,
    )
    if cancel:
        cancel._proc = proc
    if stdin is not None:
        assert proc.stdin
        proc.stdin.write(stdin.encode("utf-8"))
        proc.stdin.close()
    assert proc.stdout
    output: list[str] = []
    buf = b""
    last_logged = ""
    while True:
        chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096)
        if not chunk:
            break
        buf += chunk
        parts = re.split(rb"[\r\n]", buf)
        buf = parts.pop()
        for raw in parts:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            output.append(line)
            match = _PERCENT.search(line)
            if match:
                if progress:
                    progress(min(int(match.group(1)), 100) / 100)
                continue  # progress lines are noisy; keep them out of the log
            if line != last_logged:
                log(line)
                last_logged = line
    if buf.strip():
        output.append(buf.decode("utf-8", "replace").strip())
        log(output[-1])
    proc.stdout.close()
    code = proc.wait()
    if cancel:
        cancel._proc = None
        cancel.check()
    if code != 0:
        tail = "\n".join(output[-15:])
        raise ToolError(f"{Path(args[0]).name} exited with code {code}\n{tail}")
    return "\n".join(output)


def _display(arg: str) -> str:
    return f'"{arg}"' if " " in arg else arg
