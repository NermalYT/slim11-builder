"""MCP server so AI agents (Claude Code, Codex, Antigravity, Gemini CLI, ...) can drive Slim11.

Run with `slim11 mcp`. It speaks the Model Context Protocol over stdio
(newline-delimited JSON-RPC 2.0) and needs no extra packages. It is disabled
unless the user turned AI features on during install, in the app, or with
`slim11 ai on`.
"""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path
from typing import Any, Callable

from . import __version__, catalog, settings
from .engine import inspect_iso
from .jobs import Job, config_from_profile, load_profile, profile_from_config, save_profile
from .setup_files import autounattend, specialize_script
from .tools import find_wimlib, install_hint

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = """Slim11 Builder turns an official Windows 11 ISO into a smaller one.
Typical flow: find_isos -> list_editions -> get_catalog (or get_preset) -> edit a
profile -> preview_build -> start_build -> build_status until state is not
"running". A profile is JSON: {"source", "edition", "output", "preset" or
"selection": {"apps", "files", "tweaks", "extra_packages"}, optional "add"/"remove"
(same shape) to adjust the preset, "format": "esd"|"wim", "compact"}. Builds take 10-30 minutes and need about 3x the ISO size free.
Always show the user the preview and get their OK before start_build."""

_SELECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "apps": {"type": "array", "items": {"type": "string", "enum": [g.id for g in catalog.APP_GROUPS]}},
        "files": {"type": "array", "items": {"type": "string", "enum": [f.id for f in catalog.FILE_REMOVALS]}},
        "tweaks": {"type": "array", "items": {"type": "string", "enum": [t.id for t in catalog.TWEAKS]}},
        "extra_packages": {"type": "array", "items": {"type": "string"},
                           "description": "Extra provisioned app name prefixes to remove."},
    },
    "additionalProperties": False,
}

PROFILE_SCHEMA = {
    "type": "object",
    "description": "Build profile. Start from 'preset' or 'selection'; adjust with 'add'/'remove'.",
    "properties": {
        "source": {"type": "string", "description": "Path to the official Windows 11 ISO."},
        "edition": {"type": "integer", "description": "Edition index from list_editions."},
        "output": {"type": "string", "description": "Path of the ISO to create (must end in .iso)."},
        "preset": {"type": "string", "enum": [p[0] for p in catalog.PRESETS]},
        "selection": {**_SELECTION_SCHEMA, "description": "Full selection; replaces the preset."},
        "add": {**_SELECTION_SCHEMA, "description": "Items to add on top of the preset or selection."},
        "remove": {**_SELECTION_SCHEMA, "description": "Items to drop from the preset or selection."},
        "format": {"type": "string", "enum": ["esd", "wim"], "default": "esd"},
        "compact": {"type": "boolean", "default": False},
        "workDir": {"type": ["string", "null"]},
    },
    "required": ["source", "edition", "output"],
    "additionalProperties": False,
}


def _obj(properties: dict | None = None, required: list[str] | None = None) -> dict:
    schema: dict[str, Any] = {"type": "object", "properties": properties or {}, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


class Server:
    def __init__(self, job: Job | None = None):
        self.job = job or Job()
        self.tools: dict[str, tuple[str, dict, Callable[[dict], Any]]] = {
            "get_status": ("Slim11 version, OS, and whether wimlib (needed for builds) is installed.",
                           _obj(), self.status),
            "get_catalog": ("Everything Slim11 can remove or change: presets, app groups (with package names), "
                            "file removals and settings tweaks, each with an id.", _obj(), lambda _a: catalog.as_dict()),
            "get_preset": ("The selection a preset starts from.",
                           _obj({"preset": {"type": "string", "enum": [p[0] for p in catalog.PRESETS]}}, ["preset"]),
                           lambda a: catalog.preset(a["preset"]).__dict__),
            "find_isos": ("List .iso files in a folder (default: the user's Downloads folder).",
                          _obj({"folder": {"type": "string"}}), self.find_isos),
            "list_editions": ("Editions inside a Windows ISO (index, name, architecture, build).",
                              _obj({"iso": {"type": "string"}}, ["iso"]),
                              lambda a: [e.to_dict() for e in inspect_iso(a["iso"])]),
            "preview_build": ("Validate a profile and show exactly what the build will do: removed files, "
                              "removed apps, the setup script and the answer file. Does not build.",
                              _obj({"profile": PROFILE_SCHEMA}, ["profile"]), self.preview),
            "start_build": ("Start building the ISO described by the profile in the background. "
                            "Only call after the user approved the preview.",
                            _obj({"profile": PROFILE_SCHEMA}, ["profile"]), self.start),
            "build_status": ("Progress, state (running/done/failed/cancelled) and new log lines of the current build.",
                             _obj({"since_line": {"type": "integer", "minimum": 0}}), self.build_status),
            "cancel_build": ("Cancel the running build and delete its temporary files.", _obj(), self.cancel),
            "load_profile": ("Read a saved profile JSON file.", _obj({"path": {"type": "string"}}, ["path"]),
                             lambda a: load_profile(a["path"])),
            "save_profile": ("Validate and save a profile JSON file for later or for the GUI/CLI "
                             "(`slim11 build --profile FILE`).",
                             _obj({"path": {"type": "string"}, "profile": PROFILE_SCHEMA}, ["path", "profile"]),
                             self.save),
        }

    # --- tools -------------------------------------------------------------

    def status(self, _args: dict) -> dict:
        return {"version": __version__, "platform": platform.system(), "python": platform.python_version(),
                "wimlib": find_wimlib(), "wimlib_install_hint": None if find_wimlib() else install_hint(),
                "build_state": self.job.snapshot(10 ** 9)["state"]}

    def find_isos(self, args: dict) -> list[dict]:
        folder = Path(args.get("folder") or Path.home() / "Downloads").expanduser()
        if not folder.is_dir():
            raise ValueError(f"Not a folder: {folder}")
        return [{"path": str(p), "size_gib": round(p.stat().st_size / 1024 ** 3, 2)}
                for p in sorted(folder.iterdir()) if p.suffix.lower() == ".iso" and p.is_file()]

    def preview(self, args: dict) -> dict:
        config = config_from_profile(args["profile"])
        source = Path(config.source_iso).expanduser()
        if not source.is_file():
            raise ValueError(f"Source ISO not found: {source}")
        editions = {e.index: e for e in inspect_iso(str(source))}
        if config.edition_index not in editions:
            raise ValueError(f"Edition {config.edition_index} not in ISO; available: {sorted(editions)}")
        edition = editions[config.edition_index]
        return {
            "profile": profile_from_config(config),
            "edition": edition.to_dict(),
            "output_exists": Path(config.output_iso).expanduser().exists(),
            "files_removed_from_image": config.selection.file_paths(),
            "apps_removed_during_setup": config.selection.packages(),
            "tweaks": [t.title for t in config.selection.chosen_tweaks()],
            "specialize_script": specialize_script(config.selection),
            "autounattend_xml": autounattend(config.selection, edition.architecture,
                                             compact=config.compact_install),
        }

    def start(self, args: dict) -> dict:
        if not find_wimlib():
            raise ValueError("wimlib-imagex is not installed. " + install_hint())
        config = config_from_profile(args["profile"])
        self.job.start(config)
        return {"started": True, "output": config.output_iso,
                "next": "Call build_status every minute or so until state is not 'running'."}

    def build_status(self, args: dict) -> dict:
        snap = self.job.snapshot(int(args.get("since_line", 0)))
        snap["log"] = snap["log"][-200:]
        return snap

    def cancel(self, _args: dict) -> dict:
        self.job.cancel()
        return {"cancelling": self.job.snapshot(10 ** 9)["state"] == "running"}

    def save(self, args: dict) -> dict:
        save_profile(args["path"], args["profile"])
        return {"saved": str(Path(args["path"]).expanduser())}

    # --- protocol ----------------------------------------------------------

    def handle(self, msg: dict) -> dict | None:
        method, req_id = msg.get("method"), msg.get("id")
        if req_id is None:          # notification (e.g. notifications/initialized)
            return None
        try:
            result = self._dispatch(method, msg.get("params") or {})
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except _RpcError as err:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": err.code, "message": str(err)}}

    def _dispatch(self, method: str | None, params: dict) -> dict:
        if method == "initialize":
            requested = params.get("protocolVersion")
            version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            return {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "slim11", "title": "Slim11 Builder", "version": __version__},
                    "instructions": INSTRUCTIONS}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [{"name": name, "description": desc, "inputSchema": schema}
                              for name, (desc, schema, _fn) in self.tools.items()]}
        if method == "tools/call":
            name = params.get("name")
            if name not in self.tools:
                raise _RpcError(-32602, f"Unknown tool: {name}")
            try:
                result = self.tools[name][2](params.get("arguments") or {})
                return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}], "isError": False}
            except Exception as exc:  # tool errors go back to the model, not the protocol
                return {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True}
        raise _RpcError(-32601, f"Method not found: {method}")


class _RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


DISABLED_MESSAGE = ("Slim11 AI features are turned off. Turn them on with `slim11 ai on` "
                    "(or in the app under About & settings), then restart your AI tool.")


def serve(stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    if not settings.ai_enabled():
        print(DISABLED_MESSAGE, file=sys.stderr)
        return 1
    server = Server()
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            reply = server.handle(msg) if isinstance(msg, dict) else None
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()
    server.job.cancel()
    return 0
