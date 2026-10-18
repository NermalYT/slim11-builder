#!/usr/bin/env sh
# Run Slim11 Builder from a source checkout (Linux/macOS).
cd "$(dirname "$0")" || exit 1
if [ ! -d .venv ]; then
  python3 -m venv .venv && .venv/bin/pip install -q -e . || exit 1
fi
exec .venv/bin/python -m slim11 "$@"
