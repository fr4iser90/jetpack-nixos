# Installing NixOS on Jetson (Orin Nano Super)

## Build the installer ISO (on x86_64)

```shell
nix build github:fr4iser90/nixos-jetson-orin-nano#iso_minimal
sudo dd if=./result/iso/nixos-22.11pre-git-aarch64-linux.iso of=/dev/sdX bs=1M oflag=sync status=progress
```

Replace `/dev/sdX` with your USB device. Boot the Jetson from USB via the UEFI Boot Manager (try another USB port if the stick does not appear).

Generic ARM64 alternative: [NixOS on ARM / UEFI](https://nixos.wiki/wiki/NixOS_on_ARM/UEFI).

## What is on the minimal ISO

JetPack is enabled in the **live** environment. The image also ships:

- **`orin-nano-super-install-all`** — full wizard (optional disk prep → `nixos-generate-config` → `install-orin-nano-super` → `nixos-install`)
- **`prepare-orin-nano-super-disk`**, **`install-orin-nano-super`**
- TTY / login hints and **`/etc/orin-nano-super-template/`** (copy of the flake template)

## Recommended install

**One command:** `sudo orin-nano-super-install-all`

It asks whether to run disk preparation, checks that `/mnt` is mounted, runs `nixos-generate-config`, `install-orin-nano-super` (hostname, user, password, Jetpack flake URL), then asks before `nixos-install`.

When finished: **remove the USB installer** and `sudo reboot`.

### Step by step (same result)

1. `sudo prepare-orin-nano-super-disk` — optional wipe + GPT (EFI + ext4) + mount `/mnt`, or manual instructions if you decline. **`--dry-run`** prints commands only.
2. `sudo nixos-generate-config --root /mnt`
3. `sudo install-orin-nano-super` — see [`templates/orin-nano-super/README.md`](../templates/orin-nano-super/README.md) for **`--dry-run`**, flags, and manual copy.
4. `sudo nixos-install --root /mnt --flake /mnt/etc/nixos#nixos`

## After first boot

The Orin Nano Super template enables Docker and `hardware.nvidia-container-toolkit` so GPU containers work.

It also enables **`jetpack-nixos.examplesHome`**: on first boot, NixOS **copies** the packaged [`examples/`](../examples/) tree into each normal user’s **`$HOME`** (writable copies so you can add `.env` files). Folder names match the install wizard layout (e.g. `Ollama`, `ComfyUI`, `agent-layer`, `lib` for the shared `start-docker-example.sh`). A stamp file `~/.config/jetpack-nixos/examples-copied-v1` prevents overwriting; delete it (and any stack dirs you want refreshed) after a major repo update to re-copy.

Then:

```bash
cd ~/Ollama/docker && ./start.sh
```

See [`examples/README.md`](../examples/README.md). If you disabled `examplesHome` or use a custom config, clone the repo instead and run from `examples/` there.

## Without the ISO helpers (other boards / experts)

The generated flake already uses `jetpack.nixosModules.default`; you do not hand-paste `fetchTarball` imports for the recommended path.

If you skip `install-orin-nano-super`, follow the [NixOS manual (UEFI)](https://nixos.org/manual/nixos/stable/index.html#sec-installation), copy [`templates/orin-nano-super/`](../templates/orin-nano-super/) to `/mnt/etc/nixos`, adjust `flake.nix` / `local.nix` and `hardware.nvidia-jetpack.*` for your SOM, then `nixos-install --flake /mnt/etc/nixos#nixos`. Compare with [`flake.nix` `supportedConfigurations`](../flake.nix) in this repo.

## UEFI firmware before the ISO

Flashing from recovery mode is done on an **x86_64** host (see [README](../README.md) § “Flash UEFI firmware”). That step is separate from the NixOS installer.
