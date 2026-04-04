#!/usr/bin/env bash
set -euo pipefail

# One guided path: optional disk prep → nixos-generate-config → install-orin-nano-super → nixos-install.
# Run from the installer live session (sudo). Default target root: /mnt

die() {
  echo "error: $*" >&2
  exit 1
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  echo "usage: sudo orin-nano-super-install-all [ROOT]"
  echo "  ROOT  mount point for the target system (default: /mnt)"
  echo "Chains: optional prepare-orin-nano-super-disk → nixos-generate-config →"
  echo "        install-orin-nano-super → nixos-install (with final confirmation)."
  exit 0
fi

ROOT="${1:-/mnt}"

echo "═══════════════════════════════════════════════════════════════"
echo " Orin Nano Super — full install (flake)"
echo " Target root: $ROOT"
echo "═══════════════════════════════════════════════════════════════"
echo

read -r -p "Run prepare-orin-nano-super-disk first (wipe disk + GPT EFI/ext4 + mount)? [y/N] " prep
if [[ "${prep,,}" =~ ^y(es)?$ ]]; then
  prepare-orin-nano-super-disk "$ROOT"
fi

if ! mountpoint -q "$ROOT" 2>/dev/null; then
  die "$ROOT is not a mountpoint — partition, mount $ROOT, then run this script again (or answer Y above)."
fi

echo
echo "→ nixos-generate-config --root $ROOT"
nixos-generate-config --root "$ROOT"

echo
echo "→ install-orin-nano-super $ROOT"
install-orin-nano-super "$ROOT"

echo
read -r -p "Run nixos-install now (writes system + bootloader to disk)? [Y/n] " inst
if [[ "${inst,,}" =~ ^n(o)?$ ]]; then
  echo "Skipped. When ready:"
  echo "  sudo nixos-install --root $ROOT --flake $ROOT/etc/nixos#nixos"
  exit 0
fi

echo
echo "→ nixos-install --root $ROOT --flake $ROOT/etc/nixos#nixos"
nixos-install --root "$ROOT" --flake "$ROOT/etc/nixos#nixos"

echo
echo "═══════════════════════════════════════════════════════════════"
echo " Install finished."
echo " Remove the USB installer, then:  sudo reboot"
echo "═══════════════════════════════════════════════════════════════"
