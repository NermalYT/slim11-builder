"""Thin wrapper over wimlib-imagex. Works on WIM and ESD files without mounting."""

from __future__ import annotations

import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable

from .tools import CancelToken, ToolError, run


@dataclass
class Edition:
    index: int
    name: str
    display_name: str
    architecture: str
    build: str
    size_bytes: int
    language: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def parse_info(text: str) -> list[Edition]:
    """Parse `wimlib-imagex info` output into editions."""
    editions: list[Edition] = []
    current: dict[str, str] | None = None

    def flush() -> None:
        if current and "Index" in current:
            editions.append(Edition(
                index=int(current["Index"]),
                name=current.get("Name", ""),
                display_name=current.get("Display Name", current.get("Name", "")),
                architecture=current.get("Architecture", ""),
                build=current.get("Build", ""),
                size_bytes=int((current.get("Total Bytes", "0").split() or ["0"])[0] or 0),
                language=current.get("Default Language", ""),
            ))

    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key == "Index":
            flush()
            current = {}
        if current is not None and key not in current:
            current[key] = value
    flush()
    return editions


_ARCH_IDS = {"0": "x86", "5": "arm", "9": "x86_64", "12": "arm64"}


def editions_from_header(fp) -> list[Edition]:
    """Read editions straight from a WIM/ESD file object via its XML block.

    Only the 208-byte header and the XML at the end are read, so this works on
    a file inside an ISO without copying gigabytes and without wimlib.
    """
    fp.seek(0)
    header = fp.read(208)
    if len(header) < 96 or header[:8] != b"MSWIM\0\0\0":
        raise ToolError("Not a WIM or ESD file.")
    size_and_flags, offset, original = struct.unpack_from("<QQQ", header, 72)
    size = size_and_flags & 0x00FFFFFFFFFFFFFF
    if not size or size > 64 * 1024 * 1024:
        raise ToolError("WIM XML data is missing or implausibly large.")
    fp.seek(offset)
    raw = fp.read(size)
    text = raw.decode("utf-16-le", "replace").lstrip("\ufeff")
    root = ET.fromstring(text)
    editions = []
    for image in root.findall("IMAGE"):
        def get(path: str, default: str = "") -> str:
            node = image.find(path)
            return (node.text or "").strip() if node is not None and node.text else default
        name = get("NAME")
        editions.append(Edition(
            index=int(image.get("INDEX", "0")),
            name=name,
            display_name=get("DISPLAYNAME", name),
            architecture=_ARCH_IDS.get(get("WINDOWS/ARCH"), get("WINDOWS/ARCH")),
            build=get("WINDOWS/VERSION/BUILD"),
            size_bytes=int(get("TOTALBYTES", "0") or 0),
            language=get("WINDOWS/LANGUAGES/DEFAULT"),
        ))
    return sorted(editions, key=lambda e: e.index)


class Wimlib:
    def __init__(self, exe: str, log: Callable[[str], None], cancel: CancelToken | None = None):
        self.exe = exe
        self.log = log
        self.cancel = cancel

    def editions(self, wim: str) -> list[Edition]:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # type: ignore[attr-defined]
        result = subprocess.run([self.exe, "info", wim], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", creationflags=creationflags)
        if result.returncode != 0:
            raise ToolError(f"Could not read {wim}:\n{result.stdout}{result.stderr}".strip())
        return parse_info(result.stdout)

    def export(self, src: str, index: int, dest: str, *, compress: str, solid: bool = False,
               progress: Callable[[float], None] | None = None, name: str | None = None) -> None:
        args = [self.exe, "export", src, str(index), dest]
        if name:
            args.append(name)
        args += [f"--compress={compress}"]
        if solid:
            args.append("--solid")
        run(args, log=self.log, progress=progress, cancel=self.cancel)

    def update(self, wim: str, index: int, commands: list[str]) -> None:
        if not commands:
            return
        for command in commands:
            self.log(f"  {command}")
        run([self.exe, "update", wim, str(index)], log=self.log, cancel=self.cancel,
            stdin="\n".join(commands) + "\n")

    def split(self, wim: str, dest_swm: str, part_mib: int) -> None:
        run([self.exe, "split", wim, dest_swm, str(part_mib)], log=self.log, cancel=self.cancel)

    def list_dir(self, wim: str, index: int, path: str = "/") -> list[str]:
        out = subprocess.run([self.exe, "dir", wim, str(index), "--path=" + path],
                             capture_output=True, text=True, encoding="utf-8", errors="replace")
        if out.returncode != 0:
            raise ToolError(out.stdout + out.stderr)
        return [line for line in out.stdout.splitlines() if line.strip()]


def quote_wim_path(path: str) -> str:
    """Quote a path for a wimlib update command file."""
    if '"' in path:
        raise ValueError(f"Unsupported character in path: {path}")
    return f'"{path}"'
