# Agent layer

OpenAI-kompatible API (FastAPI) vor **Ollama**: führt **Tool Calls** lokal aus (PostgreSQL, Plugins), merged Tool-Listen mit Open WebUI, optional **JSON-im-Content-Fallback** für Reasoning-Modelle, und **SSE**, wenn Clients `stream: true` senden.

## Architektur

```text
Open WebUI / curl  →  agent-layer:8080/v1  →  Ollama :11434
                            │
                            ├─ Plugins (app/plugins/, optional extra dir)
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

```bash
docker network create ai-net   # falls noch nicht vorhanden

cd examples/ollama/docker && docker compose up -d
# Modell mit Tool-Support: z. B. ollama pull llama3.1

cd ../../agent-layer/docker
cp .env.example .env            # anpassen; siehe unten
docker compose build && docker compose up -d
```

- Health: `curl -s http://127.0.0.1:8088/health`
- Tools: `curl -s http://127.0.0.1:8088/v1/tools | jq .plugins`

## Open WebUI

1. **Connections → OpenAI API**: Base URL `http://agent-layer:8080/v1` (Container im Netz `ai-net`) bzw. vom Host `http://<host>:8088/v1`.
2. **Ollama-URL** in der UI ist optional, wenn alle Modelllisten über den Agent laufen (`GET /v1/models` proxy zu Ollama).
3. API-Key nur setzen, wenn du `AGENT_API_KEY` im Agent gesetzt hast — dann gleicher Wert als Bearer-Token.
4. **Getrennte Todos pro WebUI-Login:** Open-WebUI-Stack mit **`ENABLE_FORWARD_USER_INFO_HEADERS=true`** starten (`examples/open-webui/docker/compose.yaml` ist so gesetzt). Der Agent liest standardmäßig **`X-OpenWebUI-User-Id`** (siehe [TOOLS.md](./TOOLS.md#multi-user-postgres)).

## Konfiguration (.env)

Im Verzeichnis `docker/`:

```bash
cp .env.example .env
```

**PostgreSQL** (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`) und der Agent lesen die Werte aus **dieser** `.env` (Compose-Interpolation).  
`DATABASE_URL` für den Agent wird **automatisch** aus denselben drei Variablen gebaut, sofern du `DATABASE_URL` nicht explizit setzt (bei Sonderzeichen im Passwort: `DATABASE_URL` manuell setzen und Passwort URL-encoden).

Trage **keine Secrets** in `.env.example` ein; nur in **`.env`** (Root-`.gitignore`: `examples/agent-layer/docker/.env`).

Weitere Variablen: siehe `docker/.env.example` (`OLLAMA_BASE_URL`, `AGENT_HTTP_PORT`, `AGENT_*`, künftige Tool-API-Keys).

## Plugins

- **Built-in:** `docker/app/plugins/*.py` — pro Datei `TOOLS` + `HANDLERS`, optional `PLUGIN_ID`, `__version__` (u. a. `gmail.py` für IMAP/Gmail, siehe [TOOLS.md](./TOOLS.md#gmail-plugin-gmail)).
- **Extra:** `AGENT_PLUGINS_EXTRA_DIR` + `*.py`, Reload: `POST /v1/admin/reload-plugins?scope=extra` (mit `AGENT_API_KEY`, falls gesetzt).

Details und **Checkliste** der Tools: [TOOLS.md](./TOOLS.md).

## Nützliche Endpoints

| Methode | Pfad | Zweck |
|--------|------|--------|
| GET | `/health` | App + DB |
| GET | `/v1/models` | Proxy zu Ollama |
| POST | `/v1/chat/completions` | Chat + Tool-Loop |
| GET | `/v1/tools` | Schemas + Plugin-Meta |
| POST | `/v1/admin/reload-plugins` | Registry neu laden |
| GET/POST/DELETE | `/v1/user/secrets` | Pro-User-Geheimnisse (verschlüsselt), siehe [TOOLS.md](./TOOLS.md#user-secrets) |
| POST | `/v1/user/secrets/register-with-otp` | Secret speichern mit Einmalkennwort aus Tool `register_secrets` (ohne Bearer) |

## Siehe auch

- `docker/compose.yaml` — Postgres, Ports, Kommentare zu Env-Vars.
- `docker/extra_plugins/sample_echo.py` — Minimal-Extra-Plugin.
