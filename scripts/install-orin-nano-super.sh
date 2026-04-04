#!/usr/bin/env bash
# shellcheck disable=SC2016
set -euo pipefail

# Install Orin Nano Super flake templates into a mounted NixOS root (default /mnt).
# Templates: set TEMPLATES_DIR to the directory containing flake.nix (packaged on the ISO).
#
# --dry-run: write under /tmp/orin-nano-super-dry.XXXXXX, copy hardware-configuration from
#            this machine, optional nix validation; does not touch /mnt.

TEMPLATES_DIR="${TEMPLATES_DIR:-}"
DRY_RUN=false
RUN_NIX_CHECK=true
CLEAN_DRY=false
ROOT="/mnt"
TARGET=""
DRY_BASE=""

die() {
  echo "error: $*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
usage: install-orin-nano-super [options] [ROOT]

  ROOT              install root (default /mnt). Ignored with --dry-run.

  --dry-run         write flake under /tmp/orin-nano-super-dry.*/etc/nixos only;
                    copy hardware-configuration.nix from /etc/nixos or /mnt/etc/nixos
  --no-nix-check    skip nix flake metadata / eval / dry-build
  --clean           with --dry-run, delete the temp dir after a successful run
EOF
}

resolve_templates() {
  if [[ -n "$TEMPLATES_DIR" && -f "$TEMPLATES_DIR/flake.nix" ]]; then
    return 0
  fi
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [[ -f "$here/../templates/orin-nano-super/flake.nix" ]]; then
    TEMPLATES_DIR="$(cd "$here/../templates/orin-nano-super" && pwd)"
    return 0
  fi
  die "could not find templates (set TEMPLATES_DIR to templates/orin-nano-super)"
}

valid_hostname() {
  [[ "$1" =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]]
}

# Nix attribute name for users.users.<name> (no hyphen).
valid_username() {
  [[ "$1" =~ ^[a-z_][a-z0-9_]{0,31}$ ]]
}

prompt() {
  local var="$1" text="$2"
  local val=""
  read -r -p "$text " val || true
  printf '%s' "$val"
}

prompt_secret() {
  local text="$1"
  local val=""
  read -r -s -p "$text " val || true
  echo
  printf '%s' "$val"
}

run_nix_validate() {
  local flake_dir="$1"
  command -v nix >/dev/null 2>&1 || {
    echo "warning: nix not in PATH; skipping validation"
    return 0
  }
  echo "Nix: flake metadata..."
  nix flake metadata "$flake_dir" --no-write-lock-file >/dev/null
  echo "Nix: evaluating nixosConfigurations.nixos..."
  nix eval --accept-flake-config "$flake_dir#nixosConfigurations.nixos.config.networking.hostName" >/dev/null
  if nix build --help 2>&1 | grep -qF -- '--dry-run'; then
    echo "Nix: nix build --dry-run (no binaries installed)..."
    nix build --dry-run --no-link --accept-flake-config "$flake_dir#nixos"
  else
    echo "note: this nix has no 'nix build --dry-run'; metadata + eval checks only"
  fi
  echo "Nix validation OK."
}

POSITIONAL=()
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --no-nix-check) RUN_NIX_CHECK=false ;;
    --clean) CLEAN_DRY=true ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      POSITIONAL+=("$arg")
      ;;
  esac
done

if ((${#POSITIONAL[@]} > 1)); then
  die "too many arguments"
fi
if ((${#POSITIONAL[@]} == 1)); then
  ROOT="${POSITIONAL[0]}"
fi

resolve_templates

if [[ "$DRY_RUN" == true ]]; then
  DRY_BASE="$(mktemp -d /tmp/orin-nano-super-dry.XXXXXX)"
  TARGET="$DRY_BASE/etc/nixos"
  mkdir -p "$TARGET"
  hw=""
  for c in /etc/nixos/hardware-configuration.nix /mnt/etc/nixos/hardware-configuration.nix; do
    if [[ -f "$c" ]]; then
      hw="$c"
      break
    fi
  done
  [[ -n "$hw" ]] || die "dry-run: need hardware-configuration.nix at /etc/nixos or /mnt/etc/nixos (run on a NixOS system or after mounting /mnt)"
  cp "$hw" "$TARGET/hardware-configuration.nix"
  echo "=== DRY RUN — writing only under $TARGET ==="
  echo
else
  TARGET="$ROOT/etc/nixos"
  [[ -d "$ROOT" ]] || die "mount root does not exist: $ROOT"
  [[ -f "$ROOT/etc/nixos/hardware-configuration.nix" ]] ||
    die "missing $ROOT/etc/nixos/hardware-configuration.nix — partition & mount $ROOT first (optional: sudo prepare-orin-nano-super-disk), then: sudo nixos-generate-config --root $ROOT"
  mkdir -p "$TARGET"
fi

echo "Using templates from: $TEMPLATES_DIR"
echo

hostname="$(prompt hostname 'Hostname (e.g. orin-nano): ')"
hostname="${hostname:-orin-nano}"
valid_hostname "$hostname" || die "invalid hostname (lowercase letters, digits, hyphens; start with letter or digit)"

username="$(prompt username 'Username (login): ')"
[[ -n "$username" ]] || die "username is required"
valid_username "$username" || die "invalid username (letters, digits, underscore; start with letter or _; no hyphen)"

pass1="$(prompt_secret 'Password (hidden): ')"
pass2="$(prompt_secret 'Password again: ')"
[[ "$pass1" == "$pass2" ]] || die "passwords do not match"
[[ -n "$pass1" ]] || die "empty password"

if ! command -v openssl >/dev/null 2>&1; then
  die "openssl not found (needed for password hash)"
fi
hashed="$(openssl passwd -6 "$pass1")"
[[ -n "$hashed" ]] || die "failed to hash password"
# Nix '' string: escape single quotes as ''
hash_nix="${hashed//\'/\'\'}"

jetpack_url="${JETPACK_FLAKE_URL:-}"
if [[ -z "$jetpack_url" ]]; then
  jetpack_url="$(prompt jetpack 'Jetpack flake URL [github:fr4iser90/nixos-jetson-orin-nano]: ')"
  jetpack_url="${jetpack_url:-github:fr4iser90/nixos-jetson-orin-nano}"
fi

cp -f "$TEMPLATES_DIR/configuration.nix" "$TARGET/configuration.nix"
cp -f "$TEMPLATES_DIR/flake.nix" "$TARGET/flake.nix"

# Pin jetpack input in the copied flake (quoted for Nix string).
escaped="${jetpack_url//\\/\\\\}"
escaped="${escaped//\"/\\\"}"
sed -i.bak "s|jetpack.url = \".*\";|jetpack.url = \"$escaped\";|" "$TARGET/flake.nix"
rm -f "$TARGET/flake.nix.bak"

cat >"$TARGET/local.nix" <<EOF
# Generated by install-orin-nano-super — edit as needed.
{ ... }:

{
  networking.hostName = "$hostname";

  users.users.$username = {
    isNormalUser = true;
    extraGroups = [
      "wheel"
      "video"
      "docker"
    ];
    hashedPassword = '$hash_nix';
  };

  security.sudo.wheel.enable = true;
}
EOF

chmod u+rw,go-rwx "$TARGET/local.nix" 2>/dev/null || true

echo
echo "Wrote $TARGET/{flake.nix,configuration.nix,local.nix}"

if [[ "$DRY_RUN" == true ]]; then
  if [[ "$RUN_NIX_CHECK" == true ]]; then
    echo
    run_nix_validate "$TARGET"
  fi
  echo
  echo "Dry run finished. Your running system and /mnt were not modified."
  if [[ "$CLEAN_DRY" == true ]]; then
    rm -rf "$DRY_BASE"
    echo "Removed temp dir."
  else
    echo "Inspect:  $TARGET"
    echo "Remove:   rm -rf $DRY_BASE"
    echo "Real install: partition/mount /mnt, nixos-generate-config, then run without --dry-run"
  fi
  exit 0
fi

echo "Next:"
echo "  sudo nixos-install --root $ROOT --flake $TARGET#nixos"
echo "Then reboot, log in as '$username', and run: passwd"
