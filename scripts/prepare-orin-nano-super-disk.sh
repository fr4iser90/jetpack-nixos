#!/usr/bin/env bash
set -euo pipefail

# Optional: wipe disk, GPT (EFI + ext4 root), mount to /mnt. Otherwise print manual steps.
# Set DISK=/dev/nvme0n1 to skip the disk prompt. Intended for the Jetson installer live session.

ROOT="/mnt"
DISK="${DISK:-}"
DRY_RUN=false

print_manual() {
  cat <<'EOF'
Manual partitioning (NixOS handbook, UEFI)

  1) Pick the target disk:   lsblk -fp
     Typical on Jetson:      /dev/nvme0n1  or  /dev/mmcblk0

  2) Partition (GPT): EFI ~512 MiB (type EF00), rest for Linux root.

  3) Format:
       mkfs.fat -F32 -n boot <EFI_PARTITION>
       mkfs.ext4 -L nixos  <ROOT_PARTITION>

  4) Mount:
       mount <ROOT_PARTITION> /mnt
       mkdir -p /mnt/boot
       mount <EFI_PARTITION> /mnt/boot

  5) Continue the automated Jetson path:
       sudo nixos-generate-config --root /mnt
       sudo install-orin-nano-super
       sudo nixos-install --root /mnt --flake /mnt/etc/nixos#nixos

  Or run automatic partitioning (when you are ready):
       sudo prepare-orin-nano-super-disk

  Dry-run (print commands only, no disk I/O):
       sudo prepare-orin-nano-super-disk --dry-run
EOF
}

die() {
  echo "error: $*" >&2
  exit 1
}

set_partition_vars() {
  local base
  base="$(basename "$DISK")"
  if [[ "$base" == nvme* || "$base" == mmcblk* || "$base" == loop* ]]; then
    P1="${DISK}p1"
    P2="${DISK}p2"
  else
    P1="${DISK}1"
    P2="${DISK}2"
  fi
}

print_would_run() {
  echo "Would run (example — nothing was executed):"
  echo "  wipefs -a $DISK"
  echo "  parted -s $DISK mklabel gpt"
  echo "  parted -s $DISK mkpart ESP fat32 1MiB 512MiB"
  echo "  parted -s $DISK set 1 esp on"
  echo "  parted -s $DISK mkpart primary ext4 512MiB 100%"
  echo "  partprobe $DISK   # if available"
  echo "  mkfs.fat -F32 -n boot $P1"
  echo "  mkfs.ext4 -L nixos -F $P2"
  echo "  mkdir -p $ROOT"
  echo "  mount $P2 $ROOT"
  echo "  mkdir -p $ROOT/boot"
  echo "  mount $P1 $ROOT/boot"
  echo
  echo "Then:"
  echo "  sudo nixos-generate-config --root $ROOT"
  echo "  sudo install-orin-nano-super $ROOT"
  echo "  sudo nixos-install --root $ROOT --flake $ROOT/etc/nixos#nixos"
}

ARGS=()
for a in "$@"; do
  case "$a" in
    --dry-run) DRY_RUN=true ;;
    --manual-only)
      print_manual
      exit 0
      ;;
    -h | --help)
      echo "usage: prepare-orin-nano-super-disk [--dry-run] [--manual-only] [ROOT]"
      echo "       prepare-orin-nano-super-disk [MOUNT_ROOT]   (default /mnt)"
      echo "env:   DISK=/dev/nvme0n1   (optional; for --dry-run used in printed commands)"
      exit 0
      ;;
    *)
      ARGS+=("$a")
      ;;
  esac
done

if ((${#ARGS[@]} > 1)); then
  die "too many arguments (expected at most one mount root)"
fi
ROOT="${ARGS[0]:-/mnt}"

if [[ "$DRY_RUN" == true ]]; then
  echo "=== DRY RUN — no partition tables or filesystems will be changed ==="
  echo
  if [[ -z "$DISK" ]]; then
    lsblk -dpno NAME,SIZE,MODEL,TRAN 2>/dev/null || lsblk || true
    echo
    read -r -p "Disk path to show in commands (e.g. /dev/nvme0n1) [/dev/nvme0n1]: " inp
    DISK="${inp:-/dev/nvme0n1}"
  fi
  [[ -n "$DISK" ]] || die "no disk path"
  set_partition_vars
  print_would_run
  echo "No changes made. Reboot or ignore; your system was not modified."
  exit 0
fi

echo "This tool can ERASE an entire disk and create: EFI (FAT32) + Linux (ext4), then mount on $ROOT."
read -r -p "Run automatic partitioning now? [y/N] " ans
if [[ ! "${ans,,}" =~ ^y(es)?$ ]]; then
  print_manual
  exit 0
fi

if [[ -z "$DISK" ]]; then
  echo
  lsblk -dpno NAME,SIZE,MODEL,TRAN 2>/dev/null || lsblk
  echo
  read -r -p "Enter whole-disk device to ERASE (e.g. /dev/nvme0n1): " DISK
fi
[[ -n "$DISK" ]] || die "no disk given"
[[ -b "$DISK" ]] || die "not a block device: $DISK"

if grep -q "^$DISK" /proc/mounts 2>/dev/null; then
  die "$DISK appears mounted; unmount it first"
fi

read -r -p "Type the disk path again to confirm TOTAL ERASE: " confirm
[[ "$confirm" == "$DISK" ]] || die "confirmation mismatch — aborted"

read -r -p "Last chance. Type ERASE to continue: " final
[[ "$final" == "ERASE" ]] || die "aborted"

set_partition_vars

command -v parted >/dev/null || die "parted not found"
command -v wipefs >/dev/null || die "wipefs not found"

wipefs -a "$DISK"
parted -s "$DISK" mklabel gpt
parted -s "$DISK" mkpart ESP fat32 1MiB 512MiB
parted -s "$DISK" set 1 esp on
parted -s "$DISK" mkpart primary ext4 512MiB 100%
# Refresh partition nodes
if command -v partprobe >/dev/null 2>&1; then
  partprobe "$DISK" || true
fi
sleep 2
[[ -b "$P1" && -b "$P2" ]] || die "partitions not found ($P1 $P2); try replugging or a short sleep"

mkfs.fat -F32 -n boot "$P1"
mkfs.ext4 -L nixos -F "$P2"

mkdir -p "$ROOT"
mount "$P2" "$ROOT"
mkdir -p "$ROOT/boot"
mount "$P1" "$ROOT/boot"

echo
echo "Disk prepared and mounted on $ROOT."
echo "Next:"
echo "  sudo nixos-generate-config --root $ROOT"
echo "  sudo install-orin-nano-super $ROOT"
echo "  sudo nixos-install --root $ROOT --flake $ROOT/etc/nixos#nixos"
