#!/usr/bin/env bash
# Initialize stack: Ollama (Docker), model pulls, Open WebUI, agent-layer (Postgres + API).
# Intended layout: ~/Ollama, ~/OpenWebUI, ~/agent-layer (examples home copy) or repo examples/*.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DOCKER="$(cd "$SCRIPT_DIR/../lib" && pwd)/start-docker-example.sh"

usage() {
  echo "usage: $0 [--skip-pull]" >&2
  echo "  Starts Ollama, pulls models (ollama-models.json next to this script), Open WebUI, and agent-layer/docker." >&2
  echo "  --skip-pull  skip ollama pull; everything else still starts." >&2
  exit 2
}

SKIP_PULL=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-pull) SKIP_PULL=1 ;;
    -h | --help) usage ;;
    *) usage ;;
  esac
  shift
done

if [[ -d "$SCRIPT_DIR/../ollama/docker" || -d "$SCRIPT_DIR/../Ollama/docker" ]]; then
  STACK_ROOT="${STACK_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
else
  STACK_ROOT="${STACK_ROOT:-$HOME}"
fi

OLLAMA_DOCKER=""
for d in "$STACK_ROOT/Ollama/docker" "$STACK_ROOT/ollama/docker"; do
  if [[ -d "$d" ]]; then OLLAMA_DOCKER="$d"; break; fi
done
WEBUI_DOCKER=""
for d in "$STACK_ROOT/OpenWebUI/docker" "$STACK_ROOT/open-webui/docker"; do
  if [[ -d "$d" ]]; then WEBUI_DOCKER="$d"; break; fi
done
AGENT_DOCKER=""
if [[ -d "$STACK_ROOT/agent-layer/docker" ]]; then
  AGENT_DOCKER="$STACK_ROOT/agent-layer/docker"
elif [[ -d "$SCRIPT_DIR/docker" ]]; then
  AGENT_DOCKER="$SCRIPT_DIR/docker"
fi

if [[ -z "$OLLAMA_DOCKER" || -z "$WEBUI_DOCKER" || -z "$AGENT_DOCKER" ]]; then
  echo "error: need Ollama, Open WebUI, and agent-layer docker dirs under STACK_ROOT=$STACK_ROOT" >&2
  echo "  (Ollama/docker, OpenWebUI/docker, agent-layer/docker — or this repo’s agent-layer/docker)" >&2
  exit 1
fi

MODELS_FILE="${OLLAMA_MODELS_FILE:-}"
if [[ -z "$MODELS_FILE" ]]; then
  if [[ -f "$SCRIPT_DIR/ollama-models.json" ]]; then
    MODELS_FILE="$SCRIPT_DIR/ollama-models.json"
  elif [[ -f "$SCRIPT_DIR/ollama-models.txt" ]]; then
    MODELS_FILE="$SCRIPT_DIR/ollama-models.txt"
  fi
fi

echo "Using STACK_ROOT=$STACK_ROOT"

docker network create ai-net 2>/dev/null || true

echo "==> Ollama (docker compose up -d)"
"$LIB_DOCKER" "$OLLAMA_DOCKER"

echo "==> Waiting for Ollama API on http://127.0.0.1:11434 …"
ok=0
for _ in $(seq 1 90); do
  if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 1
done
if [[ "$ok" -ne 1 ]]; then
  echo "error: Ollama did not become ready in time." >&2
  exit 1
fi

AGENT_LAYER_MODEL=""
pulls=()
JSON_TMP_DIR=""

if [[ "$SKIP_PULL" -eq 0 ]]; then
  if [[ -n "$MODELS_FILE" && -f "$MODELS_FILE" ]]; then
    case "$MODELS_FILE" in
      *.json)
        if ! command -v python3 >/dev/null 2>&1; then
          echo "error: python3 is required to read $MODELS_FILE" >&2
          exit 1
        fi
        JSON_TMP_DIR="$(mktemp -d)"
        python3 - "$MODELS_FILE" "$JSON_TMP_DIR" <<'PY'
import json
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])
d = json.loads(path.read_text(encoding="utf-8"))
agent = (d.get("agent_layer_model") or "").strip()
extra = [str(x).strip() for x in (d.get("models") or []) if str(x).strip()]
pulls = []
if agent:
    pulls.append(agent)
for m in extra:
    if m not in pulls:
        pulls.append(m)
(out / "agent").write_text(agent, encoding="utf-8")
(out / "pulls").write_text("\n".join(pulls) + ("\n" if pulls else ""), encoding="utf-8")


def sanitize_key(k: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z_]+", "_", str(k)).strip("_")
    return (s[:120] or "category")


opt_dir = out / "optional_parts"
raw_opt = d.get("optional")
if isinstance(raw_opt, dict):
    for key, val in raw_opt.items():
        if not isinstance(val, list):
            continue
        lines = [str(x).strip() for x in val if str(x).strip()]
        if not lines:
            continue
        opt_dir.mkdir(parents=True, exist_ok=True)
        fname = sanitize_key(key)
        (opt_dir / fname).write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
        AGENT_LAYER_MODEL="$(cat "$JSON_TMP_DIR/agent")"
        while IFS= read -r line || [[ -n "$line" ]]; do
          line="$(echo "$line" | tr -d '\r' | xargs)"
          [[ -z "$line" ]] && continue
          pulls+=("$line")
        done < "$JSON_TMP_DIR/pulls"
        ;;
      *)
        while IFS= read -r line || [[ -n "$line" ]]; do
          line="${line%%#*}"
          line="$(echo "$line" | tr -d '\r' | xargs)"
          [[ -z "$line" ]] && continue
          pulls+=("$line")
        done < "$MODELS_FILE"
        ;;
    esac

    if [[ ${#pulls[@]} -eq 0 ]]; then
      echo "No models to pull: $MODELS_FILE — for JSON set agent_layer_model and/or models[]; for .txt add non-comment lines."
    else
      echo "==> Ollama: pulling ${#pulls[@]} model(s) from $MODELS_FILE"
      if [[ "$MODELS_FILE" == *.json ]]; then
        echo "    agent_layer_model (wird immer gezogen wenn gesetzt): ${AGENT_LAYER_MODEL:-<not set>}"
        echo "    models[] = zusätzliche Pulls (ohne agent erneut einzutragen)"
        echo "    optional.* = nur Referenz — zum Ziehen Einträge nach models[] verschieben"
      else
        echo "    (.txt: kein agent_layer_model — für TOOL_LABELs ollama-models.json nutzen)"
      fi
      for m in "${pulls[@]}"; do
        if [[ -n "$AGENT_LAYER_MODEL" && "$m" == "$AGENT_LAYER_MODEL" ]]; then
          echo "    ollama pull $m  ← für den agent-layer: Ollama tool_calls (agent_layer_model)"
        else
          echo "    ollama pull $m"
        fi
        docker exec ollama ollama pull "$m"
      done
      if [[ "$MODELS_FILE" == *.json && -n "$JSON_TMP_DIR" && -d "$JSON_TMP_DIR/optional_parts" ]]; then
        shopt -s nullglob
        for _optf in "$JSON_TMP_DIR/optional_parts"/*; do
          [[ -s "$_optf" ]] || continue
          _sec="$(basename "$_optf")"
          echo "    optional [${_sec}] (nicht gezogen — bei Bedarf nach models[]):"
          while IFS= read -r oline || [[ -n "$oline" ]]; do
            [[ -z "${oline//[$' \t\r\n']/}" ]] && continue
            echo "      - $oline"
          done < "$_optf"
        done
        shopt -u nullglob
      fi
    fi
    [[ -n "$JSON_TMP_DIR" && -d "$JSON_TMP_DIR" ]] && rm -rf "$JSON_TMP_DIR"
  else
    echo "No pulls: neither $SCRIPT_DIR/ollama-models.json nor ollama-models.txt found — set OLLAMA_MODELS_FILE."
  fi
else
  echo "Skipping model pulls (--skip-pull)."
fi

echo "==> Open WebUI (docker compose up -d)"
"$LIB_DOCKER" "$WEBUI_DOCKER"

echo ""
echo "==> agent-layer (docker compose build && up -d)"
if [[ ! -f "$AGENT_DOCKER/.env" ]]; then
  cp "$AGENT_DOCKER/.env.example" "$AGENT_DOCKER/.env"
  echo "Created $AGENT_DOCKER/.env from .env.example — review before production."
fi
(cd "$AGENT_DOCKER" && docker compose build && docker compose up -d)
echo "Health: curl -s http://127.0.0.1:8088/health"

cat <<EOF

==> Next steps

1. Open WebUI: http://127.0.0.1:3000 — create the first admin user (sign up).

2. Open WebUI → OpenAI-compatible API: Base URL http://agent-layer:8080/v1

3. Health: curl -s http://127.0.0.1:8088/health
EOF
