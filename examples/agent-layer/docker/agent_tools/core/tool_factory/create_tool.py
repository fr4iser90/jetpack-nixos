"""Create extra tools (full ``source`` or Ollama codegen). See sibling modules for list/read/update/rename."""

from __future__ import annotations

import json
from typing import Any, Callable

from app import config
from app import tool_authoring

from agent_tools.core.tool_factory._tool_factory_common import (
    backup_extra_tool_before_write,
    coerce_test_args,
    digest_reload_response,
    extra_root_or_error,
    ollama_generate_module,
    retry_hint_from_response,
    tool_write_extra_for_digest,
    validate_module_text,
)

__version__ = "1.3.2"
TOOL_ID = "create_tool"
TOOL_DOMAIN = "tool_factory"
TOOL_TRIGGERS = (
    "create_tool",
    "create tool",
    "new tool",
    "codegen",
    "generate tool",
    "dynamic tool",
    "plugin",
    "extra tool",
    "agent_tools",
    # Exact tool ids only — avoid vague words (otherwise the whole category matches too often).
    "update_tool",
    "read_tool",
    "replace_tool",
    "rename_tool",
)
TOOL_LABEL = "Tool factory"
TOOL_DESCRIPTION = (
    "Create, list, read, patch, replace, and rename dynamic .py tools under AGENT_TOOLS_EXTRA_DIR."
)

# Models often send garbage in ``source`` (e.g. "module_name") and put real code in ``source_content``.
_BOGUS_SOURCE_LITERALS = frozenset(
    {
        "",
        "module_name",
        "placeholder",
        "none",
        "n/a",
        "string",
        "python",
        "code",
        "source",
        "todo",
    }
)


def _unwrap_triple_quoted_module(raw: str) -> str:
    """
    Models often paste the whole module as one triple-quoted string (invalid pattern: code only exists
    inside a string literal). If the file is essentially ``''' ... real code ... '''``, return the inner text.
    """
    t = raw.strip()
    if len(t) < 10:
        return raw
    for quote in ("'''", '"""'):
        if not t.startswith(quote):
            continue
        end = t.rfind(quote)
        if end <= 3:
            continue
        inner = t[len(quote) : end].strip()
        low = inner.lower()
        if not inner:
            continue
        if (
            "def " in inner
            or "import " in inner
            or "tools" in low
            or "handlers" in low
        ):
            return inner
    return raw


def _strip_markdown_fenced_python(raw: str) -> str:
    t = raw.strip()
    if not t.startswith("```"):
        return t
    lines = t.split("\n")
    body: list[str] = []
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "```":
            break
        body.append(line)
    return "\n".join(body).strip()


def _effective_source_text(arguments: dict[str, Any]) -> tuple[str, str | None]:
    """
    Return (source_text, note). If primary ``source`` is a placeholder, ignore it and try
    ``source_content`` / ``code`` / ``body``. ``note`` is a short server hint for the model when we fixed args.
    """
    raw = arguments.get("source")
    primary = str(raw).strip() if raw is not None else ""
    pl = primary.strip().lower()
    use_primary = bool(primary) and pl not in _BOGUS_SOURCE_LITERALS
    if use_primary and len(primary) < 48 and "\n" not in primary and "tools" not in pl:
        # single-token junk like "module_name" without matching literals set (future-proof)
        if not primary.startswith(("import ", "from ", '"""', "'''")):
            use_primary = False
    if use_primary:
        return primary, None

    for key in ("source_content", "code", "body", "python_source"):
        alt = arguments.get(key)
        if alt is None:
            continue
        text = _strip_markdown_fenced_python(str(alt).strip())
        if text:
            hint = (
                f"Used {key!r} as module source (primary `source` was empty or a placeholder). "
                "Next time pass full Python in `source`, or omit `source` for codegen."
            )
            return text, hint
    return "", (
        "Ignored placeholder `source` (e.g. module_name). "
        "For codegen: omit `source` and set `tool_name` + `TOOL_DESCRIPTION`. "
        "For paste: put the full module in `source` or `source_content`."
        if primary
        else None
    )


def create_tool(arguments: dict[str, Any]) -> str:
    root, err = extra_root_or_error()
    if err:
        return err
    assert root is not None
    extra_root = root

    source_str, source_note = _effective_source_text(dict(arguments or {}))
    _before_unwrap = source_str
    source_str = _unwrap_triple_quoted_module(source_str)
    if source_str != _before_unwrap:
        uhint = (
            "Removed outer '''...''' / \"\"\"...\"\"\" wrapper — the module must be normal Python lines, "
            "not one giant string literal."
        )
        source_note = f"{source_note} {uhint}" if source_note else uhint
    codegen = not source_str
    codegen_model: str | None = None

    if codegen:
        hint = str(arguments.get("tool_name") or arguments.get("name") or "").strip()
        if not hint:
            # Models often pass only filename + TOOL_DESCRIPTION for codegen; derive hint from basename.
            raw_fn = str(arguments.get("filename") or "").strip()
            if raw_fn:
                base = raw_fn.replace("\\", "/").rsplit("/", 1)[-1]
                if base.lower().endswith(".py"):
                    base = base[:-3]
                hint = base.strip()
        if not hint:
            return json.dumps(
                {
                    "ok": False,
                    "error": (
                        "Either pass source+filename, or omit source and set tool_name (or name), "
                        "or set filename (e.g. my_tool.py) so the server can generate code via Ollama "
                        "(AGENT_CREATE_TOOL_CODEGEN_MODEL)."
                    ),
                },
                ensure_ascii=False,
            )
        snake, terr = tool_authoring.slugify_registered_tool_function_name(hint)
        if terr:
            return json.dumps({"ok": False, "error": terr}, ensure_ascii=False)
        fn, fe = tool_authoring.sanitize_tool_filename(f"{snake}.py")
        if fe or not fn:
            return json.dumps({"ok": False, "error": fe or "invalid filename"}, ensure_ascii=False)
        extra_desc = str(arguments.get("TOOL_DESCRIPTION") or "").strip()
        codegen_model = config.CREATE_TOOL_CODEGEN_MODEL
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

        max_at = config.CREATE_TOOL_CODEGEN_MAX_ATTEMPTS
        fix_hint: str | None = None
        last_body: dict[str, Any] | None = None
        test_args = coerce_test_args(arguments.get("test_arguments"))

        for attempt in range(max_at):
            text, gen_err = ollama_generate_module(
                registered_tool_function_name=snake,
                display_hint=hint,
                extra_TOOL_DESCRIPTION=extra_desc,
                repair_context=fix_hint,
            )
            if gen_err:
                return json.dumps(
                    {
                        "ok": False,
                        "error": gen_err,
                        "codegen": True,
                        "model": codegen_model,
                        "codegen_attempts": attempt + 1,
                        "codegen_max_attempts": max_at,
                    },
                    ensure_ascii=False,
                )

            val_err = validate_module_text(text, fn, codegen=True)
            if val_err:
                fix_hint = f"Validation failed: {val_err}"
                if attempt >= max_at - 1:
                    return json.dumps(
                        {
                            "ok": False,
                            "error": val_err,
                            "codegen": True,
                            "model": codegen_model,
                            "codegen_attempts": attempt + 1,
                            "codegen_max_attempts": max_at,
                        },
                        ensure_ascii=False,
                    )
                continue

            backup_path = backup_extra_tool_before_write(dest) if dest.is_file() else None
            try:
                dest.write_text(text, encoding="utf-8", newline="\n")
            except OSError as e:
                return json.dumps({"ok": False, "error": f"write failed: {e}"}, ensure_ascii=False)

            body_str = digest_reload_response(
                fn,
                dest,
                codegen=True,
                codegen_model=codegen_model,
                test_tool_name=snake,
                test_arguments=test_args,
                extra=tool_write_extra_for_digest(backup_path),
            )
            out = json.loads(body_str)
            out["codegen_attempts"] = attempt + 1
            out["codegen_max_attempts"] = max_at
            retry, rhint = retry_hint_from_response(out)
            if not retry:
                if source_note:
                    out = dict(out)
                    out["create_tool_arg_hint"] = source_note
                return json.dumps(out, ensure_ascii=False)
            fix_hint = (
                rhint
                + "\n\nUse defaults for missing arguments (arguments.get with fallbacks); "
                "never compare None to numbers."
            )
            last_body = out

        if last_body is not None:
            lb = dict(last_body)
            lb["codegen_attempts_exhausted"] = True
            if source_note:
                lb["create_tool_arg_hint"] = source_note
            return json.dumps(lb, ensure_ascii=False)
        return json.dumps(
            {
                "ok": False,
                "error": "codegen probe retries exhausted",
                "codegen": True,
                "model": codegen_model,
                "codegen_max_attempts": max_at,
            },
            ensure_ascii=False,
        )

    fn, fn_err = tool_authoring.sanitize_tool_filename(str(arguments.get("filename") or ""))
    if fn_err:
        return json.dumps({"ok": False, "error": fn_err}, ensure_ascii=False)
    text = source_str

    val_err = validate_module_text(text, fn, codegen=False)
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

    backup_path = backup_extra_tool_before_write(dest) if dest.is_file() else None
    try:
        dest.write_text(text, encoding="utf-8", newline="\n")
    except OSError as e:
        return json.dumps({"ok": False, "error": f"write failed: {e}"}, ensure_ascii=False)

    body_str = digest_reload_response(
        fn,
        dest,
        codegen=codegen,
        codegen_model=codegen_model,
        test_tool_name=None,
        test_arguments=coerce_test_args(arguments.get("test_arguments")),
        extra=tool_write_extra_for_digest(backup_path),
    )
    if source_note:
        try:
            out = json.loads(body_str)
        except json.JSONDecodeError:
            return body_str
        if isinstance(out, dict):
            out["create_tool_arg_hint"] = source_note
            return json.dumps(out, ensure_ascii=False)
    return body_str


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "create_tool": create_tool,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_tool",
            "TOOL_DESCRIPTION": (
                "Create a new tool module under AGENT_TOOLS_EXTRA_DIR. "
                "Codegen (preferred for small models): OMIT `source` entirely; set `tool_name` or `filename` (.py) "
                "and `TOOL_DESCRIPTION` (say: use invoke_registered_tool openweather_forecast). Server runs Ollama. "
                "Paste mode: raw Python module — TOOLS must be a **list** of {\"type\":\"function\",\"function\":{...}} "
                "entries; HANDLERS is a **dict** mapping the same function **name** strings to callables. "
                "Do not wrap the file in '''...''' string literals; do not use TOOLS={\"fn\": func}. "
                "Handler signature: def my_tool(arguments: dict) -> str returning json.dumps(...). "
                "Never set `source` to words like module_name — use codegen without source instead. "
                "`source_content` accepted like `source` (markdown ``` ok). "
                "Inside plugins: from app.plugin_invoke import invoke_registered_tool — "
                'invoke_registered_tool returns a JSON string (use json.loads), not a list: '
                'raw = invoke_registered_tool(\"openweather_forecast\", {\"location\": \"...\"}). '
                "Related: list_tools, read_tool, replace_tool, rename_tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "Codegen: short idea (e.g. fishingIndex) → snake_case file + tool name.",
                    },
                    "name": {"type": "string", "TOOL_DESCRIPTION": "Alias for tool_name (codegen)."},
                    "TOOL_DESCRIPTION": {
                        "type": "string",
                        "TOOL_DESCRIPTION": (
                            "Codegen: domain hints (Beißindex, Fenster). "
                            "Say to use invoke_registered_tool openweather_forecast / openweather_current inside generated code."
                        ),
                    },
                    "filename": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "With source: target file. Codegen without source: basename used as tool name hint (e.g. bite_index.py).",
                    },
                    "source": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "Full module UTF-8 text; omit entirely to trigger codegen (do not send module_name).",
                    },
                    "source_content": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "Same as source if the model wrongly split fields; optional markdown code fence.",
                    },
                    "overwrite": {"type": "boolean"},
                    "test_arguments": {
                        "type": "object",
                        "TOOL_DESCRIPTION": "Optional probe args after codegen reload.",
                    },
                },
            },
        },
    },
]
