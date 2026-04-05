# Agent layer: architecture and tool routing

This document describes the **layers** of the example under `examples/agent-layer/docker/` and how **tool routing** works (which tools end up in `tools[]` per chat request). For tool behavior, Postgres, and security, see [`examples/agent-layer/TOOLS.md`](../examples/agent-layer/TOOLS.md).

---

## 1. Overview

The **agent layer** is a FastAPI service that:

- Exposes an **OpenAI-compatible HTTP API** (`/v1/chat/completions`, …) to clients;
- Forwards requests to **Ollama** (`OLLAMA_BASE_URL`, e.g. `http://ollama:11434`);
- Executes **tool calls** locally (Python handlers from the **tool registry**);
- Uses **PostgreSQL** (compose default image includes **pgvector**) for todos, KB, `tool_invocations`, and optional **RAG**: operators ingest text with `POST /v1/admin/rag/ingest` (same user/tenant headers as chat); the model calls **`rag_search`** for vector similarity, with optional **domain** filter. Embeddings use Ollama `POST /api/embeddings` (`AGENT_RAG_OLLAMA_MODEL`, default `nomic-embed-text`). The DB column is `vector(768)` — keep **embedding dimension** aligned with the model (see `AGENT_RAG_EMBEDDING_DIM`). **LoRA / fine-tuning** is a separate training track and is not part of this HTTP+RAG path.

The **tools** are **your** registered modules (`TOOLS` / `HANDLERS` in `*.py`); the JSON shape in `tools[]` follows the usual Chat Completions **wire format** for the model — that is only the transport shape, not “OpenAI tools” as a product concept.

---

## 2. Layers

```mermaid
flowchart TB
  subgraph client [Client]
    OW[Open WebUI / curl / Custom UI]
  end

  subgraph agent_layer [Agent-layer FastAPI]
    MAIN[main.py: /v1/chat/completions]
    AG[agent.py: chat_completion]
    TR[tool_routing.py]
    REG[registry.py: ToolRegistry]
    RUN[tools.py: run_tool]
  end

  subgraph backends [Backends]
    OLL[Ollama /v1/chat/completions]
    PG[(PostgreSQL)]
  end

  OW -->|HTTP JSON + optional tools[]| MAIN
  MAIN -->|Header X-Agent-Router-Categories| AG
  AG --> TR
  AG --> REG
  AG -->|Loop: tool_calls| OLL
  OLL -->|assistant + tool_calls| AG
  AG --> RUN
  RUN --> REG
  REG -->|Tool handlers| PG
```

| Layer | Role |
|--------|------|
| **Client** | Sends `messages`, optional `tools`, optional `stream`. May set header `X-Agent-Router-Categories`. |
| **`main.py`** | Parses body, sets user/tenant (`contextvars`), reads router header, calls `chat_completion`; with `stream: true`, wraps the JSON response as SSE. |
| **`agent.py`** | Merges tool lists, **router filter**, builds **catalog** `tools[]` for Ollama, loop: POST Ollama → on `tool_calls` → `run_tool` → Ollama again until text or `MAX_TOOL_ROUNDS`. |
| **`tool_routing.py`** | Last user message → categories; filter: allowed tool names + fixed introspection tools. |
| **`registry.py`** | Loads `*.py` from configured dirs, builds `chat_tool_specs`, handler map, per-module **router metadata** (`TOOL_DOMAIN`, triggers, labels). |
| **`tools.py`** | `run_tool(name, args)` including chain depth (`AGENT_TOOL_CHAIN_MAX_DEPTH`). |
| **Ollama** | LLM with (filtered) `tools[]`; returns `tool_calls` or text. |
| **PostgreSQL** | Used by individual tools (not hardcoded in the HTTP core). |

---

## 3. Where tools come from

1. **Registry scan** (`ToolRegistry.load_all`): recursively loads `*.py` under `AGENT_TOOL_DIRS` or defaults (`agent_tools` in the image + optional `AGENT_TOOLS_EXTRA_DIR`). Shipped tools are grouped under **`agent_tools/{core,knowledge,external,productivity,domains}/`**; each module’s `tools_meta` entry may include **`layer`**, optional **`domain`** / **`requires`** / **`tags`**, and optional **`per_tool`** overrides (`AGENT_TOOL_META_BY_NAME`). After trigger/header category filtering, **`X-Agent-Tool-Domain`** / **`agent_tool_domain`** can narrow to that domain plus **`domain=shared`** tools (e.g. `outdoor_environment_snapshot`).
2. Each module exports **`TOOLS`** (list of specs in Chat `tools[]` shape) and **`HANDLERS`** (name → callable).
3. **`chat_tool_specs`** is the list of those specs used on the chat path.

**Merge with the client** (`_merge_tools` in `agent.py`):

- The base is **always** the registry list.
- Extra entries from the request body `tools` are appended when the **name** is not already in the registry (so Open WebUI can add tools without replacing the registry list).

---

## 4. Two different “spectra”

### 4.1 Which tool **names** does the model see?

Controlled by **tool routing** (section 5): a subset of the **merged** list — or, if routing is inactive, the **full** merged list.

### 4.2 How large are **parameter schemas** in `tools[]`?

Regardless of routing, `_tools_for_chat_request` replaces most entries with a **catalog** entry: name, description, **minimal** `parameters` (for most tools: empty object with `additionalProperties: true`).

The **full** JSON schema for a domain tool is returned by **`get_tool_help(tool_name)`** in the tool round (“staged exploration”). That is **not** automatic “only the three tools the model needs” — it mainly **reduces tokens** for schemas inside `tools[]`.

---

## 5. Tool routing (categories)

### 5.1 Goal

Send only a **subset** of tool names to Ollama when the **last user message** (plus optional overrides) matches certain **router categories** — e.g. only `tool_factory` tools while editing extra plugins, without pulling in all GitHub/Gmail tools.

### 5.2 Where `cats` comes from

The set `cats` is the **union** of:

1. **Text classification** — `classify_user_tool_categories(last_user_text(messages))`  
   - Per category, the registry holds **trigger strings** (substring match, lowercased).  
   - Triggers come from module attribute **`TOOL_TRIGGERS`** or fallback: **`TOOL_ID`** lowercased.  
   - Category id = **`TOOL_DOMAIN`** on the tool module (lowercased in the registry).

2. **HTTP header** — `X-Agent-Router-Categories: cat1,cat2` (comma-separated, forwarded from `main.py`).

3. **JSON body** — `agent_router_categories` (string or list of strings).  
   - Stripped from the body in `agent.py` before the payload goes to Ollama (not part of the Chat Completions schema).

### 5.3 Filter logic

In `tool_routing.filter_merged_tools_by_categories` (always called from `chat_completion`):

- If **`categories` is empty**:
  - **`AGENT_ROUTER_STRICT_DEFAULT=false` (legacy):** return the **full** merged tool list.
  - **`AGENT_ROUTER_STRICT_DEFAULT=true`:** return only the **minimal introspection** tool names (default: `list_tool_categories`, `list_tools_in_category`, `list_available_tools`, `get_tool_help`; override with comma-separated `AGENT_ROUTER_MINIMAL_TOOLS`).

- If **`categories` is non-empty**:
  - **Allowed** = fixed **introspection tools**  
    `list_available_tools`, `get_tool_help`, `list_tool_categories`, `list_tools_in_category`  
    **plus** all tool names that belong to **at least one** selected category (union across categories).
  - All other specs are removed.

- If resolution yields **no** extra tool names from known categories (unknown or empty category ids) → **warning** in logs:
  - **strict default on:** use the **same minimal introspection** set (not the full list).
  - **strict default off:** return the **full** merged list (legacy).

### 5.4 When routing applies in `chat_completion`

```text
cats = classify_user_tool_categories(...) ∪ header ∪ body
merged_tools = filter_merged_tools_by_categories(merged_tools, cats)
```

Logs use `routed_category`: matched category id(s), or `minimal` when strict default applied with empty `cats`, or `full` when legacy full list.

### 5.5 Category order for text classification

`AGENT_TOOL_DOMAIN_ORDER` in `.env` controls which **known** categories are considered **first** in the registry’s trigger loop. It does **not** directly change the **count** of tools in the union; it only affects check order. **Multiple** categories can match at once → **union** of their tools → large lists (e.g. `github+openweather+todos+tool_factory`).

### 5.6 Extra: `AGENT_TOOLS_DENYLIST`

After merge and router filter, individual tool names can still be removed via a comma-separated env list.

---

## 6. File reference

| File | Contents |
|------|----------|
| `examples/agent-layer/docker/app/main.py` | FastAPI, chat route, router header |
| `examples/agent-layer/docker/app/agent.py` | Merge, routing, Ollama loop, catalog `tools[]`, content-tool fallback |
| `examples/agent-layer/docker/app/tool_routing.py` | Introspection set, `filter_merged_tools_by_categories` |
| `examples/agent-layer/docker/app/registry.py` | Scan, `classify_tool_router_categories`, `router_tool_names_for_category` |
| `examples/agent-layer/docker/app/config.py` | `AGENT_TOOL_DOMAIN_ORDER`, `AGENT_TOOLS_DENYLIST`, … |
| `examples/agent-layer/docker/.env.example` | Commented variables |

---

## 7. Operator API

- **`GET /v1/router/categories`** — Catalog of router categories (id, label, description, tool count) for UIs and presets.
- See `examples/agent-layer/TOOLS.md` for header and body fields in detail.

---

*Reflects the `jetpack-nixos` tree (agent layer under `examples/agent-layer`).*
