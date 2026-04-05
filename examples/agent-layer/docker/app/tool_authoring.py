"""Static checks for ``create_tool``-submitted tool source (syntax + AST). Not a sandbox."""

from __future__ import annotations

import ast
import importlib.util
import os
import re
import sys
import tempfile
import uuid
from typing import Any

_FILENAME_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]*\.py\Z")

# Top-level import roots we reject (extend with care).
_FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "subprocess",
        "multiprocessing",
        "ctypes",
        "pickle",
        "_pickle",
        "shelve",
        "socket",
        "ssl",
        "pty",
        "resource",
        "importlib",
    }
)

_FORBIDDEN_FROM_OS_NAMES = frozenset(
    {
        "system",
        "popen",
        "posix_spawn",
        "spawnv",
        "spawnvp",
        "spawnl",
        "spawnlp",
        "execl",
        "execle",
        "execlp",
        "execv",
        "execve",
        "execvp",
        "execvpe",
    }
)


def slugify_registered_tool_function_name(raw: str) -> tuple[str | None, str | None]:
    """
    Map a short hint like ``fishingIndex`` → ``fishing_index`` for filename + registered tool function name.
    """
    s = (raw or "").strip()
    if not s:
        return None, "tool_name is required when source is omitted"
    s = re.sub(r"\s+", "_", s)
    s = s.replace("-", "_")
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    s = s.lower()
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        return None, "tool_name must contain letters or digits"
    if s[0].isdigit():
        s = f"t_{s}"
    if not re.fullmatch(r"[a-z][a-z0-9_]*", s):
        return (
            None,
            "tool_name must yield a valid identifier (letters, digits, underscore; start with letter)",
        )
    return s, None


def sanitize_tool_filename(name: str) -> tuple[str | None, str | None]:
    s = (name or "").strip()
    if not s:
        return None, "filename is required"
    if "/" in s or "\\" in s or s.startswith("."):
        return None, "filename must be a single basename (no path, no leading dot)"
    if not _FILENAME_RE.fullmatch(s):
        return (
            None,
            "filename must match [A-Za-z0-9][A-Za-z0-9_-]*.py",
        )
    return s, None


def _import_root(name: str) -> str:
    return (name or "").split(".", 1)[0]


def _module_assigns_tools_handlers(tree: ast.Module) -> tuple[bool, bool]:
    has_tools = False
    has_handlers = False
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    if t.id == "TOOLS":
                        has_tools = True
                    elif t.id == "HANDLERS":
                        has_handlers = True
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "TOOLS":
                has_tools = True
            elif node.target.id == "HANDLERS":
                has_handlers = True
    return has_tools, has_handlers


class _ToolAstChecker(ast.NodeVisitor):
    def __init__(self) -> None:
        self.error: str | None = None

    def _set(self, msg: str) -> None:
        if self.error is None:
            self.error = msg

    def visit_Import(self, node: ast.Import) -> Any:
        for alias in node.names:
            root = _import_root(alias.name)
            if root in _FORBIDDEN_IMPORT_ROOTS:
                self._set(f"forbidden import: {alias.name}")
                return
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        if node.module:
            root = _import_root(node.module)
            if root in _FORBIDDEN_IMPORT_ROOTS:
                self._set(f"forbidden import from: {node.module}")
                return
            if node.module == "os":
                for a in node.names:
                    if a.name == "*":
                        self._set("forbidden: from os import *")
                        return
                    if a.name in _FORBIDDEN_FROM_OS_NAMES:
                        self._set(f"forbidden import from os: {a.name}")
                        return
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> Any:
        fn = node.func
        if isinstance(fn, ast.Name):
            if fn.id in ("eval", "exec", "compile", "__import__"):
                self._set(f"forbidden call: {fn.id}()")
                return
        if isinstance(fn, ast.Attribute):
            if fn.attr in _FORBIDDEN_FROM_OS_NAMES and isinstance(fn.value, ast.Name):
                if fn.value.id == "os":
                    self._set(f"forbidden call: os.{fn.attr}")
                    return
            if isinstance(fn.value, ast.Name) and fn.value.id == "subprocess":
                self._set("forbidden use of subprocess module")
                return
        self.generic_visit(node)


def validate_tool_source(source: str) -> str | None:
    """
    Return an error string if validation fails, else None.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return f"syntax error: {e}"

    if not isinstance(tree, ast.Module):
        return "invalid ast"

    has_t, has_h = _module_assigns_tools_handlers(tree)
    if not has_t or not has_h:
        return "module must define top-level TOOLS (list) and HANDLERS (dict) assignments"

    checker = _ToolAstChecker()
    checker.visit(tree)
    return checker.error


def validate_registry_tool_exports(mod: Any) -> str | None:
    """
    Match the expectations of ``ToolRegistry._register_module``: each ``TOOLS`` entry must be
    ``{\"type\": \"function\", \"function\": {\"name\": ..., \"TOOL_DESCRIPTION\": ..., \"parameters\": dict}}``.
    Models often wrongly put ``name`` at the top level of the tool dict — that is rejected here.
    """
    tools = getattr(mod, "TOOLS", None)
    handlers = getattr(mod, "HANDLERS", None)
    if isinstance(tools, dict):
        return (
            "TOOLS must be a **list** of Chat Completions tool entries "
            '[{"type":"function","function":{"name":"my_tool","TOOL_DESCRIPTION":"...","parameters":{...}}}, ...], '
            "not a dict. Use HANDLERS = {\"my_tool\": callable} for name → function. "
            "See docker/extra_tools/sample_echo.py or call get_tool_help(\"create_tool\")."
        )
    if not isinstance(tools, list) or not tools:
        return "TOOLS must be a non-empty list"
    if not isinstance(handlers, dict) or not handlers:
        return "HANDLERS must be a non-empty dict"

    tool_names: list[str] = []
    for i, spec in enumerate(tools):
        if not isinstance(spec, dict):
            return f"TOOLS[{i}] must be a dict"
        if spec.get("type") != "function":
            return f'TOOLS[{i}] must have "type": "function"'
        fn = spec.get("function")
        if not isinstance(fn, dict):
            return (
                f"TOOLS[{i}] must nest the function object under key \"function\" (Chat tools[] shape): "
                '{{"type": "function", "function": {{"name": "...", "TOOL_DESCRIPTION": "...", '
                '"parameters": {{...}}}}}} — not name at the top level of TOOLS[{i}].'
            )
        name = fn.get("name")
        if not isinstance(name, str) or not name.strip():
            return (
                f"TOOLS[{i}].function must have a non-empty string \"name\" "
                f'(inside the "function" object, not at the root of TOOLS[{i}])'
            )
        params = fn.get("parameters")
        if not isinstance(params, dict):
            return f"TOOLS[{i}].function.parameters must be a dict (JSON Schema object)"
        tool_names.append(name.strip())

    if len(tool_names) != len(set(tool_names)):
        return "duplicate function.name values in TOOLS — each name must appear once"

    valid: list[str] = []
    for name in tool_names:
        h = handlers.get(name)
        if not callable(h):
            return f'HANDLERS must contain a callable for tool name "{name}"'
        valid.append(name)

    if not valid:
        return "no tool names could be matched to HANDLERS callables"

    for declared in handlers:
        if declared not in tool_names:
            return (
                f'HANDLERS contains key "{declared}" with no matching TOOLS[].function.name — '
                "remove it or add a TOOLS entry."
            )
    return None


def validate_tool_registry_exports(source: str) -> str | None:
    """
    Load *source* in a temporary file (unique module name), run ``validate_registry_tool_exports``,
    then unload. Catches invalid TOOLS shape before writing to ``AGENT_TOOLS_EXTRA_DIR``.
    """
    mod_name = f"_agent_tool_validate_{uuid.uuid4().hex}"
    path: str | None = None
    try:
        fd, path = tempfile.mkstemp(suffix=".py", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(source)
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            return "internal error: could not build module spec"
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        return validate_registry_tool_exports(mod)
    except Exception as e:
        return f"failed to load tool for validation: {e}"
    finally:
        sys.modules.pop(mod_name, None)
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass
