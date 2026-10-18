"""Turning AI agent access on/off and connecting Slim11 to AI coding tools."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import settings


def server_command() -> list[str]:
    """How an AI tool should launch the MCP server: this exact Python environment."""
    return [sys.executable, "-m", "slim11", "mcp"]


def config_snippets() -> dict[str, str]:
    cmd, *args = server_command()
    json_cfg = json.dumps({"mcpServers": {"slim11": {"command": cmd, "args": args}}}, indent=2)
    toml_args = ", ".join(json.dumps(a) for a in args)
    return {
        "Claude Code": "claude mcp add --scope user slim11 -- " + " ".join(_shell_quote(c) for c in server_command()),
        "Codex (~/.codex/config.toml)": f"[mcp_servers.slim11]\ncommand = {json.dumps(cmd)}\nargs = [{toml_args}]",
        "Gemini CLI (~/.gemini/settings.json), Antigravity (Manage MCP Servers > View raw config), "
        "Cursor and other MCP clients": json_cfg,
    }


def _shell_quote(text: str) -> str:
    return f'"{text}"' if any(c in text for c in ' "\'') else text


def detected_tools() -> list[str]:
    found = []
    if shutil.which("claude"):
        found.append("claude")
    if shutil.which("codex") or (Path.home() / ".codex").is_dir():
        found.append("codex")
    if shutil.which("gemini") or (Path.home() / ".gemini" / "settings.json").is_file():
        found.append("gemini")
    return found


def register(tool: str) -> str:
    """Add Slim11 to an AI tool's MCP config. Returns a short description of what changed."""
    cmd, *args = server_command()
    if tool == "claude":
        exe = shutil.which("claude")
        if not exe:
            raise RuntimeError("Claude Code (`claude`) is not on PATH.")
        subprocess.run([exe, "mcp", "remove", "--scope", "user", "slim11"], capture_output=True)
        result = subprocess.run([exe, "mcp", "add", "--scope", "user", "slim11", "--", *server_command()],
                                capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip() or "claude mcp add failed")
        return "Claude Code: added user-scoped MCP server 'slim11'"
    if tool == "codex":
        path = Path.home() / ".codex" / "config.toml"
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        block = config_snippets()["Codex (~/.codex/config.toml)"]
        if "[mcp_servers.slim11]" in text:
            return f"Codex: {path} already has [mcp_servers.slim11]; left unchanged"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + ("\n" if text and not text.endswith("\n") else "") + "\n" + block + "\n",
                        encoding="utf-8")
        return f"Codex: added [mcp_servers.slim11] to {path}"
    if tool == "gemini":
        path = Path.home() / ".gemini" / "settings.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        data.setdefault("mcpServers", {})["slim11"] = {"command": cmd, "args": args}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return f"Gemini CLI: added mcpServers.slim11 to {path}"
    raise ValueError(f"Unknown tool: {tool} (use claude, codex or gemini)")


def set_enabled(on: bool) -> None:
    settings.save(ai_features=on)


def status_text() -> str:
    on = settings.ai_enabled()
    lines = [f"AI features: {'on' if on else 'off'} (setting stored in {settings.path()})"]
    if on:
        lines.append("Connect your AI tool to Slim11's MCP server:")
        for name, snippet in config_snippets().items():
            lines += ["", f"  {name}:", *("    " + l for l in snippet.splitlines())]
    else:
        lines.append("Turn on with: slim11 ai on")
    return "\n".join(lines)
