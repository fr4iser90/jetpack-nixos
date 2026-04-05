# LoRA trainer (example)

Training lives **outside** the agent-layer: you produce adapters or exported weights, then load them in Ollama (or another runtime) and point the chat UI at the **model name**.

## Docker first, or Nix?

| Approach | When it helps |
|----------|----------------|
| **Docker** (`docker/`) | Same layout on most Linux boxes; easy GPU passthrough on x86_64 + NVIDIA (see profile `gpu`). Good default to **build first**. |
| **Native / `shell.nix`** | NixOS or `nix develop`: tight coupling with jetpack-nixos, Jetson/L4T-style stacks, no container overhead. Add under `nix/` when you want reproducible **host** envs (optional second step). |

You do **not** need both at once. Start with Docker; add Nix if your workflow is already Nix-first.

### Optional: Nix shell (no container)

```bash
nix-shell examples/lora-trainer/nix/shell.nix
```

This only pulls **Python + git**; wire in `torch` / CUDA via your usual jetpack-nixos or nixpkgs overlays.

## Docker quick start

```bash
cd examples/lora-trainer/docker
mkdir -p ../data ../outputs
./start.sh          # from docker/: uses ../../lib/start-docker-example.sh
# or: docker compose up -d --build
```

CPU default service: **`lora-trainer`**. Optional GPU stack (x86_64 NVIDIA):

```bash
docker compose --profile gpu up -d --build
```

Then e.g.:

```bash
docker exec -it lora-trainer python /work/scripts/train_example.py
```

Replace `scripts/train_example.py` with your real PEFT/Unsloth/Axolotl entrypoint.

## Layout

- `data/` — training data (mounted read-only at `/data` in the container).
- `outputs/` — checkpoints and logs (mounted at `/outputs`; gitignored).
- `docker/` — `Dockerfile`, optional `Dockerfile.gpu`, `compose.yaml`, `requirements.txt`.

## LoRA on a topic (e.g. Angeln / fishing)

LoRA does **not** use hand-tuned “topic weights”. Training minimizes loss on **your examples**, so the model’s predictions shift toward the **style, vocabulary, and answers** you show (here: fishing / *Angeln*, gear, waters, regulations in your wording).

1. **Collect data** — Many short **instruction → answer** or **chat** turns work better than a few long blobs. Aim for **hundreds to thousands** of solid rows if you want a clear domain bias; dozens only nudge slightly.
2. **Format** — Use whatever your trainer expects (often **ShareGPT-style** `messages` JSONL). See `data/examples/fishing_de_chat.jsonl` for a minimal German fishing-themed pattern you can copy and scale.
3. **Base model** — Pick the **same architecture** you will run in inference (e.g. a Nemotron / Llama-class checkpoint on Hugging Face that matches your Ollama/GGUF pipeline). Mismatched tokenizer/arch breaks training or merge.
4. **Train** — Run your script (TRL `SFTTrainer` + PEFT, Axolotl, Unsloth, NVIDIA NeMo cookbooks, …) inside the **gpu** container or on the host, reading from `/data`, writing adapters to `/outputs`.
5. **Deploy** — Merge adapter → export (e.g. GGUF) → **Ollama `Modelfile`** / NIM / vLLM; then select that **model name** in the chat UI. Agent-layer stays unchanged.

**Regulatory / safety:** If you train on fishing law or catch limits, keep sources accurate; the model will **imitate** the training text, not look up live rules.

## Agent layer

After training, packaging for inference (e.g. GGUF + Ollama) is **not** automated here. The agent-layer keeps using `OLLAMA_BASE_URL` and the model name you choose in the client.
