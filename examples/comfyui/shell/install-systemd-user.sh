#!/usr/bin/env bash
# Install a user systemd unit that runs ComfyUI via examples/comfyui/nix/shell.nix (native).
set -euo pipefail

COMFYUI_ROOT="${1:-${COMFYUI_ROOT:-}}"
if [[ -z "$COMFYUI_ROOT" ]]; then
  echo "usage: $0 /path/to/ComfyUI-clone" >&2
  echo "  (directory must contain main.py; or set COMFYUI_ROOT)" >&2
  exit 2
fi

COMFYUI_ROOT="$(cd "$COMFYUI_ROOT" && pwd)"
if [[ ! -f "$COMFYUI_ROOT/main.py" ]]; then
  echo "error: main.py not found in $COMFYUI_ROOT" >&2
  exit 1
fi

EXAMPLE_COMFYUI="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHELL_NIX="$(cd "$EXAMPLE_COMFYUI/nix" && pwd)/shell.nix"
RUN_SH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/run.sh"

if [[ ! -f "$SHELL_NIX" ]]; then
  echo "error: missing $SHELL_NIX" >&2
  exit 1
fi

NIX_SHELL="$(command -v nix-shell)"
if [[ -z "$NIX_SHELL" ]]; then
  echo "error: nix-shell not in PATH" >&2
  exit 1
fi

UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"
UNIT="$UNIT_DIR/comfyui-native.service"

# systemd does not expand COMFYUI_ROOT in WorkingDirectory the same way; bake absolute paths.
cat > "$UNIT" <<EOF
[Unit]
Description=ComfyUI (native, jetpack-nixos nix-shell)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$COMFYUI_ROOT
Environment=COMFYUI_ROOT=$COMFYUI_ROOT
# User units often have a minimal PATH; nix-shell lives under the system profile on NixOS.
Environment=PATH=/run/current-system/sw/bin:/nix/var/nix/profiles/default/bin:/usr/bin:/bin
ExecStart=$RUN_SH
Restart=on-failure
RestartSec=15

[Install]
WantedBy=default.target
EOF

echo "Wrote $UNIT"
echo "Run: systemctl --user daemon-reload && systemctl --user enable --now comfyui-native.service"
echo "Boot without login: sudo loginctl enable-linger \"$USER\""
