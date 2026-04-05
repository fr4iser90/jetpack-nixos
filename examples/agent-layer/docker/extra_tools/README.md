# Extra tools (`AGENT_TOOLS_EXTRA_DIR`)

Python modules with `TOOLS` + `HANDLERS` in this directory (or any mounted extra-tools tree). After changes: `POST /v1/admin/reload-tools`.

## Prompt: `create_tool` (German example)

```text
Rufe create_tool auf mit tool_name "fishingIndex", overwrite true, und TOOL_DESCRIPTION:
Grober Beißindex 0–10 fürs Angeln. Nutze httpx + OpenWeather /data/2.5/weather mit Query-Parameter **q** (nicht city), https, API-Key nur os.environ["OPENWEATHER_API_KEY"]. Handler nur return json.dumps(...), keine Tupel.
```

## Autonomous fix loop (model + server)

1. **Server (default on):** If a tool returns something that looks like an HTTP error, the agent injects a short **system hint** (`AGENT_TOOL_HTTP_ERROR_RECOVERY_HINTS`, see `TOOLS.md`): read source, optional web search, replace tool.
2. **System prompt (optional, stronger):** You can add: *If any tool returns JSON or text mentioning HTTP 400/401, call `read_tool` for that tool’s file, optionally `search_web` for the official API parameter names, then `replace_tool` with the fix. Do not assume 400 means invalid key.*

Typical OpenWeather mistake: using `city=` instead of **`q=`** on `/data/2.5/weather` → **400**.

## Composing built-in weather from an extra tool

```python
from app.plugin_invoke import invoke_registered_tool

raw = invoke_registered_tool("openweather_current", {"location": "Leipzig,de"})
```

See `app/plugin_invoke.py` and `TOOLS.md`.
