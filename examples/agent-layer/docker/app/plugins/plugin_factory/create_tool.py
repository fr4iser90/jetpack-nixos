"""Optional: manage extra ``*.py`` plugins under AGENT_PLUGINS_EXTRA_DIR (create, read, update, rename)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable

import httpx

from app import config
from app import plugin_authoring
from app.registry import get_registry, reload_registry

logger = logging.getLogger(__name__)

__version__ = "1.2.0"
PLUGIN_ID = "create_tool"


def _coerce_test_args(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            o = json.loads(s)
            return dict(o) if isinstance(o, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _extra_root_or_error() -> tuple[Path | None, str | None]:
    if not config.CREATE_TOOL_ENABLED:
        return None, json.dumps(
            {
                "ok": False,
                "error": (
                    "extra plugin tools are disabled. Set AGENT_CREATE_TOOL_ENABLED=true "
                    "and mount a writable directory (e.g. ./extra_plugins:/data/plugins:rw)."
                ),
            },
            ensure_ascii=False,
        )
    raw = (config.PLUGINS_EXTRA_DIR or "").strip()
    if not raw:
        return None, json.dumps(
            {
                "ok": False,
                "error": (
                    "AGENT_PLUGINS_EXTRA_DIR is empty. With create_tool enabled, default is /data/plugins "
                    "— ensure that path is mounted read-write from the host."
                ),
            },
            ensure_ascii=False,
        )
    root = Path(raw)
    if not root.is_dir():
        return None, json.dumps(
            {"ok": False, "error": f"AGENT_PLUGINS_EXTRA_DIR is not a directory: {raw}"},
            ensure_ascii=False,
        )
    return root, None


def _digest_reload_response(
    fn: str,
    dest: Path,
    *,
    codegen: bool = False,
    codegen_model: str | None = None,
    test_tool_name: str | None = None,
    test_arguments: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    allow = config.plugins_allowed_sha256()
    if allow is not None and digest not in allow:
        out: dict[str, Any] = {
            "ok": True,
            "written": fn,
            "path": str(dest),
            "sha256": digest,
            "reload": "pending",
            "codegen": codegen,
            "warning": (
                "AGENT_PLUGINS_ALLOWED_SHA256 is set — file NOT loaded until operator adds sha256 "
                "to env and POST /v1/admin/reload-plugins or restarts."
            ),
        }
        if extra:
            out.update(extra)
        return json.dumps(out, ensure_ascii=False)
    try:
        reload_registry(scope="all")
    except Exception as e:
        logger.exception("reload after extra plugin change failed")
        out = {
            "ok": True,
            "written": fn,
            "path": str(dest),
            "sha256": digest,
            "reload": "failed",
            "error": str(e),
            "codegen": codegen,
            "hint": "POST /v1/admin/reload-plugins or restart",
        }
        if extra:
            out.update(extra)
        return json.dumps(out, ensure_ascii=False)

    reg = get_registry()
    out = {
        "ok": True,
        "written": fn,
        "path": str(dest),
        "sha256": digest,
        "reload": "ok",
        "codegen": codegen,
        "plugin_file_entries": len(
            [m for m in reg.plugins_meta if "file:" in str(m.get("source", ""))]
        ),
        "hint": "Use list_available_tools; read_extra_plugin / update_extra_plugin for this file.",
    }
    if codegen_model:
        out["codegen_model"] = codegen_model
    if extra:
        out.update(extra)
    if test_tool_name:
        from app.tools import run_tool

        probe = run_tool(test_tool_name, test_arguments or {})
        out["test_tool"] = {"name": test_tool_name, "result": probe}
    return json.dumps(out, ensure_ascii=False)


def _validate_module_text(text: str, fn: str, *, codegen: bool) -> str | None:
    _ = codegen
    if len(text.encode("utf-8")) > config.CREATE_TOOL_MAX_BYTES:
        return (
            f"source exceeds AGENT_CREATE_TOOL_MAX_BYTES ({config.CREATE_TOOL_MAX_BYTES}); "
            "raise limit or split the plugin."
        )
    try:
        compile(text, fn, "exec")
    except SyntaxError as e:
        return f"compile failed: {e}"
    ast_err = plugin_authoring.validate_plugin_source(text)
    if ast_err:
        return ast_err
    return plugin_authoring.validate_plugin_registry_exports(text)


def _extract_python_from_llm(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    if "```" not in t:
        return t
    parts = t.split("```")
    for i in range(1, len(parts), 2):
        block = parts[i].strip()
        if block.lower().startswith("python"):
            block = block[6:].lstrip()
        if "HANDLERS" in block and "TOOLS" in block:
            return block.strip()
    for i in range(1, len(parts), 2):
        block = parts[i].strip()
        if block.lower().startswith("python"):
            block = block[6:].lstrip()
        if block:
            return block.strip()
    return t


def _ollama_generate_module(
    *,
    openai_tool_name: str,
    display_hint: str,
    extra_description: str,
) -> tuple[str | None, str | None]:
    system = (
        "You output ONE complete Python 3.11 module only. No markdown fences. No prose before or after.\n\n"
        "The module MUST:\n"
        "- start with: from __future__ import annotations\n"
        "- import json\n"
        "- from typing import Any, Callable\n"
        '- set __version__ = "0.1.0"\n'
        f'- set PLUGIN_ID = "{openai_tool_name}"\n'
        f"- define def {openai_tool_name}(arguments: dict[str, Any]) -> str that returns json.dumps(...) "
        "with UTF-8-safe strings\n"
        f'- HANDLERS = {{"{openai_tool_name}": {openai_tool_name}}}\n'
        "- TOOLS must be a list with EXACTLY this nesting (name goes INSIDE \"function\", never at top level):\n"
        "TOOLS = [\n"
        "    {\n"
        '        "type": "function",\n'
        '        "function": {\n'
        f'            "name": "{openai_tool_name}",\n'
        '            "description": "…",\n'
        '            "parameters": {\n'
        '                "type": "object",\n'
        '                "properties": { ... },\n'
        '                "required": [],\n'
        "            },\n"
        "        },\n"
        "    },\n"
        "]\n\n"
        "Rules:\n"
        f"- Exactly one TOOLS entry; HANDLERS has exactly one key \"{openai_tool_name}\".\n"
    )
    if config.CREATE_TOOL_CODEGEN_ALLOW_NETWORK:
        system += (
            "- HTTP: you MAY use httpx (e.g. httpx.Client(timeout=10.0)) or urllib.request for public APIs. "
            "Never hardcode secrets — only os.environ.get(\"SOME_API_KEY\") etc.; operator sets env in Docker. "
            "Return clear json errors on HTTP failures.\n"
            "- Still forbidden: subprocess, os.system, eval, exec, __import__, reading/writing local files.\n"
        )
    else:
        system += (
            "- No network: implement deterministic heuristics from tool arguments only; state that in the description.\n"
            "- No subprocess, os.system, eval/exec/__import__, no httpx/urllib for HTTP.\n"
        )
    user = (
        f"Implement a plugin for this short name / idea: {display_hint}\n"
        f"OpenAI function name (required, already chosen): {openai_tool_name}\n"
        f"Extra instructions: {extra_description or '(none)'}\n"
    )
    url = f"{config.OLLAMA_BASE_URL}/v1/chat/completions"
    payload: dict[str, Any] = {
        "model": config.CREATE_TOOL_CODEGEN_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "temperature": 0.2,
    }
    try:
        with httpx.Client(timeout=float(config.CREATE_TOOL_CODEGEN_TIMEOUT)) as client:
            resp = client.post(url, json=payload, headers={"Content-Type": "application/json"})
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        return None, f"codegen HTTP {e.response.status_code}: {e.response.text[:2000]}"
    except Exception as e:
        return None, f"codegen request failed: {e}"

    choice0 = (data.get("choices") or [{}])[0]
    msg = choice0.get("message") or {}
    content = msg.get("content")
    if not isinstance(content, str) or not content.strip():
        return None, "codegen: empty model response"
    raw = _extract_python_from_llm(content)
    if not re.search(r"\bHANDLERS\b", raw) or not re.search(r"\bTOOLS\b", raw):
        return None, "codegen: response does not look like a plugin module"
    return raw, None


def list_extra_plugins(arguments: dict[str, Any]) -> str:
    _ = arguments
    root, err = _extra_root_or_error()
    if err:
        return err
    assert root is not None
    names = sorted(p.name for p in root.iterdir() if p.is_file() and p.suffix == ".py")
    return json.dumps(
        {
            "ok": True,
            "directory": str(root),
            "files": names,
            "hint": "Basenames only; use read_extra_plugin(filename) for full source.",
        },
        ensure_ascii=False,
    )


def read_extra_plugin(arguments: dict[str, Any]) -> str:
    root, err = _extra_root_or_error()
    if err:
        return err
    assert root is not None
    fn, fe = plugin_authoring.sanitize_plugin_filename(str(arguments.get("filename") or ""))
    if fe or not fn:
        return json.dumps({"ok": False, "error": fe or "filename required"}, ensure_ascii=False)
    dest = root / fn
    if not dest.is_file():
        return json.dumps({"ok": False, "error": f"not found: {fn}"}, ensure_ascii=False)
    try:
        text = dest.read_text(encoding="utf-8")
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    if len(text.encode("utf-8")) > config.CREATE_TOOL_MAX_BYTES:
        return json.dumps(
            {
                "ok": False,
                "error": f"file larger than AGENT_CREATE_TOOL_MAX_BYTES ({config.CREATE_TOOL_MAX_BYTES})",
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {"ok": True, "filename": fn, "source": text, "byte_length": len(text.encode("utf-8"))},
        ensure_ascii=False,
    )


def update_extra_plugin(arguments: dict[str, Any]) -> str:
    root, err = _extra_root_or_error()
    if err:
        return err
    assert root is not None
    fn, fe = plugin_authoring.sanitize_plugin_filename(str(arguments.get("filename") or ""))
    if fe or not fn:
        return json.dumps({"ok": False, "error": fe or "filename required"}, ensure_ascii=False)
    source = arguments.get("source")
    if source is None or not str(source).strip():
        return json.dumps({"ok": False, "error": "source required (full module text)"}, ensure_ascii=False)
    text = str(source)
    val_err = _validate_module_text(text, fn, codegen=False)
    if val_err:
        return json.dumps({"ok": False, "error": val_err}, ensure_ascii=False)
    dest = root / fn
    if not dest.is_file():
        return json.dumps(
            {"ok": False, "error": f"file does not exist: {fn}; use create_tool to add a new file"},
            ensure_ascii=False,
        )
    try:
        dest.write_text(text, encoding="utf-8", newline="\n")
    except OSError as e:
        return json.dumps({"ok": False, "error": f"write failed: {e}"}, ensure_ascii=False)
    return _digest_reload_response(fn, dest)


def rename_extra_plugin(arguments: dict[str, Any]) -> str:
    root, err = _extra_root_or_error()
    if err:
        return err
    assert root is not None
    old_fn, e1 = plugin_authoring.sanitize_plugin_filename(str(arguments.get("old_filename") or ""))
    new_fn, e2 = plugin_authoring.sanitize_plugin_filename(str(arguments.get("new_filename") or ""))
    if e1 or not old_fn:
        return json.dumps({"ok": False, "error": e1 or "old_filename required"}, ensure_ascii=False)
    if e2 or not new_fn:
        return json.dumps({"ok": False, "error": e2 or "new_filename required"}, ensure_ascii=False)
    old_p = root / old_fn
    new_p = root / new_fn
    if not old_p.is_file():
        return json.dumps({"ok": False, "error": f"not found: {old_fn}"}, ensure_ascii=False)
    overwrite = bool(arguments.get("overwrite", False))
    if new_p.exists() and not overwrite:
        return json.dumps(
            {"ok": False, "error": f"target exists: {new_fn}; pass overwrite:true to replace"},
            ensure_ascii=False,
        )
    try:
        if new_p.exists():
            new_p.unlink()
        old_p.rename(new_p)
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    return _digest_reload_response(
        new_fn,
        new_p,
        extra={"renamed_from": old_fn},
    )


def create_tool(arguments: dict[str, Any]) -> str:
    root, err = _extra_root_or_error()
    if err:
        return err
    assert root is not None
    extra_root = root

    source_raw = arguments.get("source")
    source_str = str(source_raw).strip() if source_raw is not None else ""
    codegen = not source_str
    test_tool_name: str | None = None
    codegen_model: str | None = None

    if codegen:
        hint = str(arguments.get("tool_name") or arguments.get("name") or "").strip()
        if not hint:
            return json.dumps(
                {
                    "ok": False,
                    "error": (
                        "Either pass source+filename, or omit source and set tool_name (or name) "
                        "so the server can generate code via Ollama (AGENT_CREATE_TOOL_CODEGEN_MODEL)."
                    ),
                },
                ensure_ascii=False,
            )
        snake, terr = plugin_authoring.slugify_openai_tool_name(hint)
        if terr:
            return json.dumps({"ok": False, "error": terr}, ensure_ascii=False)
        fn, fe = plugin_authoring.sanitize_plugin_filename(f"{snake}.py")
        if fe or not fn:
            return json.dumps({"ok": False, "error": fe or "invalid filename"}, ensure_ascii=False)
        extra_desc = str(arguments.get("description") or "").strip()
        text, gen_err = _ollama_generate_module(
            openai_tool_name=snake,
            display_hint=hint,
            extra_description=extra_desc,
        )
        codegen_model = config.CREATE_TOOL_CODEGEN_MODEL
        if gen_err:
            return json.dumps(
                {"ok": False, "error": gen_err, "codegen": True, "model": codegen_model},
                ensure_ascii=False,
            )
        test_tool_name = snake
    else:
        fn, fn_err = plugin_authoring.sanitize_plugin_filename(
            str(arguments.get("filename") or "")
        )
        if fn_err:
            return json.dumps({"ok": False, "error": fn_err}, ensure_ascii=False)
        text = source_str

    val_err = _validate_module_text(text, fn, codegen=codegen)
    if val_err:
        return json.dumps(
            {"ok": False, "error": val_err, "codegen": codegen},
            ensure_ascii=False,
        )

    overwrite = bool(arguments.get("overwrite", False))
    dest = extra_root / fn
    if dest.exists() and not overwrite:
        return json.dumps(
            {
                "ok": False,
                "error": f"file already exists: {fn}; pass overwrite:true to replace",
            },
            ensure_ascii=False,
        )

    try:
        dest.write_text(text, encoding="utf-8", newline="\n")
    except OSError as e:
        return json.dumps({"ok": False, "error": f"write failed: {e}"}, ensure_ascii=False)

    return _digest_reload_response(
        fn,
        dest,
        codegen=codegen,
        codegen_model=codegen_model,
        test_tool_name=test_tool_name,
        test_arguments=_coerce_test_args(arguments.get("test_arguments")),
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "create_tool": create_tool,
    "list_extra_plugins": list_extra_plugins,
    "read_extra_plugin": read_extra_plugin,
    "update_extra_plugin": update_extra_plugin,
    "rename_extra_plugin": rename_extra_plugin,
}

_TOOLS_CREATE: dict[str, Any] = {
    "name": "create_tool",
    "description": (
        "Create a new extra plugin (.py with TOOLS + HANDLERS). "
        "(1) filename + source, or (2) omit source: tool_name + optional description → Ollama codegen. "
        "Then list_available_tools. Workflow: on failure read_extra_plugin / update_extra_plugin. "
        "Requires AGENT_CREATE_TOOL_ENABLED=true and writable extra plugin dir."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "tool_name": {
                "type": "string",
                "description": "Codegen: short idea (e.g. fishingIndex) → snake_case file + tool name.",
            },
            "name": {"type": "string", "description": "Alias for tool_name (codegen)."},
            "description": {
                "type": "string",
                "description": "Codegen: domain hints (e.g. Beißindex 0–10, heuristics only, no APIs).",
            },
            "filename": {"type": "string", "description": "With source: basename e.g. my_plugin.py"},
            "source": {
                "type": "string",
                "description": "Full module UTF-8 text; omit to trigger codegen.",
            },
            "overwrite": {"type": "boolean"},
            "test_arguments": {"type": "object", "description": "Optional probe args after codegen reload."},
        },
    },
}

_TOOLS_LIST: dict[str, Any] = {
    "name": "list_extra_plugins",
    "description": "List .py basenames in AGENT_PLUGINS_EXTRA_DIR (top level only).",
    "parameters": {"type": "object", "properties": {}},
}

_TOOLS_READ: dict[str, Any] = {
    "name": "read_extra_plugin",
    "description": "Return full UTF-8 source of one extra plugin file (same validation size limit as create).",
    "parameters": {
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "Basename e.g. fishing_index.py"},
        },
        "required": ["filename"],
    },
}

_TOOLS_UPDATE: dict[str, Any] = {
    "name": "update_extra_plugin",
    "description": (
        "Replace an existing extra plugin file with new source; compile + AST check; reload registry. "
        "Use after read_extra_plugin to fix codegen errors."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "filename": {"type": "string"},
            "source": {"type": "string", "description": "Full replacement module text"},
        },
        "required": ["filename", "source"],
    },
}

_TOOLS_RENAME: dict[str, Any] = {
    "name": "rename_extra_plugin",
    "description": "Rename a .py plugin in the extra directory (basenames only); reload registry.",
    "parameters": {
        "type": "object",
        "properties": {
            "old_filename": {"type": "string"},
            "new_filename": {"type": "string"},
            "overwrite": {"type": "boolean"},
        },
        "required": ["old_filename", "new_filename"],
    },
}

TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": _TOOLS_CREATE},
    {"type": "function", "function": _TOOLS_LIST},
    {"type": "function", "function": _TOOLS_READ},
    {"type": "function", "function": _TOOLS_UPDATE},
    {"type": "function", "function": _TOOLS_RENAME},
]
