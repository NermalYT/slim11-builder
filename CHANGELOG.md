# Changelog

## v0.1.0

First release.

- Cross-platform builder (Linux, macOS, Windows) with a Fluent-style wizard GUI and a CLI.
- Slim (Tiny11-style), Light and Custom presets.
- Removes provisioned apps and applies settings during Windows Setup; deletes Edge, WebView2 and OneDrive files offline with wimlib.
- Skips the TPM, Secure Boot, CPU and RAM checks.
- ESD (smallest) or WIM (faster) output; ESD compression threads are capped by free memory.
- UEFI and BIOS bootable ISO written in pure Python. UEFI boot asks "Press any key" like Microsoft's media, so Setup does not loop after its first restart.
- `slim11 update` and an in-app banner update Slim11 to the newest GitHub release.
- One-line installers for Linux/macOS (`install.sh`) and Windows (`install.ps1`) that ask whether to turn on AI agent features.
- AI agent access (off by default): a built-in MCP server (`slim11 mcp`) lets Claude Code, Codex, Antigravity, Gemini CLI and other MCP clients inspect ISOs, edit build profiles, preview and run builds. Toggle with `slim11 ai on|off` or in the app.
- JSON build profiles (`slim11 build --profile`, `--save-profile`) with `add`/`remove` adjustments on top of a preset.

Tested by driving the MCP server from Claude Code (find ISO, list editions, preview), and by building Windows 11 Pro build 26300 (official English x64 ISO) on Ubuntu 24.04 and installing it in a QEMU/KVM UEFI VM without TPM or Secure Boot.
