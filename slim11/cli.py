"""Command line entry point. `slim11` with no arguments opens the GUI."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__, catalog
from .engine import BuildConfig, build, inspect_iso
from .jobs import config_from_profile, load_profile, profile_from_config, save_profile
from .tools import Cancelled, CancelToken, ToolError


def _build_config(args: argparse.Namespace) -> BuildConfig:
    profile = load_profile(args.profile) if args.profile else {}
    for key, value in (("source", args.iso), ("edition", args.edition), ("output", args.output),
                       ("format", args.format), ("workDir", args.work_dir)):
        if value is not None:
            profile[key] = value
    if args.compact:
        profile["compact"] = True
    if args.preset:
        profile["preset"] = args.preset
        profile.pop("selection", None)
    config = config_from_profile(profile)
    config.selection = _selection(args, config.selection)
    config.keep_work = args.keep_work
    return config


def _selection(args: argparse.Namespace, sel: catalog.Selection) -> catalog.Selection:
    for attr in ("apps", "files", "tweaks"):
        current = getattr(sel, attr)
        for item in getattr(args, f"add_{attr}") or []:
            if item not in current:
                current.append(item)
        for item in getattr(args, f"skip_{attr}") or []:
            if item in current:
                current.remove(item)
    sel.extra_packages = list(dict.fromkeys(sel.extra_packages + (args.package or [])))
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

    ai = sub.add_parser("ai", help="turn AI agent access (MCP) on or off and connect AI tools")
    ai.add_argument("action", choices=["status", "on", "off"], nargs="?", default="status")
    ai.add_argument("--register", action="append", choices=["claude", "codex", "gemini", "detected"],
                    help="also add Slim11 to this AI tool's MCP config (repeatable)")

    sub.add_parser("mcp", help="run the MCP server on stdio (started by AI tools, not by hand)")

    upd = sub.add_parser("update", help="update Slim11 to the newest GitHub release")
    upd.add_argument("--check", action="store_true", help="only report whether an update is available")

    b = sub.add_parser("build", help="build an ISO without the GUI")
    b.add_argument("iso", nargs="?", help="official Windows 11 ISO (or set it in --profile)")
    b.add_argument("--profile", help="JSON build profile; command-line options override it")
    b.add_argument("--save-profile", metavar="FILE", help="write the resulting profile to FILE and exit")
    b.add_argument("-o", "--output", help="path of the ISO to create")
    b.add_argument("-e", "--edition", type=int, help="edition index (see `slim11 inspect`)")
    b.add_argument("-p", "--preset", choices=[p[0] for p in catalog.PRESETS], help="default: slim")
    for attr in ("apps", "files", "tweaks"):
        b.add_argument(f"--add-{attr}", nargs="*", metavar="ID")
        b.add_argument(f"--skip-{attr}", nargs="*", metavar="ID")
    b.add_argument("--package", action="append", metavar="PREFIX", help="extra provisioned app to remove")
    b.add_argument("--format", choices=["esd", "wim"])
    b.add_argument("--compact", action="store_true", help="install with CompactOS")
    b.add_argument("--work-dir")
    b.add_argument("--keep-work", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command in (None, "gui"):
            from .server import serve
            serve(port=getattr(args, "port", 0), open_browser=not getattr(args, "no_browser", False))
            return 0
        if args.command == "mcp":
            from .mcp_server import serve as serve_mcp
            return serve_mcp()
        if args.command == "ai":
            from . import ai as ai_mod
            if args.action in ("on", "off"):
                ai_mod.set_enabled(args.action == "on")
            for tool in args.register or []:
                for name in (ai_mod.detected_tools() if tool == "detected" else [tool]):
                    try:
                        print(ai_mod.register(name))
                    except (RuntimeError, ValueError, OSError) as exc:
                        print(f"{name}: not registered ({exc})", file=sys.stderr)
            print(ai_mod.status_text())
            return 0
        if args.command == "update":
            from . import updater
            info = updater.check()
            if not info["updateAvailable"]:
                print(f"Slim11 {info['current']} is up to date (latest release: {info['latest']}).")
                return 0
            print(f"Update available: {info['current']} -> {info['latest']}")
            if args.check:
                return 0
            updater.apply(log=print, release=updater.release_from_json_dict(info["release"]))
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
            config = _build_config(args)
            if args.save_profile:
                save_profile(args.save_profile, profile_from_config(config))
                print(f"Saved {args.save_profile}")
                return 0
            token = CancelToken()
            last = [-1]

            def progress(stage: str, value: float) -> None:
                pct = int(value * 100)
                if pct != last[0]:
                    last[0] = pct
                    print(f"[{pct:3d}%] {stage}", file=sys.stderr)

            try:
                build(config, log=lambda line: print(line, flush=True), progress=progress, cancel=token)
            except KeyboardInterrupt:
                token.cancel()
                raise Cancelled() from None
            return 0
    except Cancelled:
        print("Cancelled.", file=sys.stderr)
        return 130
    except (ToolError, ValueError, OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    parser.print_help()
    return 2
