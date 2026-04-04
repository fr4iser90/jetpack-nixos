# NixOS on Jetson Orin Nano (Super)

NixOS module, installer ISO, and JetPack-related packages so you can run **NixOS on NVIDIA Jetson** (kernels, CUDA stack, containers, etc.). This fork is aimed at the **Orin Nano Super Developer Kit**; other boards may work but are not the main story.

**Goal:** flash firmware if needed → boot the USB installer → one guided install → reboot → clone the repo and run **Docker examples** (Ollama, agent-layer, ComfyUI, …) from [`examples/`](./examples/).

---

## What’s in the repo

- UEFI / JetPack flashing scripts, vendor kernel, EDK2/firmware pieces, CUDA / multimedia / graphics / `nvpmodel` / `nvfancontrol` (see flake outputs).
- **Minimal installer ISO** with JetPack in the live system and **`orin-nano-super-install-all`** (wizard) plus smaller helpers.
- **Template:** [`templates/orin-nano-super/`](./templates/orin-nano-super/) (flake + Orin Nano Super `hardware.nvidia-jetpack.*`, Docker + NVIDIA container toolkit).
- **`examples/`** — Compose stacks and `*/docker/start.sh`.

Not supported: Jetson Nano / TX1 / TX2 (dropped upstream in JetPack 5). CUDA on JetPack 7 targets Thor AGX per upstream notes.

---

## Getting started (short path)

### 1. Flash UEFI firmware (often required)

Recovery mode on the Jetson, USB to an **x86_64** machine, then:

```shell
lsusb | grep -i NVIDIA
nix build github:fr4iser90/nixos-jetson-orin-nano#flash-orin-nano-super-devkit
sudo ./result/bin/flash-orin-nano-super-devkit
```

(`nix flake show` lists other flash targets.) Details stay the same as before; expanded install docs: **[docs/install-jetson.md](./docs/install-jetson.md)**.

### 2. Installer ISO → install → reboot

```shell
nix build github:fr4iser90/nixos-jetson-orin-nano#iso_minimal
sudo dd if=./result/iso/nixos-22.11pre-git-aarch64-linux.iso of=/dev/sdX bs=1M oflag=sync status=progress
```

Boot the Jetson from the stick (UEFI Boot Manager). On the live system:

```shell
sudo orin-nano-super-install-all
```

Remove the USB installer when it finishes, then `sudo reboot`.

Step-by-step commands, dry-run, and expert paths: **[docs/install-jetson.md](./docs/install-jetson.md)** and [`templates/orin-nano-super/README.md`](./templates/orin-nano-super/README.md).

### 3. Run examples (agent, ComfyUI, …)

Log in as the user you created during install. The template copies the Docker **examples** into **`$HOME`** on first boot (`~/Ollama`, `~/ComfyUI`, `~/agent-layer`, `~/lib`, … — writable so you can add `.env`). Then:

```shell
cd ~/Ollama/docker && ./start.sh
```

No `git clone` is required for that path. Details: [`docs/install-jetson.md`](./docs/install-jetson.md#after-first-boot) · [`examples/README.md`](./examples/README.md).

---

## Documentation

| | |
|--|--|
| [docs/install-jetson.md](./docs/install-jetson.md) | ISO, wizard, template, without-ISO install |
| [docs/platform-jetson.md](./docs/platform-jetson.md) | JetPack versions, HDMI/console, UEFI capsule firmware |
| [docs/nix-docker-cuda-kernel.md](./docs/nix-docker-cuda-kernel.md) | GPU containers, kernel sets, CUDA / Nixpkgs |
| [docs/README.md](./docs/README.md) | Index |

[ROADMAP.md](./ROADMAP.md) — planned work.

---

## Disclaimer

This project is provided **as is**, without warranty of any kind. You use it **at your own risk**.

That includes (but is not limited to) **firmware flashing**, **disk partitioning / wipe**, **NixOS installation**, **GPU and container workloads**, and anything under [`examples/`](./examples/) (e.g. LLM agents, APIs, credentials, network-facing services). **You** are responsible for backups, updates, isolation, secrets, firewalling, and judging whether a configuration is safe for your environment.

The maintainers aim to improve quality and security over time but **do not accept liability** for crashes, data loss, hardware issues, or security incidents arising from use of this software. If you need legally binding terms, consult a professional; the project’s **license** (see the repository’s `LICENSE` if present) governs redistribution and warranty disclaimers where applicable.

---

## Additional links

Inspired by [OpenEmbedded for Tegra](https://github.com/OE4T); vendor kernel work traces back to OE4T.
