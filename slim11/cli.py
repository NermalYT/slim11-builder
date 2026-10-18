"""Command line entry point. `slim11` with no arguments opens the GUI."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__, catalog
from .engine import BuildConfig, build, inspect_iso
from .tools import Cancelled, CancelToken, ToolError


def _selection(args: argparse.Namespace) -> catalog.Selection:
    sel = catalog.preset(args.preset)
    for attr in ("apps", "files", "tweaks"):
        current = getattr(sel, attr)
        for item in getattr(args, f"add_{attr}") or []:
            if item not in current:
                current.append(item)
        for item in getattr(args, f"skip_{attr}") or []:
            if item in current:
                current.remove(item)
    sel.extra_packages = args.package or []
    sel.validate()
    return sel


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="slim11", description="Build a smaller Windows 11 ISO on Linux, macOS or Windows.")
    parser.add_argument("--version", action="version", version=f"slim11 {__version__}")
    sub = parser.add_subparsers(dest="command")

    gui = sub.add_parser("gui", help="open the graphical builder (default)")
    gui.add_argument("--port", type=int, default=0)
    gui.add_argument("--no-browser", action="store_true", help="print the URL instead of opening a browser")

    ins = sub.add_parser("inspect", help="list the editions in an ISO")
    ins.add_argument("iso")
    ins.add_argument("--json", action="store_true")

    sub.add_parser("catalog", help="print everything that can be removed or changed (JSON)")

    b = sub.add_parser("build", help="build an ISO without the GUI")
    b.add_argument("iso", help="official Windows 11 ISO")
    b.add_argument("-o", "--output", required=True, help="path of the ISO to create")
    b.add_argument("-e", "--edition", type=int, required=True, help="edition index (see `slim11 inspect`)")
    b.add_argument("-p", "--preset", default="slim", choices=[p[0] for p in catalog.PRESETS])
    for attr in ("apps", "files", "tweaks"):
        b.add_argument(f"--add-{attr}", nargs="*", metavar="ID")
        b.add_argument(f"--skip-{attr}", nargs="*", metavar="ID")
    b.add_argument("--package", action="append", metavar="PREFIX", help="extra provisioned app to remove")
    b.add_argument("--format", choices=["esd", "wim"], default="esd")
    b.add_argument("--compact", action="store_true", help="install with CompactOS")
    b.add_argument("--work-dir")
    b.add_argument("--keep-work", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command in (None, "gui"):
            from .server import serve
            serve(port=getattr(args, "port", 0), open_browser=not getattr(args, "no_browser", False))
            return 0
        if args.command == "catalog":
            print(json.dumps(catalog.as_dict(), indent=2))
            return 0
        if args.command == "inspect":
            editions = inspect_iso(args.iso)
            if args.json:
                print(json.dumps([e.to_dict() for e in editions], indent=2))
            else:
                for e in editions:
                    print(f"{e.index:>3}  {e.name}  ({e.architecture}, build {e.build})")
            return 0
        if args.command == "build":
            config = BuildConfig(source_iso=args.iso, edition_index=args.edition, output_iso=args.output,
                                 selection=_selection(args), work_dir=args.work_dir, format=args.format,
                                 compact_install=args.compact, keep_work=args.keep_work)
            token = CancelToken()
            last = [-1]

            def progress(stage: str, value: float) -> None:
                pct = int(value * 100)
                if pct != last[0]:
                    last[0] = pct
                    print(f"[{pct:3d}%] {stage}", file=sys.stderr)

            try:
                build(config, log=print, progress=progress, cancel=token)
            except KeyboardInterrupt:
                token.cancel()
                raise Cancelled() from None
            return 0
    except Cancelled:
        print("Cancelled.", file=sys.stderr)
        return 130
    except (ToolError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    parser.print_help()
    return 2
