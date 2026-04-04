#!/usr/bin/env bash
# Run ComfyUI in the Jetson-oriented nix-shell (native). Requires a git clone with main.py.
set -euo pipefail

EXAMPLE_COMFYUI="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHELL_NIX="$EXAMPLE_COMFYUI/nix/shell.nix"
ROOT="${COMFYUI_ROOT:-}"

if [[ -z "$ROOT" ]]; then
  echo "Set COMFYUI_ROOT to your ComfyUI clone (directory containing main.py)." >&2
  echo "Example: export COMFYUI_ROOT=\"\$HOME/ComfyUI-app\"" >&2
  exit 2
fi

if [[ ! -f "$SHELL_NIX" ]]; then
  echo "error: missing $SHELL_NIX" >&2
  exit 1
fi

cd "$ROOT"
if [[ ! -f main.py ]]; then
  echo "error: main.py not in $ROOT — clone ComfyUI there first." >&2
  exit 1
fi

run_cmd="comfyui_run"
for a in --novram --disable-pinned-memory "$@"; do
  run_cmd+=" $(printf '%q' "$a")"
done

exec nix-shell "$SHELL_NIX" --run "$run_cmd"
