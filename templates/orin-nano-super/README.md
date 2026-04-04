# Orin Nano Super — NixOS template

For **Jetson Orin Nano Super Developer Kit** (`som = orin-nano`, `carrierBoard = devkit`, `super = true`).

## Guided (recommended)

From the **installer live session** (this repo’s ISO includes the helpers):

**One command (wizard):** `sudo orin-nano-super-install-all` — optional disk prep (`prepare-orin-nano-super-disk`), then `nixos-generate-config`, `install-orin-nano-super`, and (after confirmation) `nixos-install`. At the end: remove USB, `sudo reboot`.

**Or step by step:**

1. **Disk (optional automation)** — `sudo prepare-orin-nano-super-disk` — **yes** wipes the chosen disk (GPT: EFI + ext4) and mounts `/mnt`; **no** prints manual partitioning steps only.

2. `sudo nixos-generate-config --root /mnt`

3. `sudo install-orin-nano-super`

4. `sudo nixos-install --root /mnt --flake /mnt/etc/nixos#nixos`

To print manual steps only: `prepare-orin-nano-super-disk --manual-only`

## After first boot

`jetpack-nixos.examplesHome` is **enabled** in `configuration.nix`: example stacks are **copied once** into each normal user’s home (e.g. `~/Ollama`, `~/lib`, …). See [`docs/install-jetson.md`](../../docs/install-jetson.md#after-first-boot).

## Dry-run (test on a running NixOS Nano without installing)

- **Partitioning (print-only):** `sudo prepare-orin-nano-super-disk --dry-run` — lists the exact `wipefs` / `parted` / `mkfs` / `mount` commands; does not touch disks. Optional `DISK=/dev/nvme0n1` to skip the prompt.
- **Flake + user config:** `sudo install-orin-nano-super --dry-run` — writes `flake.nix`, `configuration.nix`, `local.nix` under `/tmp/orin-nano-super-dry.*/etc/nixos`, copies `hardware-configuration.nix` from **`/etc/nixos`** (or `/mnt/etc/nixos`) so evaluation matches this machine, then runs `nix flake metadata`, a small `nix eval`, and `nix build --dry-run …#nixos` if your `nix` supports it. Does **not** change `/mnt` or your running system.
  - `--no-nix-check` — skip Nix validation (faster, offline-ish).
  - `--clean` — delete the temp dir after success; default keeps it for inspection.

## Manual

1. Copy everything in this directory to `/mnt/etc/nixos/`.
2. Edit `local.nix` (hostname, user, `initialPassword` or `hashedPassword`).
3. Ensure `flake.nix` `inputs.jetpack.url` points at the flake you use.
4. `nixos-install --root /mnt --flake /mnt/etc/nixos#nixos`

After boot, run `passwd` immediately if you used `initialPassword`.
