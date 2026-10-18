"""The build pipeline: ISO in, smaller ISO out. Same code on every OS."""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import iso as isofs
from .catalog import Selection
from .setup_files import SCRIPT_DIR_IN_IMAGE, SCRIPT_NAME, autounattend, specialize_script
from .tools import CancelToken, ToolError, find_wimlib, install_hint
from .wim import Edition, Wimlib, editions_from_header, quote_wim_path

SWM_PART_MIB = 3800


@dataclass
class BuildConfig:
    source_iso: str
    edition_index: int
    output_iso: str
    selection: Selection = field(default_factory=Selection)
    work_dir: str | None = None
    format: str = "esd"            # "esd" (smallest, slow) or "wim" (faster, larger)
    compact_install: bool = False  # CompactOS on the installed system
    keep_work: bool = False


# (stage id, title, share of the progress bar)
STAGES = (
    ("prepare", "Checking tools and space", 0.02),
    ("extract", "Copying installation media", 0.15),
    ("export", "Extracting the chosen edition", 0.20),
    ("modify", "Removing files and adding setup scripts", 0.05),
    ("compress", "Compressing the image", 0.43),
    ("iso", "Writing the ISO", 0.15),
)


class Reporter:
    def __init__(self, log: Callable[[str], None], progress: Callable[[str, float], None]):
        self.log = log
        self._progress = progress
        self._base = 0.0
        self._share = 0.0
        self.stage = ""

    def begin(self, stage: str) -> None:
        offset = 0.0
        for sid, title, share in STAGES:
            if sid == stage:
                self._base, self._share, self.stage = offset, share, sid
                self.log(f"== {title}")
                self._progress(sid, offset)
                return
            offset += share
        raise KeyError(stage)

    def fraction(self, value: float) -> None:
        self._progress(self.stage, self._base + self._share * max(0.0, min(value, 1.0)))


def find_install_image(media: Path) -> Path:
    sources = next((p for p in media.iterdir() if p.name.lower() == "sources" and p.is_dir()), None)
    if sources:
        for name in ("install.wim", "install.esd"):
            found = next((p for p in sources.iterdir() if p.name.lower() == name), None)
            if found:
                return found
        if any(p.name.lower() == "install.swm" for p in sources.iterdir()):
            raise ToolError("Split install.swm media is not supported as a source. Use a single-file ISO.")
    raise ToolError("This ISO has no sources/install.wim or install.esd. Is it Windows installation media?")


def inspect_iso(source_iso: str, log: Callable[[str], None] = lambda _m: None) -> list[Edition]:
    """List editions without extracting the ISO (reads only the WIM header and XML)."""
    import pycdlib

    iso = pycdlib.PyCdlib()
    try:
        iso.open(source_iso)
    except Exception as exc:  # pycdlib raises its own exception types
        raise ToolError(f"Could not open {source_iso} as an ISO: {exc}") from exc
    try:
        kind = "udf_path" if iso.has_udf() else "joliet_path" if iso.has_joliet() else "iso_path"
        target = None
        for dirname, _dirs, files in iso.walk(**{kind: "/"}):
            if dirname.strip("/").lower() != "sources":
                continue
            for name in files:
                if name.split(";")[0].lower() in ("install.wim", "install.esd"):
                    target = f"{dirname.rstrip('/')}/{name}"
        if not target:
            raise ToolError("This ISO has no sources/install.wim or install.esd. Is it Windows installation media?")
        log(f"Reading {target}")
        with iso.open_file_from_iso(**{kind: target}) as fp:
            return editions_from_header(fp)
    finally:
        iso.close()


def _require_wimlib() -> str:
    exe = find_wimlib()
    if not exe:
        raise ToolError("wimlib-imagex was not found. " + install_hint())
    return exe


def build(config: BuildConfig, *, log: Callable[[str], None], progress: Callable[[str, float], None],
          cancel: CancelToken | None = None) -> str:
    cancel = cancel or CancelToken()
    config.selection.validate()
    rep = Reporter(log, progress)
    started = time.monotonic()

    rep.begin("prepare")
    exe = _require_wimlib()
    wim = Wimlib(exe, log, cancel)
    source = Path(config.source_iso).expanduser().resolve()
    output = Path(config.output_iso).expanduser().resolve()
    if not source.is_file():
        raise ToolError(f"Source ISO not found: {source}")
    if output == source:
        raise ToolError("The output ISO must be a different file from the source.")
    output.parent.mkdir(parents=True, exist_ok=True)
    work = Path(config.work_dir).expanduser().resolve() if config.work_dir else output.parent / f".slim11-work-{os.getpid()}"
    if work.exists() and any(work.iterdir()):
        raise ToolError(f"Work folder is not empty: {work}")
    work.mkdir(parents=True, exist_ok=True)
    need = source.stat().st_size * 3
    free = shutil.disk_usage(work).free
    log(f"Using {exe}")
    log(f"Work folder {work} ({free / 1024**3:.1f} GiB free, about {need / 1024**3:.1f} GiB needed)")
    if free < need:
        raise ToolError(f"Not enough free space in {work}: {free / 1024**3:.1f} GiB free, "
                        f"about {need / 1024**3:.1f} GiB needed.")

    try:
        media = work / "media"
        rep.begin("extract")
        isofs.extract(str(source), str(media), log=log, progress=rep.fraction, check_cancel=cancel.check)

        image = find_install_image(media)
        editions = wim.editions(str(image))
        chosen = next((e for e in editions if e.index == config.edition_index), None)
        if not chosen:
            listed = ", ".join(f"{e.index}={e.name}" for e in editions)
            raise ToolError(f"Edition {config.edition_index} is not in this image. Available: {listed}")
        log(f"Edition: {chosen.name} ({chosen.architecture}, build {chosen.build})")

        rep.begin("export")
        single = work / "edition.wim"
        wim.export(str(image), chosen.index, str(single), compress="LZX", progress=rep.fraction)
        image.unlink()

        rep.begin("modify")
        inject = work / "inject"
        inject.mkdir()
        (inject / SCRIPT_NAME).write_text(specialize_script(config.selection), encoding="utf-8-sig", newline="")
        commands = [f"delete --force --recursive {quote_wim_path(p)}" for p in config.selection.file_paths()]
        commands.append(f"add {quote_wim_path(str(inject))} {quote_wim_path(SCRIPT_DIR_IN_IMAGE)}")
        wim.update(str(single), 1, commands)
        (media / "autounattend.xml").write_text(
            autounattend(config.selection, chosen.architecture, compact=config.compact_install),
            encoding="utf-8", newline="\r\n")
        rep.fraction(1)

        rep.begin("compress")
        sources = image.parent
        if config.format == "esd":
            wim.export(str(single), 1, str(sources / "install.esd"), compress="LZMS", solid=True,
                       progress=rep.fraction)
        elif config.format == "wim":
            target = sources / "install.wim"
            wim.export(str(single), 1, str(target), compress="LZX", progress=rep.fraction)
            if target.stat().st_size > isofs.MAX_ISO_FILE:
                log("install.wim is over 4 GiB; splitting into install.swm parts")
                wim.split(str(target), str(sources / "install.swm"), SWM_PART_MIB)
                target.unlink()
        else:
            raise ToolError(f"Unknown output format: {config.format}")
        single.unlink()

        rep.begin("iso")
        label = f"SLIM11_{chosen.architecture.upper().replace('X86_64', 'X64')}"
        isofs.build(str(media), str(output), label=label, log=log, check_cancel=cancel.check)
        rep.fraction(1)
    finally:
        if not config.keep_work:
            shutil.rmtree(work, ignore_errors=True)

    size = output.stat().st_size
    log(f"Done in {(time.monotonic() - started) / 60:.1f} min: {output} ({size / 1024**3:.2f} GiB)")
    progress("done", 1.0)
    return str(output)
