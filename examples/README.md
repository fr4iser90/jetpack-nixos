# Examples (Docker stacks)

## Where the files live

- **Orin Nano Super template install** (`jetpack-nixos.examplesHome.enable = true`): the same trees are **copied into your home directory** on first boot (e.g. `~/Ollama`, `~/agent-layer`, `~/lib`, …) so you do not need `git clone` for Compose. See [`docs/install-jetson.md`](../docs/install-jetson.md#after-first-boot).
- **Otherwise:** clone this repository (e.g. `~/jetpack-nixos`) and use paths under `examples/` as below.

## Prerequisites

- Docker enabled on NixOS (`virtualisation.docker.enable = true`; your user should be in the `docker` group, or use `sudo`).
- For GPU in containers: `hardware.nvidia-container-toolkit.enable = true` (see the Orin Nano Super template under `templates/orin-nano-super/`).

## Start a stack

Each stack has a `docker/` directory.

**From a git checkout (repo root):**

```bash
chmod +x examples/ollama/docker/start.sh   # once, if your checkout has no exec bit
./examples/ollama/docker/start.sh
```

**From home copies after install:**

```bash
chmod +x ~/Ollama/docker/start.sh   # once if needed
cd ~/Ollama/docker && ./start.sh
```

The shared helper `examples/lib/start-docker-example.sh` picks `compose.yaml` or `compose.yml`, creates the external `ai-net` network when the compose file references it, then runs `docker compose up -d`.

Read each example’s own `README.md` for `.env` files and ports.

## Shell (non-Docker)

Some stacks have **native** launchers (often better RAM behaviour on Jetson than Docker):

| Path | Purpose |
|------|---------|
| [`comfyui/shell/run.sh`](./comfyui/shell/run.sh) | Run ComfyUI via `comfyui/nix/shell.nix` (set `COMFYUI_ROOT` to your ComfyUI git clone). |
| [`comfyui/shell/install-systemd-user.sh`](./comfyui/shell/install-systemd-user.sh) | Install a **user** systemd unit so ComfyUI stays up (`loginctl enable-linger` for boot without login). |
| [`agent-layer/initialize-agent.sh`](./agent-layer/initialize-agent.sh) | **Ollama** + model pulls ([`ollama-models.json`](./agent-layer/ollama-models.json)) + **Open WebUI** + **agent-layer** Compose; **`--skip-pull`** optional. |

Model config: [`agent-layer/ollama-models.json`](./agent-layer/ollama-models.json) — **`agent_layer_model`** is pulled automatically when set (agent / tool_calls label); **`models[]`** lists *additional* pulls only (no duplicate of the agent tag); **`optional`** is an object of named lists (e.g. `coding_llm`, `text_image_vlm`) shown by the script but not pulled until you copy tags into `models[]`. **`ollama-models.txt`** works via `OLLAMA_MODELS_FILE` (no JSON labels).

## Layout

| Directory | Role |
|-----------|------|
| `lib/start-docker-example.sh` | Shared Docker launcher |
| `*/docker/start.sh` | Thin wrapper for that example |
| `comfyui/nix/shell.nix` | Nix shell for native ComfyUI on Jetson |
| `comfyui/shell/*.sh` | Native ComfyUI run + systemd installer |
| `agent-layer/ollama-models.json` | `agent_layer_model` + extra `models[]` + categorized `optional` for `initialize-agent.sh` |
| `agent-layer/initialize-agent.sh` | Ollama → pulls → Open WebUI → agent-layer Compose |
