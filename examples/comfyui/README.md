# ComfyUI example

Two ways to run:

| Mode | When to use |
|------|----------------|
| **Docker** (`docker/`) | Reproducible image; on small Jetson boards you may hit RAM limits (pinned memory, cgroup). |
| **Native shell** (`nix/`, `shell/`) | Same CUDA/JetPack setup as the repo’s `shell.nix`; often **more headroom** than Docker because nothing is double-accounted in the container. |

## Docker

```bash
cd docker && ./start.sh
```

Create `models/`, `input/`, `output/` next to `compose.yaml` if missing. See `docker/compose.yaml` for Jetson flags (`--novram`, `--disable-pinned-memory`).

## Native (nix-shell)

1. Clone ComfyUI (once), e.g. `git clone https://github.com/comfyanonymous/ComfyUI.git ~/ComfyUI-app`
2. `cd ~/ComfyUI-app`
3. `nix-shell /path/to/examples/comfyui/nix/shell.nix`
4. Run **`cinstall`** once, then **`crun`** (or pass extra args: `crun --help`).

From a copy under `$HOME/ComfyUI` (examples home layout), the nix file is `~/ComfyUI/nix/shell.nix`.

### Foreground helper

```bash
export COMFYUI_ROOT="$HOME/ComfyUI-app"   # your clone with main.py
~/ComfyUI/shell/run.sh                     # path after home copy; or repo examples/comfyui/shell/run.sh
```

### Stay up after logout (systemd user unit)

```bash
./shell/install-systemd-user.sh "$HOME/ComfyUI-app"
systemctl --user enable --now comfyui-native.service
```

For **boot without logging in**: `sudo loginctl enable-linger "$USER"`.
