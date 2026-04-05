"""
Shipped tool tree: **recursive** scan for ``*.py`` (``TOOLS`` + ``HANDLERS``); see ``app.registry``.

**Layout (2-level sweet spot)** — first directory under ``agent_tools/`` is the **layer** (stored as
``tools_meta[].layer`` for operators / future filtering). Go deeper only when it helps (e.g. many
modules under ``domains/fishing/``).

- ``core/`` — introspection, secrets, workspace, **tool_factory** (dynamic plugins).
- ``knowledge/`` — KB, RAG, long-term notes / vectors.
- ``external/`` — network APIs (GitHub, web search, weather, …).
- ``productivity/`` — mail, calendar, todos, clocks.
- ``domains/`` — **your** verticals (fishing, survival, games, …); keep technical vs domain split.

**Scaling (100+ / 1000+ tools):** Folders alone are not enough. Use (1) **router categories**
(``TOOL_DOMAIN`` + ``TOOL_TRIGGERS`` per module), (2) **staged discovery** (``list_tool_categories`` →
``list_tools_in_category`` → ``get_tool_help``), (3) optional **``TOOL_TAGS``** on a module
(reflected in ``tools_meta``), (4) later: embedding search over tool TOOL_DESCRIPTIONs or capability
indexes — not implemented in the HTTP core yet.

Extra tools under ``AGENT_TOOLS_EXTRA_DIR`` may mirror the same shape (e.g. ``extra_tools/domains/...``).
"""
