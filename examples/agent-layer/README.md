# Agent layer

OpenAI-kompatible API (FastAPI) vor **Ollama**: führt **Tool Calls** lokal aus (PostgreSQL, Tools), merged Tool-Listen mit Open WebUI, optional **JSON-im-Content-Fallback** für Reasoning-Modelle, und **SSE**, wenn Clients `stream: true` senden.

## Architektur

```text
Open WebUI / curl  →  agent-layer:8080/v1  →  Ollama :11434
                            │
                            ├─ Tools (tools/, optional extra dir)
                            └─ PostgreSQL (Todos, tool_invocations)
```

- **Modellname** kommt pro Request vom Client (`model` im JSON), der Agent reicht ihn an Ollama durch.
- **Websuche** funktioniert auch **ohne API-Key** (ddgs-Metasuche, inoffiziell); Keys für Tavily/Brave sind optional robuster — siehe [TOOLS.md](./TOOLS.md).
- **Secrets:** siehe [`.env`](#konfiguration-env) — nicht ins Git committen.
- **Mehrere Nutzer:** Todos pro WebUI-Account, wenn Open WebUI **`ENABLE_FORWARD_USER_INFO_HEADERS`** sendet (siehe `examples/open-webui/docker/compose.yaml`) und der Agent die Standard-Header-Kette nutzt — Details [TOOLS.md](./TOOLS.md#multi-user-postgres).

## Voraussetzungen

- Docker-Netzwerk `ai-net` (wie bei `examples/ollama/docker`).
- Ollama im gleichen Netz erreichbar (`OLLAMA_BASE_URL`, Standard `http://ollama:11434`).

## Schnellstart

### Ein Skript (Initialisierung)

Voraussetzung: dieselben Ordner wie nach Home-Copy (`~/Ollama`, `~/OpenWebUI`, `~/agent-layer`) **oder** Checkout unter `examples/…`.

`initialize-agent.sh` startet **Ollama**, zieht Modelle aus **`ollama-models.json`** (liegt daneben), startet **Open WebUI** und **`docker/`** (Postgres + API). Optional: **`--skip-pull`** wenn die Modelle schon lokal da sind.

```bash
chmod +x initialize-agent.sh
./initialize-agent.sh
```

Danach **Open WebUI** (`http://127.0.0.1:3000`) ersten Nutzer anlegen, dann **OpenAI API**-URL `http://agent-layer:8080/v1`. Details unten bei „Open WebUI“.

### Manuell (docker compose)

```bash
docker network create ai-net   # falls noch nicht vorhanden

cd examples/ollama/docker && docker compose up -d
# Modell mit Tool-Support: z. B. ollama pull llama3.1

cd ../../agent-layer/docker
cp .env.example .env            # anpassen; siehe unten
docker compose build && docker compose up -d
```

- Health: `curl -s http://127.0.0.1:8088/health`
- Tools: `curl -s http://127.0.0.1:8088/v1/tools | jq .tools` (Chat-`tools[]`-Form wie am HTTP-Endpunkt) und `jq .tools_meta` (Registry-Meta pro Modul)

## Open WebUI

1. **Connections → OpenAI API**: Base URL `http://agent-layer:8080/v1` (Container im Netz `ai-net`) bzw. vom Host `http://<host>:8088/v1`.
2. **Ollama-URL** in der UI ist optional, wenn alle Modelllisten über den Agent laufen (`GET /v1/models` proxy zu Ollama).
4. **Getrennte Todos pro WebUI-Login:** Open-WebUI-Stack mit **`ENABLE_FORWARD_USER_INFO_HEADERS=true`** starten (`examples/open-webui/docker/compose.yaml` ist so gesetzt). Der Agent liest standardmäßig **`X-OpenWebUI-User-Id`** (siehe [TOOLS.md](./TOOLS.md#multi-user-postgres)).

## Konfiguration (.env)

Im Verzeichnis `docker/`:

```bash
cp .env.example .env
```

**PostgreSQL:** Entweder **`DATABASE_URL`** in **`.env`** setzen (siehe `.env.example`) **oder** nur **`POSTGRES_USER`**, **`POSTGRES_PASSWORD`**, **`POSTGRES_DB`** wie beim `postgres`-Service — der Agent baut die URL intern (`PGHOST=postgres` setzt Compose). Passwort mit Sonderzeichen: in `DATABASE_URL` URL-encoden.

Trage **keine Secrets** in `.env.example` ein; nur in **`.env`** (Root-`.gitignore`: `examples/agent-layer/docker/.env`).

Weitere Variablen: siehe `docker/.env.example` (`OLLAMA_BASE_URL`, `AGENT_HTTP_PORT`, `AGENT_*`, künftige Tool-API-Keys).

## Tools

- **Laden:** Die Registry scannt Tool-Wurzeln **rekursiv** nach `*.py`. Im Image sind Module unter **`tools/`** nach Layer gruppiert (`core/`, `knowledge/`, `external/`, `productivity/`, `domains/`). Standard-Wurzel: `tools` im Image, optional `AGENT_TOOLS_EXTRA_DIR`. Mit **`AGENT_TOOL_DIRS`** (Komma-Liste) steuerst du die Wurzeln selbst. `tools_meta` kann pro Modul **`layer`** (aus dem ersten Pfadsegment) und optional **`tags`** (`TOOL_TAGS` im Modul) enthalten — Basis für späteres Filtern bei sehr vielen Tools.
- **Pro Datei:** `TOOLS` + `HANDLERS`, optional `TOOL_ID`, `__version__` — siehe [TOOLS.md](./TOOLS.md).

Details und **Checkliste** der Tools: [TOOLS.md](./TOOLS.md).

## Nützliche Endpoints

| Methode | Pfad | Zweck |
|--------|------|--------|
| GET | `/health` | App + DB |
| GET | `/v1/models` | Proxy zu Ollama |
| POST | `/v1/chat/completions` | Chat + Tool-Loop |
| GET | `/v1/tools` | Schemas + Tool-Meta |
| GET | `/v1/router/categories` | Router-Kategorie-IDs (für Presets / Doku) |
| GET | `/control/` | Mini Tool-Control-UI (siehe Schnellstart) |
| POST | `/v1/admin/reload-tools` | Registry neu laden |
| POST | `/v1/admin/create-tool` | Wie Chat-Tool `create_tool` (JSON-Body) |
| GET/POST/DELETE | `/v1/user/secrets` | Pro-User-Geheimnisse (verschlüsselt), siehe [TOOLS.md](./TOOLS.md#user-secrets) |
| POST | `/v1/user/secrets/register-with-otp` | Secret speichern mit Einmalkennwort aus Tool `register_secrets` (ohne Bearer) |

## Siehe auch

- `docker/compose.yaml` — Postgres, Ports, Kommentare zu Env-Vars.
- `docker/control-panel/` — statische Operator-UI für Tools + Factory.
- `docker/extra_tools/sample_echo.py` — Minimal-Extra-Tool.
