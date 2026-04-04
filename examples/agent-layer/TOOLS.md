# Agent layer — Tools

Übersicht über **eingebaute** und **geplante** Tools, dazu Ideen für Erweiterungen.  
Implementierung: `*.py`-Module mit `TOOLS` + `HANDLERS` unter **konfigurierten Tool-Wurzeln** (`AGENT_TOOL_DIRS` oder Standard: `agent_tools` im Image + optional `AGENT_TOOLS_EXTRA_DIR`). Die Registry scannt **rekursiv** (Domänen-Unterordner wie `github/`, `secrets/`, `calendar/`). Kein Tool ist im HTTP-Core eingetragen. Secrets nur über **`.env`** / Env, siehe `docker/.env.example`.

**Begriffe:** Nur die **HTTP-API** des Agent-Layers ist **OpenAI-kompatibel** (Clients wie Open WebUI). Eure **Tools** sind registrierte Python-Module; die Einträge in `tools[]` nutzen dasselbe **JSON-Layout** wie Chat Completions (`type` / `function` / …), sind aber **eure** Tools — keine „OpenAI-Tools“.

**Stufenweise Erkundung (Pflichtmodell):** In `tools[]` an Ollama sind **alle** Tools immer nur **Katalog** (Name, Kurzbeschreibung, minimale `parameters`). **Kein** Domänen-Tool erhält sein volles JSON-Schema in `tools[]`. **(1) Kategorien:** **`list_tool_categories`** → je Kategorie **id**, **Label**, **Kurzbeschreibung**, Tool-Anzahl. **(2) Tools pro Kategorie:** **`list_tools_in_category(category)`** → Namen + Kurzbeschreibungen in dieser Kategorie. **(3) Volles Spektrum nur nach Auswahl:** **`get_tool_help(tool_name)`** — die **Tool-Antwort** liefert **description** + **parameters** (volles Schema), dazu **`module_source`** (`file:…` zur definierenden `.py`, aus Registry-Metadaten im Speicher — **nicht** Postgres) und **`readable_via_read_tool`** / **`read_tool_hint`** (ob **`read_tool`** für dieses Modul überhaupt geht). Erst danach sinnvoller Aufruf des Domänen-Tools (Schema liegt in der Historie, nicht in `tools[]`). **`list_available_tools`** bleibt flache Namen+Kurztexte. **Router** steuert nur, **welche** Tools überhaupt in der gemergten Liste sind (Trigger in der letzten User-Message → Vereinigung der Kategorien + Introspection-Tools; kein Treffer → volle Registry, weiterhin nur Katalog). Zusätzliche Kategorien explizit: Header **`X-Agent-Router-Categories`** oder Body **`agent_router_categories`**. **`GET /v1/router/categories`**. **`AGENT_TOOLS_DENYLIST`**. Optional **`tool_prefetch`**. Module: **`AGENT_TOOL_ROUTER_*`**, **`AGENT_TOOL_ROUTER_CATEGORY_ORDER`**. Details: `docker/.env.example`.

---

## Checkliste (built-in)

| Status | Tool | Tool | Kurzbeschreibung |
|--------|------|--------|------------------|
| [x] | `get_current_time` | `clock` | IANA-Zeitzone, ISO-Zeit (ohne DB). |
| [x] | `create_todo` | `todos` | Todo anlegen (**pro** `X-Agent-User-Sub` + Tenant). |
| [x] | `list_todos` | `todos` | Eigene Todos (max. 100). |
| [x] | `set_todo_status` | `todos` | Status nur für eigene Zeilen. |
| [x] | `search_web` | `web_search` | Tavily → Brave → **ddgs**-Metasuche ohne API-Key (inoffiziell). |
| [x] | `deep_search` | `web_search` | Tavily: `raw_content`. Ohne: Snippets + **Seitenabruf** wenn `robots.txt` den UA erlaubt (`fetch_status`, `raw_content`). Abschalten: `AGENT_DISABLE_FETCH_DEEP=true`. |
| [x] | `openweather_current` | `openweather` | Aktuelles Wetter (OpenWeather **`/data/2.5/weather`**, metrisch); Key nur **`OPENWEATHER_API_KEY`**. |
| [x] | `openweather_forecast` | `openweather` | 5-Tage-Vorschau in **3-Stunden-Schritten** (**`/data/2.5/forecast`**). Für „bestes Fenster“ / Heuristiken; kein offizieller Beißindex in der API. |
| [x] | `list_available_tools` | `tool_help` | Alle Tools: Namen + Kurzbeschreibung; **keine** Parameter-Schemas (→ `get_tool_help`). |
| [x] | `list_tool_categories` | `tool_help` | Router-Kategorien: id, Label, Kurztext, Tool-Anzahl (→ `list_tools_in_category`). |
| [x] | `list_tools_in_category` | `tool_help` | Tools **einer** Kategorie: Namen + Kurzbeschreibung; **keine** Schemas (→ `get_tool_help`). |
| [x] | `get_tool_help` | `tool_help` | **Ein** Tool: volles Schema + `how_to_use` (`tool_name`). |
| [x] | `register_secrets` | `register_secrets` | Secret registrieren: Einmalcode + fertiger `curl` (OTP-Flow); nur in `register_secrets.py`. |
| [x] | `secrets_help` | `secrets_help` | Statische Hilfe zu User-Secrets; **kein** OTP — OTP nur aus `register_secrets`. |
| [x] | `create_tool` | `tool_factory/create_tool.py` | Neues Extra-Tool (Quelltext oder Codegen via Ollama); `AGENT_CREATE_TOOL_ENABLED=true` + beschreibbares Extra-Verzeichnis. |
| [x] | `list_tools` | `tool_factory/list_tools.py` | Dateinamen (`.py`, eine Ebene) im beschreibbaren Tool-Modul-Ordner (`AGENT_TOOLS_EXTRA_DIR`). |
| [x] | `read_tool` | `tool_factory/read_tool.py` | Quelltext **nur** für `.py` unter **`AGENT_TOOLS_EXTRA_DIR`** (Extras); eingebaute Image-Tools (`openweather_*`, …) haben hier **keinen** Pfad — Schema per **`get_tool_help`**. |
| [x] | `update_tool` | `tool_factory/update_tool.py` | Patch (`old_string`/`new_string`); Ziel wie bei `read_tool`. Verwechslungen (`overwrite`, `description`, `source`) → klare JSON-Fehler. |
| [x] | `replace_tool` | `tool_factory/replace_tool.py` | Ganze Datei durch `source`; Ziel wie bei `read_tool`. |
| [x] | `rename_tool` | `tool_factory/rename_tool.py` | `.py`-Datei umbenennen (Reload). |
| [x] | `gmail_search` | `gmail` | Gmail-Suche (IMAP `X-GM-RAW`, z. B. `newer_than:7d is:unread`). |
| [x] | `gmail_read` | `gmail` | Eine Mail per IMAP-UID lesen (Plain-Text-Body, gekürzt). |
| [x] | `gmail_collect_for_summary` | `gmail` | Mehrere Mails laden → `combined_excerpt`; Modell fasst für den Nutzer zusammen. |
| [x] | `github_search_code` | `github` | Code-Suche (GitHub-Query-Syntax); Token: `GITHUB_TOKEN` oder User-Secret `github_pat`. |
| [x] | `github_search_issues` | `github` | Issues/PRs-Suche (`repo:…`, `is:open`, …). |
| [x] | `github_get_file` | `github` | Eine Datei aus einem Repo (UTF-8-Text, gekürzt wenn sehr groß). |
| [x] | `github_list_pull_requests` | `github` | PRs eines Repos (`open` / `closed` / `all`). |
| [x] | `github_get_issue` | `github` | Ein Issue oder PR nach Nummer inkl. Body-Auszug. |
| [x] | `calendar_ics_list_events` | `calendar_ics` | ICS-URL; ohne Secret → **`otp_registration`** (google_calendar). Monats-Parameter + **`by_month`**. |
| [x] | `kb_append_note` | `kb` | Persönliche Notiz in Postgres (gleiche User-Scope wie Todos). |
| [x] | `kb_search_notes` | `kb` | Notizen durchsuchen (Volltext + ILIKE). |
| [x] | `kb_read_note` | `kb` | Eine Notiz per `id` voll lesen (Längenlimit). |
| [x] | `workspace_stat` | `workspace` | Metadaten zu einem Pfad unter `AGENT_WORKSPACE_ROOT` (lokaler Mount). |
| [x] | `workspace_list_dir` | `workspace` | Verzeichnisinhalt (relativ, Limits). |
| [x] | `workspace_read_file` | `workspace` | Textdatei lesen (optional Zeilenfenster, UTF-8). |
| [x] | `workspace_glob` | `workspace` | Dateien per Glob ab `path` (z. B. `**/*.py`). |
| [x] | `workspace_search_text` | `workspace` | Volltextsuche (Substring oder Regex) im Mount. |
| [x] | `workspace_replace_text` | `workspace` | `old_string` → `new_string` (einmalig oder `replace_all`). |
| [x] | `workspace_write_file` | `workspace` | Datei anlegen/überschreiben; legt Elternverzeichnisse im Mount an. |

*(Frühere Tool-Namen `issue_secret_registration_otp` / `secret_storage_help` — durch Umbenennung ersetzt.)*

**Hilfe / „Welche Tools gibt es?“**

- In **`tools[]`** pro Request: nur **Kurz**-`description` + Katalog-Hinweis; **volle** **`parameters`** liefert **`get_tool_help(tool_name)`** in der Tool-Antwort.
- Abfragbar: **`list_tool_categories`** → **`list_tools_in_category(category)`** → **`get_tool_help(tool_name)`**; oder flach **`list_available_tools`** → **`get_tool_help`**.

### Dynamisches Extra-Tool (`tool_factory/`)

- **Zweck:** Tool-Module (`.py` mit `TOOLS`/`HANDLERS`) in **`AGENT_TOOLS_EXTRA_DIR`** schreiben und Registry neu laden — neue Namen erscheinen danach in **`list_available_tools`**. Sechs eingebaute Hilfs-Tools, je **eine Datei** unter `agent_tools/tool_factory/` (`create_tool.py`, `list_tools.py`, `read_tool.py`, `update_tool.py`, `replace_tool.py`, `rename_tool.py`); gemeinsame Hilfslogik in `_tool_factory_common.py` (wird von der Registry nicht als Tool geladen).
- **Kurzform (ohne `source`):** Nur **`tool_name`** (oder **`name`**) setzen, z. B. `fishingIndex` — der Server ruft Ollama auf (**`AGENT_CREATE_TOOL_CODEGEN_MODEL`**, Default `qwen2.5-coder:7b`; kleineres Modell z. B. `qwen2.5-coder:3b` per Env), erzeugt ein Modul mit genau einem Tool (Snake-Case-Name + Datei `<name>.py`), validiert, schreibt, **`reload_registry`**, und führt **einen Probelauf** (`run_tool`) mit optional **`test_arguments`** aus. **`description`** optional für genauere Codegen-Hinweise (z. B. Beißindex 0–10).
- **HTTP-APIs im generierten Tool:** Standard-Codegen **ohne** Netzwerk (nur Heuristiken). **`AGENT_CREATE_TOOL_CODEGEN_ALLOW_NETWORK=true`** erlaubt im Prompt **httpx** / **urllib**; API-Schlüssel **nur** über **`os.environ`** (z. B. `OPENWEATHER_API_KEY` in `docker/.env` + gleiche Variable im `agent-layer`-Service), **nie** im Chat oder als Klartext im Quelltext. Alternativ: **`create_tool` mit vollem `source`** — der AST-Check blockiert **httpx** nicht; so kannst du Wetter-APIs auch ohne dieses Flag bauen.
- **Iterieren:** kleine Änderungen mit **`update_tool`** (`old_string`/`new_string`); kompletter Neuinhalt mit **`replace_tool`** (`source`); **`read_tool`** zum Ansehen; **`list_tools`** für Überblick; **`rename_tool`** bei Dateinamen-Wechsel. Kleine Chat-Modelle rufen oft `get_tool_help` für noch nicht existierende Namen auf — Nutzer-Prompt explizit: „Nutze **`create_tool`** mit `tool_name`, nicht `get_tool_help`.“ (**`list_tools`** listet nur Dateien unter `AGENT_TOOLS_EXTRA_DIR`, nicht alle registrierten Tool-Namen — dafür **`list_available_tools`**.)
- **Codegen-Auto-Retry (eingebaut, kein Chat-Goal-Checker):** **`AGENT_CREATE_TOOL_CODEGEN_MAX_ATTEMPTS`** (Default **1** = aus, Maximum **20**) — bei fehlgeschlagener **Validierung** oder fehlgeschlagenem **`test_tool`**-Probe ruft der Server Ollama erneut auf und übergibt den Fehlerkontext. Ersetzt **nicht** `AGENT_MAX_TOOL_ROUNDS` (das sind weiterhin nur Modell-Tool-Schleifen pro Chat-Request).
- **Klassisch:** **`filename`** + **`source`** wie bisher (voller Quelltext).
- **Aktivierung:** `AGENT_CREATE_TOOL_ENABLED=true` — wenn **`AGENT_TOOLS_EXTRA_DIR`** nicht gesetzt ist, verwendet der Agent **`/data/tools`** (Compose-Volume z. B. **`./extra_tools:/data/tools:rw`**). Anderen Pfad nur bei Bedarf setzen. Optional **`AGENT_CREATE_TOOL_MAX_BYTES`** (Default siehe `config.py`).
- **Allowlist:** Ist **`AGENT_TOOLS_ALLOWED_SHA256`** gesetzt und der neue Digest **nicht** darin, liefert das Tool `reload: pending` + **`sha256`** — Betreiber ergänzt die Whitelist und ruft **`POST /v1/admin/reload-tools`** (oder Neustart).
- **Aufbau des Quelltexts:** Wie `docker/extra_tools/sample_echo.py`: Modul mit **`TOOLS`** (Liste im Chat-`tools[]`-Format), **`HANDLERS`** (Name → Callable), Handler-Funktionen mit `def foo(arguments: dict) -> str` und `return json.dumps(...)`. Jedes Element von **`TOOLS`** muss **`{\"type\": \"function\", \"function\": {\"name\": \"…\", \"description\": \"…\", \"parameters\": {...}}}`** sein — der **`name`** gehört **unter** `function`, nicht auf die oberste Ebene des Dicts (häufiger Codegen-Fehler; vor dem Schreiben prüft der Agent `validate_tool_registry_exports`). AST-Check verbietet u. a. `subprocess`, `eval`/`exec`, `os.system` — **kein vollständiger Sandbox**; nur in vertrauenswürdigen Umgebungen aktivieren (**`AGENT_API_KEY`** empfohlen).
- **Anderes Tool aus einem Extra-Plugin aufrufen:** `from app.plugin_invoke import invoke_registered_tool` — Argumente: **registrierter Tool-Funktionsname** (z. B. `openweather_forecast`) und ein **dict** wie im Chat. Rückgabe ist derselbe JSON-String wie bei einem normalen Tool-Call; bei Fehlern oft `{"ok": false, ...}`. Jeder Aufruf wird wie üblich in **`tool_invocations`** protokolliert. Tiefe begrenzt: **`AGENT_TOOL_CHAIN_MAX_DEPTH`** (Default 24). Rekursion (A ruft A) vermeiden. Alternative bleibt `from app.tools import run_tool` (identische Semantik).

**HTTP-Fehler → Selbstkorrektur (optional):** Ist **`AGENT_TOOL_HTTP_ERROR_RECOVERY_HINTS=true`** (Default), erkennt der Agent an der Tool-Antwort grob **HTTP-/httpx-Fehler** (z. B. 400/401) und hängt **eine kurze System-Nachricht** an die nächste Runde: u. a. **`read_tool`** auf die betroffene `.py`, optional **`search_web`** zur API-Doku, dann **`replace_tool`** / **`update_tool`** — inkl. Hinweis, dass **400** oft **falsche Parameter** (nicht zwingend der Key) bedeutet. Ersetzt kein echtes Debugging; kleine Modelle können trotzdem scheitern. Abschalten: Env auf `false`.

**Backups vor Überschreiben:** Vor **`replace_tool`**, **`update_tool`** und **`create_tool`** (wenn die Zieldatei schon existiert / Overwrite) schreibt der Server optional eine Kopie nach **`AGENT_TOOLS_BACKUP_DIR`** oder Default **`AGENT_DATA_DIR/tool_backups`** als `YYYYMMDDThhmmssZ_<basename>.py`. Die JSON-Antwort enthält **`backup_previous`** und **`rollback_hint`**. Abschalten: **`AGENT_TOOLS_BACKUP_ENABLED=false`**. Für längere Historie: **Git** auf dem Host-Volume oder Snapshots — es gibt keine automatische Rotation.

**Validiert (manuell / Stack):** Tool-Loop über Agent → Ollama, Einträge in `todos` + `tool_invocations`; Open WebUI mit OpenAI-Base-URL auf den Agent; `stream: true` über SSE-Shim; Tool-Merge mit WebUI-`tools`; Content-JSON-Fallback für Modelle mit `reasoning`-Feld.

### Multi-User (Postgres)

- Tabellen: **`tenants`**, **`users`** (`external_sub` pro Login, eindeutig je `tenant_id`); **`todos`**, **`user_kb_notes`** und **`tool_invocations`** haben **`tenant_id`** + **`user_id`**.
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
- **Registrieren (Chat):** Tool **`register_secrets`** — legt ein **Einmalkennwort** für den **aktuellen Chat-User** an und liefert **`curl_bash`** (und ggf. **`jq_register_example_de`**): darin ist das OTP schon im JSON; der Nutzer ersetzt nur lokale Platzhalter (Passwort, iCal-URL, …) und führt den Befehl im **Terminal** aus. **Wichtig:** Das Modell soll **keinen** curl selbst erfinden — nur die **exakte** `curl_bash`-Zeile aus der **Tool-Antwort** weitergeben; sonst kaputtes JSON (z. B. `secret`) oder falsches `service_key` (gmail statt `google_calendar`). Kleine Modelle (z. B. Nemotron-nano) machen das oft falsch → größeres Modell mit Tool-Calling oder `curl` manuell aus der Tool-Antwort kopieren. Endpoint: **`POST /v1/user/secrets/register-with-otp`** (ohne Bearer — wenn `AGENT_API_KEY` gesetzt ist, ist dieser Pfad davon ausgenommen). Feld **`secret`** darf **String** (JSON-Text) oder **Objekt** sein — z. B. `{"email":"…","app_password":"…"}` direkt im Body (kein Escaping nötig).
- **OTP-Sicherheit:** Wer den Chat mitlesen kann, könnte das OTP nutzen — kurz gültig (Standard 10 min), **einmalig**; Befehl zeitnah ausführen.
- **`secrets_help`:** nur **Erklärung** im Tool-JSON — **kein** OTP, **kein** curl. OTP ausschließlich aus der Antwort von **`register_secrets`**.
- **Auflisten / Löschen** gespeicherter `service_key`s: HTTP **`GET`** / **`DELETE`** `/v1/user/secrets` mit denselben **User-Headern** wie beim Chat; wenn **`AGENT_API_KEY`** gesetzt ist, zusätzlich **`Authorization: Bearer …`** = **nur** dieser Agent-Key (**niemals** die WebUI-User-ID als Bearer). Für direktes Speichern ohne OTP (Skripte): **`POST`** `/v1/user/secrets` mit denselben Headern — siehe FastAPI-Doku unter dem Agent.
- **Tools** (z. B. E-Mail): serverseitig nur `db.user_secret_get_plaintext(user_id, "…")`; **nie** Klartext in Tool-Antworten an das Modell.
- **Chat-Hilfe:** **`register_secrets`** zum Speichern; **`secrets_help`** nur zur Orientierung. Optional **`AGENT_PUBLIC_URL`** für die Basis-URL in den `register_secrets`-Vorlagen.

### Gmail (`tool gmail`)

- **Pro User** ein Secret mit **`service_key`** = **`gmail`**, Wert = **JSON** (ein String, den das Tool parst):
  ```json
  {"email":"du@gmail.com","app_password":"xxxxxxxxxxxxxxxx"}
  ```
  Leerzeichen im App-Passwort sind erlaubt (werden beim Einlesen entfernt). Google: **2-Faktor** + **App-Passwort**; normales Login-Passwort funktioniert am IMAP-Endpoint nicht.
- **Registrieren:** `register_secrets` mit `service_key_example: "gmail"` — **`curl_bash` eine Zeile**; oder **`jq_register_example_de`**: **eine** Zeile, `--arg e` / `--arg p` für E-Mail und App-Passwort, OTP bereits eingetragen (`tojson` baut das `secret`-Feld).
- **Zugriff:** IMAP **`imap.gmail.com:993`**, Standard-Mailbox **`INBOX`** (Parameter `mailbox` bei Bedarf).
- **Tools:** **`gmail_search`** (Gmail-Suchsyntax wie in der Web-UI), **`gmail_read`** (`uid` aus der Suche), **`gmail_collect_for_summary`** (mehrere Mails → Auszüge; das **Modell** soll daraus eine Zusammenfassung formulieren). **Keine** Mail-Inhalte absichtlich vollständig spammen: `limit` / `max_body_chars` / `max_messages` beachten.

### GitHub (`tool github`)

- **Token:** Umgebung **`GITHUB_TOKEN`** (Compose-`.env`) für alle Nutzer **oder** pro Nutzer Secret **`github_pat`** mit JSON `{"token":"ghp_…"}` bzw. `github_pat_…` (überschreibt Env). Nur **read-only**-Scopes / Fine-grained PAT empfohlen.
- **Tools:** **`github_search_code`**, **`github_search_issues`**, **`github_get_file`**, **`github_list_pull_requests`**, **`github_get_issue`** — siehe `get_tool_help`.

### Lokaler Workspace (`tool workspace`)

- **Nicht dasselbe wie GitHub:** **`github_get_file`** liest über die **GitHub-REST-API** (Remote-Repo, Branch/SHA). Die **`workspace_*`**-Tools arbeiten auf **einem gemounteten Verzeichnis** im Agent-Container (`AGENT_WORKSPACE_ROOT`, absoluter Pfad, z. B. Host-Projekt nach `/workspace`).
- **Aktivierung:** In `docker/.env` **`AGENT_WORKSPACE_ROOT=/workspace`** (oder anderer Pfad) setzen und in `compose.yaml` ein **Volume** eintragen, z. B. `- /pfad/auf/host:/workspace:rw`. Ohne gültiges Verzeichnis liefern alle `workspace_*`-Calls eine klare Fehlermeldung (`ok: false`).
- **Sicherheit:** Nur Pfade **unter** dem aufgelösten Root (kein `..`, kein führendes `/` in `path`). Symlinks werden beim Auflösen berücksichtigt — Mount nur vertrauenswürdige Daten. Schreib-Tools können Dateien **zerstören**; Betreiber-Scope wie Shell-Zugriff.
- **Limits:** u. a. `AGENT_WORKSPACE_MAX_FILE_BYTES`, `AGENT_WORKSPACE_MAX_READ_LINES`, `AGENT_WORKSPACE_SEARCH_MAX_FILE_BYTES` (Suche überspringt größere Dateien), `AGENT_WORKSPACE_MAX_SEARCH_*` / `AGENT_WORKSPACE_MAX_GLOB_FILES` — siehe `docker/.env.example` und `app/config.py`.

### OpenWeather (`tool openweather`)

- **Nicht veraltet:** Das eingebaute Tool nutzt die üblichen **Free-/Subscription-Endpunkte** **`/data/2.5/weather`** und **`/data/2.5/forecast`**. Das sind **nicht** dasselbe wie das frühere „One Call 2.5“-Produkt oder **One Call 3.0** — letztere brauchen oft gesonderte Freischaltung und andere URLs.
- **Env:** nur **`OPENWEATHER_API_KEY`** im Agent-Container (`.env` + Compose). Keine **`OW3_API_KEY`** und keine Keys im Chat.
- **Beißindex / Angeln:** OpenWeather liefert **kein** Feld „bite index“ oder Mondphase in diesen APIs. Vorgehen für das Modell: **`openweather_forecast`** mit `location` aufrufen → aus `forecast[]` (z. B. `temp_c`, `humidity_pct`, `wind_speed_m_s`, `pop`) eine **einfache, erklärte** Formel im Chat anwenden — oder **`openweather_current`** nur für „jetzt“. **Kein** `create_tool`, das `/onecall` oder erfundene JSON-Felder nutzt, es sei denn du hast das Produkt aktiv und weißt die exakte Doku.
- **Kleine Modelle (Nemotron-nano & Co.):** Tool-Factory-Codegen für HTTP + Zeitreihen ist fehleranfällig; lieber **diese beiden Built-ins** nutzen und die Auswertung im Text machen.

### Kalender ICS (`tool calendar_ics`)

- **User-Secrets** (gleiches JSON, der Agent probiert **`google_calendar`** zuerst, sonst **`calendar_ics`**):  
  `{"ics_url":"https://…"}`
  - **Google Kalender (ohne OAuth):** [calendar.google.com](https://calendar.google.com) → Zahnrad → **Einstellungen** → gewünschter Kalender in der Liste → **„Geheime Adresse im iCal-Format“** kopieren (URL enthält `calendar.google.com/calendar/ical/…/basic.ics`). Per **`register_secrets`** mit `service_key_example: "google_calendar"` speichern (oder `calendar_ics`). **URL nicht in den Chat** — nur im Terminal/`curl`.
  - **Nextcloud / andere:** öffentliche oder geheime ICS-HTTPS-URL → meist `calendar_ics`.
- **Tool:** **`calendar_ics_list_events`** — `days_ahead` / `days_back` plus **`months_ahead`** / **`months_back`** (je Monat +31 Tage Fenster) für Überblick über mehrere Monate. Antwort enthält standardmäßig **`by_month`** (`YYYY-MM` → Anzahl + Titel). `include_by_month: false` zum Kürzen. **Ohne Secret** (bei gesetztem **`AGENT_SECRETS_MASTER_KEY`**) liefert die Antwort zusätzlich **`otp_registration`** für **`google_calendar`** (wie `register_secrets`) — oft **ein** Tool-Call genug. Kleine Modelle (z. B. Nemotron) liefern manchmal falsch geschriebene Argumentnamen (`monthsahead` …) — das Tool mappt die gängigen Varianten mit. Kein Schreiben; kein Google Calendar API / OAuth.

### Notizen / KB (`tool kb`)

- Tabelle **`user_kb_notes`** (Migration 5): Volltext-Spalte + ILIKE-Suche.
- **Tools:** **`kb_append_note`**, **`kb_search_notes`**, **`kb_read_note`** — persönlicher „second brain“ ohne Embeddings. Später optional **pgvector** ergänzen.

---

## Checkliste (geplant / optional)

| Status | Tool / Paket | Hinweis |
|--------|----------------|---------|
| [x] | GitHub Search / Repo-Read | Tool `github`; Env `GITHUB_TOKEN` oder Secret `github_pat`. |
| [x] | HTTP-Fetch + robots.txt + noindex | `deep_search` ohne Tavily; optionale Allowlist via Env. |
| [ ] | Weitere Search-Provider (SerpAPI, …) | Optional ergänzen. |
| [x] | Lokaler Workspace (Mount, read/write) | Tool `workspace`; `AGENT_WORKSPACE_ROOT` + Volume. |
| [ ] | Home Assistant / MQTT | Topic-Whitelist. |
| [ ] | RAG mit Embeddings (pgvector, …) | Aktuell: `kb_*` mit Postgres FTS; Embeddings optional. |
| [ ] | Kalender CalDAV (Lesen/Schreiben) | Aktuell nur ICS-URL read-only. |

*(Status hier anpassen, sobald ein Tool gemerged und einmal gegen euren Stack getestet ist.)*

---

## API-Keys & `.env`

Empfehlung: **eine** `docker/.env` (von `.env.example` kopieren), **nicht** committen.

- **Heute:** meist nur Postgres/Ollama/Agent-Settings (`DATABASE_URL`, `OLLAMA_BASE_URL`, `AGENT_API_KEY`, …).
- **Web-Suche:** optional `TAVILY_API_KEY` / `BRAVE_SEARCH_API_KEY`; ohne Keys nutzt das Tool **[ddgs](https://pypi.org/project/ddgs/)** (Metasuche, u. a. Bing/DuckDuckGo-Backends; ohne Vertrag, Rate-Limits möglich). Abschalten: `AGENT_DISABLE_DDG_SEARCH=true`. Zusätzlich `AGENT_SEARCH_TIMEOUT`, `AGENT_SEARCH_MAX_RAW_CHARS`.
- **deep_search ohne Tavily:** pro Treffer optional **HTTP-GET** der URL, nur wenn `robots.txt` für `AGENT_FETCH_USER_AGENT` (Default: `JetpackAgentLayer/…`) **kein** `Disallow` setzt; sonst `fetch_status=robots_disallowed`, kein Abruf. **`AGENT_ROBOTS_STRICT=true`:** wenn `robots.txt` nicht lesbar ist, wird **nicht** gefetcht (Default: in dem Fall wie „keine Regeln“ behandelt). **`AGENT_DISABLE_FETCH_DEEP=true`:** nur Snippets. **`AGENT_FETCH_MAX_BYTES`:** max. Antwortgröße (Default 2 MB). **`AGENT_ROBOTS_CACHE_TTL`:** Cache für `robots.txt` pro Origin (Sekunden). Loopback/Link-Local/Metadata-Hosts werden nicht abgerufen (Basis-SSRF-Schutz). **`AGENT_RESPECT_META_ROBOTS`** (Default `true`): bei **`X-Robots-Tag`** oder **`<meta name="robots" content="…">`** mit **`noindex`** oder **`none`** wird **kein** `raw_content` geliefert (`fetch_status` z. B. `x_robots_noindex` / `meta_robots_noindex`). **`AGENT_FETCH_DOMAIN_ALLOWLIST`:** wenn gesetzt (kommagetrennte Hostnamen), nur noch diese Hosts und ihre Subdomains — alles andere `blocked_allowlist` (reduziert SSRF + Scope).
- **GitHub:** `GITHUB_TOKEN` in `docker/.env` (siehe `.env.example`) **oder** Nutzer registriert `github_pat` per `register_secrets`.
- **Kalender:** kein Env — User-Secret `google_calendar` oder `calendar_ics` mit `{"ics_url":"https://…"}` (Google: geheime iCal-Adresse).
- **Weitere Beispiele:** `SERPAPI_API_KEY=…` — im jeweiligen Tool aus `os.environ` lesen.

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

- Whisper / faster-whisper / ComfyUI als **eigene** Services; der Agent kann sie per HTTP-Tool ansprechen, falls du ein Tool dafür schreibst.

---

## Tool-Vertrag (Kurz)

```text
TOOLS: list[dict]          # Chat tools[] wire shape (type/function/…)
HANDLERS: dict[str, callable]  # name -> fn(args: dict) -> str (JSON-String)
TOOL_ID: str             # optional
__version__: str           # optional
```

Reload Built-in + Extra: `POST /v1/admin/reload-tools?scope=all|extra`.

---

## Sicherheit (Merksatz)

Jedes Tool ist **ausführbarer Code** mit den Rechten des Agent-Containers. Lieber zu wenige, gut begrenzte Tools als ein generisches „run_shell“.
