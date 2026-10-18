"""Read and write Windows installation ISOs in pure Python (pycdlib).

Windows media keeps its files in UDF; the ISO 9660 side only carries a readme
and the El Torito boot images. Slim11 writes the same layout: every file in
UDF 2.60, the BIOS and UEFI boot images also in ISO 9660 so firmware can find
them.
"""

from __future__ import annotations

import io
import os
from pathlib import Path, PurePosixPath
from typing import Callable

import pycdlib

# FAT32 limit; only matters when the ISO is copied to a FAT32 USB stick.
FAT32_MAX_FILE = 4 * 1024 ** 3 - 1

BIOS_BOOT = "boot/etfsboot.com"
# The default image asks "Press any key to boot from CD or DVD", like Microsoft's
# own media. Without that prompt a PC whose firmware boots the stick first
# restarts straight back into Setup after the first reboot.
UEFI_BOOT_PROMPT = "efi/microsoft/boot/efisys.bin"
UEFI_BOOT_NOPROMPT = "efi/microsoft/boot/efisys_noprompt.bin"

README = (b"This disc contains a UDF file system and requires an operating system\r\n"
          b"that supports UDF to read it. Built by Slim11 Builder.\r\n")


def extract(iso_path: str, dest: str, *, log: Callable[[str], None],
            progress: Callable[[float], None] | None = None, check_cancel: Callable[[], None] | None = None) -> None:
    iso = pycdlib.PyCdlib()
    iso.open(iso_path)
    try:
        if iso.has_udf():
            kind, root = "udf_path", "/"
        elif iso.has_joliet():
            kind, root = "joliet_path", "/"
        else:
            kind, root = "iso_path", "/"
        log(f"Reading ISO ({kind.split('_')[0].upper()})")
        entries: list[tuple[str, int]] = []
        for dirname, _dirs, files in iso.walk(**{kind: root}):
            os.makedirs(_local(dest, dirname, kind), exist_ok=True)
            for name in files:
                full = str(PurePosixPath(dirname) / name)
                if dirname == "/" and name.split(";")[0].lower() == "boot.cat":
                    continue  # El Torito catalog; a new one is written with the ISO
                record = iso.get_record(**{kind: full})
                entries.append((full, record.get_data_length()))
        total = sum(size for _, size in entries) or 1
        done = 0
        for full, size in entries:
            if check_cancel:
                check_cancel()
            local = _local(dest, full, kind)
            if size == 0:
                open(local, "wb").close()  # pycdlib refuses to copy entries with no data
            else:
                iso.get_file_from_iso(local, **{kind: full})
            done += size
            if progress:
                progress(done / total)
    finally:
        iso.close()


def _local(dest: str, iso_name: str, kind: str) -> str:
    name = iso_name
    if kind == "iso_path":
        name = name.split(";")[0].rstrip(".")
    return os.path.join(dest, *[p for p in name.split("/") if p])


def _find(root: Path, rel: str) -> Path | None:
    """Case-insensitive lookup of a relative path under root."""
    cur = root
    for part in rel.split("/"):
        if not cur.is_dir():
            return None
        match = next((c for c in cur.iterdir() if c.name.lower() == part.lower()), None)
        if match is None:
            return None
        cur = match
    return cur


def build(src_dir: str, iso_path: str, *, label: str, log: Callable[[str], None],
          no_prompt: bool = False, check_cancel: Callable[[], None] | None = None) -> None:
    root = Path(src_dir)
    bios = _find(root, BIOS_BOOT)
    uefi_rel = UEFI_BOOT_NOPROMPT if no_prompt and _find(root, UEFI_BOOT_NOPROMPT) else UEFI_BOOT_PROMPT
    uefi = _find(root, uefi_rel)
    if not bios and not uefi:
        raise RuntimeError("No boot image found (boot/etfsboot.com or efi/microsoft/boot/efisys.bin).")

    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=3, udf="2.60", vol_ident=_label(label), sys_ident="",
            app_ident_str="SLIM11 BUILDER")
    iso.add_fp(io.BytesIO(README), len(README), iso_path="/README.TXT;1")

    boot_iso_names: dict[Path, str] = {}
    made_iso_dirs: set[str] = set()
    for boot_file, iso_dir, iso_name in (
        (bios, "/BOOT", "ETFSBOOT.COM;1"),
        (uefi, "/EFIBOOT", "EFISYS.BIN;1"),
    ):
        if boot_file:
            if iso_dir not in made_iso_dirs:
                iso.add_directory(iso_path=iso_dir)
                made_iso_dirs.add(iso_dir)
            boot_iso_names[boot_file.resolve()] = f"{iso_dir}/{iso_name}"

    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        if rel_dir != ".":
            iso.add_directory(udf_path="/" + rel_dir)
        for name in sorted(filenames):
            if check_cancel:
                check_cancel()
            full = Path(dirpath) / name
            udf = "/" + (name if rel_dir == "." else f"{rel_dir}/{name}")
            iso_name = boot_iso_names.get(full.resolve())
            iso.add_file(str(full), udf_path=udf, **({"iso_path": iso_name} if iso_name else {}))
            count += 1
    log(f"Laid out {count} files")

    if bios:
        iso.add_eltorito(boot_iso_names[bios.resolve()], bootcatfile="/BOOT.CAT;1",
                         boot_load_size=8, media_name="noemul")
    if uefi:
        iso.add_eltorito(boot_iso_names[uefi.resolve()], bootcatfile="/BOOT.CAT;1",
                         efi=True, media_name="noemul")
    log(f"Writing {iso_path}")
    tmp = iso_path + ".partial"
    try:
        iso.write(tmp)
    finally:
        iso.close()
    os.replace(tmp, iso_path)


def _label(label: str) -> str:
    clean = "".join(c if c.isalnum() or c == "_" else "_" for c in label.upper())
    return clean[:32] or "SLIM11"

