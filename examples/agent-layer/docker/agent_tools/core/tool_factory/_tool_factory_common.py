"""Shared helpers for tool_factory tools (not a tool — ``_*`` skipped by registry scan)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app import config
from app import tool_authoring
from app.registry import get_registry, reload_registry
from app.tool_name_hints import suggest_tool_names

logger = logging.getLogger(__name__)


def coerce_test_args(raw: Any) -> dict[str, Any]:
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


def extra_root_or_error() -> tuple[Path | None, str | None]:
    if not config.CREATE_TOOL_ENABLED:
        return None, json.dumps(
            {
                "ok": False,
                "error": (
                    "tool factory is disabled. Set AGENT_CREATE_TOOL_ENABLED=true "
                    "and mount a writable directory (e.g. ./extra_tools:/data/tools:rw)."
                ),
            },
            ensure_ascii=False,
        )
    raw = (config.TOOLS_EXTRA_DIR or "").strip()
    if not raw:
        return None, json.dumps(
            {
                "ok": False,
                "error": (
                    "AGENT_TOOLS_EXTRA_DIR is empty. With create_tool enabled, default is /data/tools "
                    "— ensure that path is mounted read-write from the host."
                ),
            },
            ensure_ascii=False,
        )
    root = Path(raw)
    if not root.is_dir():
        return None, json.dumps(
            {"ok": False, "error": f"AGENT_TOOLS_EXTRA_DIR is not a directory: {raw}"},
            ensure_ascii=False,
        )
    return root, None


def _path_under_extra(path: Path, extra_root: Path) -> bool:
    try:
        path.resolve().relative_to(extra_root.resolve())
        return True
    except (ValueError, OSError):
        return False


def parse_tool_meta_file_path(source: Any) -> Path | None:
    if not isinstance(source, str) or not source.startswith("file:"):
        return None
    return Path(source[5:])


def resolve_extra_py_filename(*, extra_root: Path, hint: str) -> tuple[str | None, str | None]:
    """
    Map ``fishing_index``, ``fishingIndex``, or ``fishing_index.py`` to a basename under ``extra_root``
    using registry metadata (only tools loaded from files inside that directory).
    """
    h = (hint or "").strip()
    if not h:
        return None, json.dumps({"ok": False, "error": "tool name hint is empty"}, ensure_ascii=False)
    er = extra_root.resolve()

    if h.endswith(".py"):
        fn, fe = tool_authoring.sanitize_tool_filename(h)
        if fe:
            return None, json.dumps({"ok": False, "error": fe}, ensure_ascii=False)
        if (er / fn).is_file():
            return fn, None
        return None, json.dumps(
            {
                "ok": False,
                "error": f"no file {fn!r} under AGENT_TOOLS_EXTRA_DIR",
                "hint": "Use list_tools for basenames.",
            },
            ensure_ascii=False,
        )

    snake, terr = tool_authoring.slugify_registered_tool_function_name(h)
    if terr:
        return None, json.dumps({"ok": False, "error": terr}, ensure_ascii=False)

    reg = get_registry()
    for meta in reg.tools_meta:
        path = parse_tool_meta_file_path(meta.get("source"))
        if path is None:
            continue
        try:
            pr = path.resolve()
        except OSError:
            pr = path
        if not _path_under_extra(pr, er):
            continue
        tools = meta.get("tools") or []
        if not isinstance(tools, list):
            continue
        tool_set = {str(t) for t in tools if isinstance(t, str)}
        if snake in tool_set or h in tool_set:
            return path.name, None

    return None, json.dumps(
        {
            "ok": False,
            "error": (
                f"no module under AGENT_TOOLS_EXTRA_DIR exports registered tool function name {snake!r} "
                f"(hint: {h!r})"
            ),
            "hint": (
                "Use list_available_tools for names, list_tools for .py files; "
                "registered_tool_name must match a tool defined in a file under the extra tool directory."
            ),
            "suggestions": suggest_tool_names(get_registry(), h),
            "read_tool_note": (
                "read_tool only reads .py under AGENT_TOOLS_EXTRA_DIR. "
                "Built-in tools (e.g. openweather_current) live in the image — use get_tool_help with that name, "
                "not read_tool."
            ),
        },
        ensure_ascii=False,
    )


def coalesce_tool_file_target(arguments: dict[str, Any], *, extra_root: Path) -> tuple[str | None, str | None]:
    """Return ``(basename.py, None)`` or ``(None, error_json_str)``."""
    raw_fn = str(arguments.get("filename") or "").strip()
    if raw_fn:
        fn, fe = tool_authoring.sanitize_tool_filename(raw_fn)
        if fe:
            return None, json.dumps({"ok": False, "error": fe}, ensure_ascii=False)
        return fn, None

    for key in ("registered_tool_name", "tool_name", "name"):
        v = arguments.get(key)
        if v is None or not str(v).strip():
            continue
        return resolve_extra_py_filename(extra_root=extra_root, hint=str(v).strip())

    return None, json.dumps(
        {
            "ok": False,
            "error": "Provide filename (e.g. fishing_index.py) or registered_tool_name / tool_name / name (e.g. fishing_index)",
            "hint": "registered_tool_name (or tool_name / name) must match a tool implemented in a .py file under AGENT_TOOLS_EXTRA_DIR.",
        },
        ensure_ascii=False,
    )


def reject_update_tool_confused_arguments(arguments: dict[str, Any]) -> str | None:
    """Return error JSON if args look like create_tool/replace_tool; else None."""
    if arguments.get("old_string") is not None:
        return None
    if arguments.get("source") is not None:
        return json.dumps(
            {
                "ok": False,
                "error": "update_tool patches with old_string/new_string, not source",
                "use_instead": "replace_tool with full source, or create_tool for codegen",
            },
            ensure_ascii=False,
        )
    for key, owner in (
        ("overwrite", "create_tool (or replace_tool when replacing whole file)"),
        ("TOOL_DESCRIPTION", "create_tool when generating a new module without source"),
    ):
        if arguments.get(key) is not None:
            return json.dumps(
                {
                    "ok": False,
                    "error": f"update_tool does not accept {key!r} — that belongs on {owner}",
                    "hint": "After read_tool: call update_tool with old_string (exact snippet) and new_string.",
                },
                ensure_ascii=False,
            )
    return None


def reject_replace_tool_confused_arguments(arguments: dict[str, Any]) -> str | None:
    if arguments.get("old_string") is not None or arguments.get("new_string") is not None:
        return json.dumps(
            {
                "ok": False,
                "error": "replace_tool replaces the entire file; it does not use old_string/new_string",
                "use_instead": "update_tool for substring patches",
            },
            ensure_ascii=False,
        )
    if arguments.get("overwrite") is not None:
        return json.dumps(
            {
                "ok": False,
                "error": "replace_tool always overwrites the whole file; there is no overwrite flag",
                "hint": "Pass filename (or registered_tool_name / tool_name / name) and full source only.",
            },
            ensure_ascii=False,
        )
    return None


def backup_extra_tool_before_write(dest: Path) -> str | None:
    """
    If enabled, copy the existing extra-tool file into ``AGENT_TOOLS_BACKUP_DIR`` (or
    ``AGENT_DATA_DIR/tool_backups``) with a UTC timestamp prefix before overwriting.
    """
    if not config.TOOLS_BACKUP_ENABLED:
        return None
    if not dest.is_file():
        return None
    bdir = config.tools_backup_directory()
    try:
        bdir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("tool_backups: mkdir %s failed: %s", bdir, e)
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = bdir / f"{ts}_{dest.name}"
    try:
        shutil.copy2(dest, target)
        logger.info("tool_backups: saved previous %s -> %s", dest, target)
        return str(target)
    except OSError as e:
        logger.warning("tool_backups: copy failed: %s", e)
        return None


def tool_write_extra_for_digest(backup_path: str | None) -> dict[str, Any] | None:
    if not backup_path:
        return None
    return {
        "backup_previous": backup_path,
        "rollback_hint": (
            "Previous revision saved before write. Restore: copy the backup file over the live module in "
            "AGENT_TOOLS_EXTRA_DIR, then POST /v1/admin/reload-tools — or use replace_tool with source read from the backup."
        ),
    }


def digest_reload_response(
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
    allow = config.tools_allowed_sha256()
    if allow is not None and digest not in allow:
        out: dict[str, Any] = {
            "ok": True,
            "written": fn,
            "path": str(dest),
            "sha256": digest,
            "reload": "pending",
            "codegen": codegen,
            "warning": (
                "AGENT_TOOLS_ALLOWED_SHA256 is set — file NOT loaded until operator adds sha256 "
                "to env and POST /v1/admin/reload-tools or restarts."
            ),
        }
        if extra:
            out.update(extra)
        return json.dumps(out, ensure_ascii=False)
    try:
        reload_registry(scope="all")
    except Exception as e:
        logger.exception("reload after tool module change failed")
        out = {
            "ok": True,
            "written": fn,
            "path": str(dest),
            "sha256": digest,
            "reload": "failed",
            "error": str(e),
            "codegen": codegen,
            "hint": "POST /v1/admin/reload-tools or restart",
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
        "tool_file_entries": len(
            [m for m in reg.tools_meta if "file:" in str(m.get("source", ""))]
        ),
        "hint": "Use list_available_tools; read_tool, update_tool (patch), or replace_tool (full file).",
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


def validate_module_text(text: str, fn: str, *, codegen: bool) -> str | None:
    _ = codegen
    if len(text.encode("utf-8")) > config.CREATE_TOOL_MAX_BYTES:
        return (
            f"source exceeds AGENT_CREATE_TOOL_MAX_BYTES ({config.CREATE_TOOL_MAX_BYTES}); "
            "raise limit or split the tool."
        )
    try:
        compile(text, fn, "exec")
    except SyntaxError as e:
        return f"compile failed: {e}"
    ast_err = tool_authoring.validate_tool_source(text)
    if ast_err:
        return ast_err
    return tool_authoring.validate_tool_registry_exports(text)


def extract_python_from_llm(text: str) -> str:
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


def probe_block_succeeded(test_tool_block: Any) -> bool:
    if not isinstance(test_tool_block, dict):
        return False
    raw = test_tool_block.get("result")
    if not isinstance(raw, str):
        return False
    if "unknown tool" in raw.lower():
        return False
    try:
        o = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if isinstance(o, dict) and o.get("ok") is False:
        return False
    return True


def retry_hint_from_response(out: dict[str, Any]) -> tuple[bool, str]:
    if out.get("ok") is not True:
        return False, ""
    if out.get("reload") != "ok":
        return False, ""
    tt = out.get("test_tool")
    if not isinstance(tt, dict):
        return False, ""
    if probe_block_succeeded(tt):
        return False, ""
    raw = tt.get("result")
    hint = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    return True, hint[:8000]


def ollama_generate_module(
    *,
    registered_tool_function_name: str,
    display_hint: str,
    extra_TOOL_DESCRIPTION: str,
    repair_context: str | None = None,
) -> tuple[str | None, str | None]:
    system = (
        "You output ONE complete Python 3.11 module only. No markdown fences. No prose before or after.\n\n"
        "The module MUST:\n"
        "- start with: from __future__ import annotations\n"
        "- import json\n"
        "- from typing import Any, Callable\n"
        '- set __version__ = "0.1.0"\n'
        f'- set TOOL_ID = "{registered_tool_function_name}"\n'
        f"- define def {registered_tool_function_name}(arguments: dict[str, Any]) -> str that returns json.dumps(...) "
        "with UTF-8-safe strings\n"
        f'- HANDLERS = {{"{registered_tool_function_name}": {registered_tool_function_name}}}\n'
        "- TOOLS must be a list with EXACTLY this nesting (name goes INSIDE \"function\", never at top level):\n"
        "TOOLS = [\n"
        "    {\n"
        '        "type": "function",\n'
        '        "function": {\n'
        f'            "name": "{registered_tool_function_name}",\n'
        '            "TOOL_DESCRIPTION": "…",\n'
        '            "parameters": {\n'
        '                "type": "object",\n'
        '                "properties": { ... },\n'
        '                "required": [],\n'
        "            },\n"
        "        },\n"
        "    },\n"
        "]\n\n"
        "Rules:\n"
        f"- Exactly one TOOLS entry; HANDLERS has exactly one key \"{registered_tool_function_name}\".\n"
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
            "- No network: implement deterministic heuristics from tool arguments only; state that in the TOOL_DESCRIPTION.\n"
            "- No subprocess, os.system, eval/exec/__import__, no httpx/urllib for HTTP.\n"
        )
    user = (
        f"Implement a tool for this short name / idea: {display_hint}\n"
        f"Registered tool function name (required, already chosen): {registered_tool_function_name}\n"
        f"Extra instructions: {extra_TOOL_DESCRIPTION or '(none)'}\n"
    )
    if repair_context:
        user += (
            "\n\n---\nPrevious module failed validation or the automatic test call. "
            "Output one full corrected module (same registered tool function name). Context:\n"
            + repair_context.strip()
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
    raw = extract_python_from_llm(content)
    if not re.search(r"\bHANDLERS\b", raw) or not re.search(r"\bTOOLS\b", raw):
        return None, "codegen: response does not look like a tool module"
    return raw, None
