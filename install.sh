#!/bin/sh
# Slim11 Builder installer for Linux and macOS.
#
#   curl -fsSL https://github.com/NermalYT/slim11-builder/releases/latest/download/install.sh | sh
#
# Options (pass after `sh -s --` when piping):
#   --ai | --no-ai     turn AI agent features on/off without asking
#   --register         with --ai: add Slim11 to AI tools found on this computer
#   --version vX.Y.Z   install a specific release (default: latest)
#   --dir PATH         install location (default: ~/.slim11)
#   --yes              accept defaults for every question (AI stays off unless --ai)
set -eu

REPO="${SLIM11_REPO:-NermalYT/slim11-builder}"
DIR="${HOME}/.slim11"
VERSION=""
AI=""
REGISTER=""
YES=""

while [ $# -gt 0 ]; do
  case "$1" in
    --ai) AI=on ;;
    --no-ai) AI=off ;;
    --register) REGISTER=yes ;;
    --version) VERSION="$2"; shift ;;
    --dir) DIR="$2"; shift ;;
    --yes|-y) YES=yes ;;
    -h|--help) sed -n '2,13p' "$0" 2>/dev/null || true; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

say() { printf '%s\n' "$*"; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

# Ask a yes/no question on the terminal even when this script is piped into sh.
ask() {  # ask "Question" default(y|n)
  if [ -n "$YES" ] || ! { [ -r /dev/tty ] && : < /dev/tty; } 2>/dev/null; then
    [ "$2" = y ]; return
  fi
  hint="[y/N]"; [ "$2" = y ] && hint="[Y/n]"
  printf '%s %s ' "$1" "$hint" > /dev/tty
  read -r answer < /dev/tty || answer=""
  case "$answer" in
    [Yy]*) return 0 ;;
    [Nn]*) return 1 ;;
    *) [ "$2" = y ] ;;
  esac
}

PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    PY="$candidate"; break
  fi
done
[ -n "$PY" ] || fail "Python 3.10 or newer is required. Install it from your package manager or python.org."
"$PY" -c 'import venv, ensurepip' 2>/dev/null ||
  fail "Python's venv module is missing. On Debian/Ubuntu: sudo apt install python3-venv"

if [ -n "$VERSION" ]; then
  API="https://api.github.com/repos/${REPO}/releases/tags/${VERSION}"
else
  API="https://api.github.com/repos/${REPO}/releases/latest"
fi
if [ -n "${SLIM11_WHEEL:-}" ]; then
  WHEEL="$SLIM11_WHEEL"   # local or custom wheel (used by CI)
else
say "Finding the Slim11 release..."
WHEEL=$("$PY" - "$API" <<'EOF'
import json, sys, urllib.request
req = urllib.request.Request(sys.argv[1], headers={"Accept": "application/vnd.github+json",
                                                  "User-Agent": "slim11-installer"})
data = json.load(urllib.request.urlopen(req, timeout=30))
urls = [a["browser_download_url"] for a in data.get("assets", []) if a["name"].endswith(".whl")]
if not urls:
    sys.exit("release has no wheel")
print(urls[0])
EOF
) || fail "Could not read the release from GitHub."
fi

say "Installing into ${DIR}"
"$PY" -m venv "${DIR}/venv"
"${DIR}/venv/bin/python" -m pip install --quiet --upgrade pip
"${DIR}/venv/bin/python" -m pip install --quiet --upgrade "$WHEEL"
SLIM11="${DIR}/venv/bin/slim11"

mkdir -p "${HOME}/.local/bin"
ln -sf "$SLIM11" "${HOME}/.local/bin/slim11"

say ""
say "AI agent features let AI coding tools (Claude Code, Codex, Antigravity, Gemini CLI, ...)"
say "control Slim11 through MCP: read your ISO, change what gets removed, preview and run builds."
if [ -z "$AI" ]; then
  if ask "Turn on AI agent features?" n; then AI=on; else AI=off; fi
fi
"$SLIM11" ai "$AI" >/dev/null
say "AI features: ${AI} (change any time with 'slim11 ai on' / 'slim11 ai off' or in the app)"

if [ "$AI" = on ]; then
  tools=$("${DIR}/venv/bin/python" -c 'from slim11.ai import detected_tools; print(" ".join(detected_tools()))')
  if [ -n "$tools" ]; then
    # Editing another tool's config needs a yes: --register, or answering the question.
    if [ -n "$REGISTER" ] || { [ -z "$YES" ] && ask "Add Slim11 to these AI tools: ${tools}?" y; }; then
      "$SLIM11" ai on --register detected 2>&1 | grep -E '^(Claude Code|Codex|Gemini CLI|claude|codex|gemini)' || true
    else
      say "Not added to ${tools}. Run 'slim11 ai on --register detected' later, or 'slim11 ai' for manual setup."
    fi
  else
    say "No AI tools detected. Run 'slim11 ai' to see how to connect one."
  fi
fi

say ""
if command -v wimlib-imagex >/dev/null 2>&1; then
  say "wimlib: found"
else
  case "$(uname -s)" in
    Darwin) say "Builds need wimlib: brew install wimlib" ;;
    *) say "Builds need wimlib: sudo apt install wimtools  (Fedora: sudo dnf install wimlib-utils, Arch: sudo pacman -S wimlib)" ;;
  esac
fi

case ":${PATH}:" in
  *":${HOME}/.local/bin:"*) say "Done. Run: slim11" ;;
  *) say "Done. Run: ${HOME}/.local/bin/slim11   (add ~/.local/bin to your PATH to just type 'slim11')" ;;
esac
