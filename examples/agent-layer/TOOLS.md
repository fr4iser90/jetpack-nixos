# Agent layer — Tools

Übersicht über **eingebaute** und **geplante** Tools, dazu Ideen für Erweiterungen.  
Implementierung: jeweils Plugin-Modul mit `TOOLS` (OpenAI-Schema) + `HANDLERS` (Python). Secrets über **Umgebungsvariablen** / **`.env`** (siehe `docker/.env.example`), nicht hardcoden.

---

## Checkliste (built-in)

| Status | Tool | Plugin | Kurzbeschreibung |
|--------|------|--------|------------------|
| [x] | `get_current_time` | `clock` | IANA-Zeitzone, ISO-Zeit (ohne DB). |
| [x] | `create_todo` | `todos` | Todo anlegen (**pro** `X-Agent-User-Sub` + Tenant). |
| [x] | `list_todos` | `todos` | Eigene Todos (max. 100). |
| [x] | `set_todo_status` | `todos` | Status nur für eigene Zeilen. |
| [x] | `search_web` | `web_search` | Tavily → Brave → **ddgs**-Metasuche ohne API-Key (inoffiziell). |
| [x] | `deep_search` | `web_search` | Tavily: `raw_content`. Ohne: Snippets + **Seitenabruf** wenn `robots.txt` den UA erlaubt (`fetch_status`, `raw_content`). Abschalten: `AGENT_DISABLE_FETCH_DEEP=true`. |
| [x] | `list_available_tools` | `meta` | Alle Tools mit Beschreibung + JSON-Schema (Parameter). |
| [x] | `get_tool_help` | `meta` | Hilfe zu einem Tool nach Namen (`tool_name`). |
| [x] | `register_secrets` | `meta` | Secret registrieren: Einmalcode + fertiger `curl` (OTP-Flow); z. B. `service_key_example: gmail`. |
| [x] | `secrets_help` | `meta` | Hilfe: Überblick + Legacy-`curl` für Liste/Löschen / Header-POST (kein OTP). |
| [x] | `gmail_search` | `gmail` | Gmail-Suche (IMAP `X-GM-RAW`, z. B. `newer_than:7d is:unread`). |
| [x] | `gmail_read` | `gmail` | Eine Mail per IMAP-UID lesen (Plain-Text-Body, gekürzt). |
| [x] | `gmail_collect_for_summary` | `gmail` | Mehrere Mails laden → `combined_excerpt`; Modell fasst für den Nutzer zusammen. |

*(Frühere Tool-Namen `issue_secret_registration_otp` / `secret_storage_help` — durch Umbenennung ersetzt.)*

**Hilfe / „Welche Tools gibt es?“**

- Pro Tool: **`description`** + **`parameters`** im OpenAI-Schema (sieht das Modell in jedem Request).
- Explizit abfragbar: **`list_available_tools`** (Übersicht), **`get_tool_help`** mit `tool_name` (ein Tool ausführlich + kurzer `how_to_use`-Hinweis).

**Validiert (manuell / Stack):** Tool-Loop über Agent → Ollama, Einträge in `todos` + `tool_invocations`; Open WebUI mit OpenAI-Base-URL auf den Agent; `stream: true` über SSE-Shim; Tool-Merge mit WebUI-`tools`; Content-JSON-Fallback für Modelle mit `reasoning`-Feld.

### Multi-User (Postgres)

- Tabellen: **`tenants`**, **`users`** (`external_sub` pro Login, eindeutig je `tenant_id`); **`todos`** und **`tool_invocations`** haben **`tenant_id`** + **`user_id`**.
- Pro Chat-Request setzt der Agent die Identität aus HTTP-Headern (dann `contextvars` für alle Tool-Handler):
  - **User-Kennung** — Standard: zuerst **`X-OpenWebUI-User-Id`** (Open WebUI mit `ENABLE_FORWARD_USER_INFO_HEADERS`), sonst **`X-Agent-User-Sub`**. Reihenfolge/Namen: `AGENT_USER_SUB_HEADER` (kommagetrennt).
  - **`X-Agent-Tenant-Id`** — numerische Tenant-ID (Default `1` = `default`-Tenant). Optional: `AGENT_TENANT_ID_HEADER`.
  - Ohne Sub: `AGENT_DEFAULT_EXTERNAL_SUB` (Default `default`) → gemeinsamer DB-User wie früher.
- **Open WebUI:** In den Connection-**Headers** (Admin) sind Werte meist **statisch** — ungeeignet für Trennung pro Account. **OAuth** = Login zur WebUI, nicht automatisch User-ID am Agent.
- **Ohne Proxy:** Im Repo ist **`examples/open-webui/docker/compose.yaml`** mit **`ENABLE_FORWARD_USER_INFO_HEADERS=true`** vorkonfiguriert; der **agent-layer** nutzt standardmäßig **`X-OpenWebUI-User-Id`** (dann **`X-Agent-User-Sub`** als Fallback). `external_sub` = WebUI-User-ID (Header-Namen bei WebUI per `FORWARD_USER_INFO_HEADER_USER_ID` änderbar).
- Alternativ: **Reverse-Proxy** setzt `X-Agent-User-Sub`, oder `AGENT_USER_SUB_HEADER` anpassen.
- **Sicherheit:** Ohne `AGENT_API_KEY` kann jeder Client beliebige Subs vorgeben. Für geteilten Zugriff: API-Key + vertrauenswürdiger Proxy, der `X-Agent-User-Sub` setzt und von außen nicht überschreibbar macht.

### User secrets

- **Nicht** das Klartext-Secret in den Chat schreiben — Registrierung per **`curl`** im eigenen Terminal (oder später UI).
- Tabelle **`user_secrets`**: pro `users.id` und **`service_key`** (kleinbuchstaben `[a-z0-9._-]`, max. 63 Zeichen) ein **Fernet**-verschlüsselter Blob.
- **`AGENT_SECRETS_MASTER_KEY`** (nur **Betreiber**, nie Endnutzer): Fernet-Key erzeugen mit  
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`  
  — in **`docker/.env`**, nicht committen. Verschlüsselt nur die Datenbank-Inhalte; Nutzer sehen oder tippen das **nicht**. Bei Key-Verlust sind gespeicherte Secrets **nicht** wiederherstellbar.
- **Registrieren (empfohlen):** Tool **`register_secrets`** — legt ein **Einmalkennwort** für den **aktuellen Chat-User** an und liefert **`curl_bash`**: darin ist das OTP schon im JSON; der Nutzer ersetzt nur den Platzhalter **`DEIN_GMAIL_APP_PASSWORT`** lokal und führt den Befehl aus. Endpoint: **`POST /v1/user/secrets/register-with-otp`** (ohne Bearer — wenn `AGENT_API_KEY` gesetzt ist, ist dieser Pfad davon ausgenommen).
- **OTP-Sicherheit:** Wer den Chat mitlesen kann, könnte das OTP nutzen — kurz gültig (Standard 10 min), **einmalig**; Befehl zeitnah ausführen.
- **Legacy** (Header + optional Bearer): `POST /v1/user/secrets` mit denselben User-Headern wie beim Chat; wenn **`AGENT_API_KEY`** gesetzt ist, **`Authorization: Bearer …`** = **nur** dieser Agent-Key (Open-WebUI-Connection), **niemals** die WebUI-User-ID. **`GET`** / **`DELETE`** für Auflisten bzw. Entfernen von `service_key`s ebenfalls mit diesen Headern (und Bearer falls konfiguriert).
- **Plugins** (z. B. E-Mail): serverseitig nur `db.user_secret_get_plaintext(user_id, "…")`; **nie** Klartext in Tool-Antworten an das Modell.
- **Chat-Hilfe:** **`register_secrets`** zum Speichern; **`secrets_help`** für Überblick und Legacy-`curl`. Optional **`AGENT_PUBLIC_URL`** für die Basis-URL in den Vorlagen.

### Gmail (`plugin gmail`)

- **Pro User** ein Secret mit **`service_key`** = **`gmail`**, Wert = **JSON** (ein String, den das Plugin parst):
  ```json
  {"email":"du@gmail.com","app_password":"xxxxxxxxxxxxxxxx"}
  ```
  Leerzeichen im App-Passwort sind erlaubt (werden beim Einlesen entfernt). Google: **2-Faktor** + **App-Passwort**; normales Login-Passwort funktioniert am IMAP-Endpoint nicht.
- **Registrieren:** `register_secrets` mit `service_key_example: "gmail"` — im `curl` steht im Feld `secret` bereits ein JSON-Platzhalter; **E-Mail und App-Passwort lokal eintragen**, Befehl im Terminal ausführen.
- **Zugriff:** IMAP **`imap.gmail.com:993`**, Standard-Mailbox **`INBOX`** (Parameter `mailbox` bei Bedarf).
- **Tools:** **`gmail_search`** (Gmail-Suchsyntax wie in der Web-UI), **`gmail_read`** (`uid` aus der Suche), **`gmail_collect_for_summary`** (mehrere Mails → Auszüge; das **Modell** soll daraus eine Zusammenfassung formulieren). **Keine** Mail-Inhalte absichtlich vollständig spammen: `limit` / `max_body_chars` / `max_messages` beachten.

---

## Checkliste (geplant / optional)

| Status | Tool / Paket | Hinweis |
|--------|----------------|---------|
| [ ] | GitHub Search / Repo-Read | Fine-grained PAT, nur nötige Scopes. |
| [x] | HTTP-Fetch + robots.txt + noindex | `deep_search` ohne Tavily; optionale Allowlist via Env. |
| [ ] | Weitere Search-Provider (SerpAPI, …) | Optional ergänzen. |
| [ ] | Lokale Dateien (read-only Mount) | Nur definierte Pfade. |
| [ ] | Home Assistant / MQTT | Topic-Whitelist. |
| [ ] | RAG / `search_kb` | pgvector, Chroma, … |

*(Status hier anpassen, sobald ein Plugin gemerged und einmal gegen euren Stack getestet ist.)*

---

## API-Keys & `.env`

Empfehlung: **eine** `docker/.env` (von `.env.example` kopieren), **nicht** committen.

- **Heute:** meist nur Postgres/Ollama/Agent-Settings (`DATABASE_URL`, `OLLAMA_BASE_URL`, `AGENT_API_KEY`, …).
- **Web-Suche:** optional `TAVILY_API_KEY` / `BRAVE_SEARCH_API_KEY`; ohne Keys nutzt das Plugin **[ddgs](https://pypi.org/project/ddgs/)** (Metasuche, u. a. Bing/DuckDuckGo-Backends; ohne Vertrag, Rate-Limits möglich). Abschalten: `AGENT_DISABLE_DDG_SEARCH=true`. Zusätzlich `AGENT_SEARCH_TIMEOUT`, `AGENT_SEARCH_MAX_RAW_CHARS`.
- **deep_search ohne Tavily:** pro Treffer optional **HTTP-GET** der URL, nur wenn `robots.txt` für `AGENT_FETCH_USER_AGENT` (Default: `JetpackAgentLayer/…`) **kein** `Disallow` setzt; sonst `fetch_status=robots_disallowed`, kein Abruf. **`AGENT_ROBOTS_STRICT=true`:** wenn `robots.txt` nicht lesbar ist, wird **nicht** gefetcht (Default: in dem Fall wie „keine Regeln“ behandelt). **`AGENT_DISABLE_FETCH_DEEP=true`:** nur Snippets. **`AGENT_FETCH_MAX_BYTES`:** max. Antwortgröße (Default 2 MB). **`AGENT_ROBOTS_CACHE_TTL`:** Cache für `robots.txt` pro Origin (Sekunden). Loopback/Link-Local/Metadata-Hosts werden nicht abgerufen (Basis-SSRF-Schutz). **`AGENT_RESPECT_META_ROBOTS`** (Default `true`): bei **`X-Robots-Tag`** oder **`<meta name="robots" content="…">`** mit **`noindex`** oder **`none`** wird **kein** `raw_content` geliefert (`fetch_status` z. B. `x_robots_noindex` / `meta_robots_noindex`). **`AGENT_FETCH_DOMAIN_ALLOWLIST`:** wenn gesetzt (kommagetrennte Hostnamen), nur noch diese Hosts und ihre Subdomains — alles andere `blocked_allowlist` (reduziert SSRF + Scope).
- **Später (Beispiele):** `GITHUB_TOKEN=…`, `SERPAPI_API_KEY=…` — im jeweiligen Plugin aus `os.environ` lesen.

Für Produktion alternativ **NixOS sops-nix** / Secrets-Store statt flacher `.env`.

---

## Kategorien (Ideenkatalog)

### Web / Research

| Ansatz | Bemerkung |
|--------|-----------|
| Search-API (Brave, Tavily, SerpAPI, Google CSE) | Stabil, ToS/Quota beachten. |
| URL-Fetch | Nur mit **Allowlist**; sonst SSRF. |
| Reader-APIs (Firecrawl, Jina, …) | Oft kostenpflichtig; Inhalte gekürzt liefern. |

### GitHub

- `search/code`, `search/repositories`, `search/issues` über REST API.  
- PAT minimal halten (read-only wo möglich).

### System / Homelab

- **Shell:** nur Allowlist einzelner Befehle oder RPC auf Host.  
- **Monitoring:** Prometheus-Query, interne Health-URLs.  
- **Container:** nur mit klar eingeschränkter API — nie blind Socket mounten.

### Bereits woanders im Repo

- Whisper / faster-whisper / ComfyUI als **eigene** Services; der Agent kann sie per HTTP-Tool ansprechen, falls du ein Plugin dafür schreibst.

---

## Plugin-Vertrag (Kurz)

```text
TOOLS: list[dict]          # OpenAI function specs
HANDLERS: dict[str, callable]  # name -> fn(args: dict) -> str (JSON-String)
PLUGIN_ID: str             # optional
__version__: str           # optional
```

Reload Built-in + Extra: `POST /v1/admin/reload-plugins?scope=all|extra`.

---

## Sicherheit (Merksatz)

Jedes Tool ist **ausführbarer Code** mit den Rechten des Agent-Containers. Lieber zu wenige, gut begrenzte Tools als ein generisches „run_shell“.
