"""Discover, register, and reload tool plugins (built-in package + optional directory)."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import logging
import sys
import threading
import pkgutil
from pathlib import Path
from typing import Any, Callable

from . import config
from . import db

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], str]


class ToolRegistry:
    """
    Built-in plugins (``app.plugins``) and optional directory plugins are kept separate.
    ``reload_extra_only`` refreshes only the directory layer; built-in modules stay loaded.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._builtin_handlers: dict[str, Handler] = {}
        self._builtin_openai_tools: list[dict[str, Any]] = []
        self._builtin_meta: list[dict[str, Any]] = []
        self._extra_handlers: dict[str, Handler] = {}
        self._extra_openai_tools: list[dict[str, Any]] = []
        self._extra_meta: list[dict[str, Any]] = []
        self._handlers: dict[str, Handler] = {}
        self._openai_tools: list[dict[str, Any]] = []
        self._plugins_meta: list[dict[str, Any]] = []

    def load_all(self) -> None:
        with self._lock:
            self._clear_storage()
            self._purge_builtin_plugin_modules()
            self._purge_user_plugin_modules()
            self._load_builtin_into_storage()
            self._load_extra_into_storage()
            self._merge()

    def reload_extra_only(self) -> None:
        with self._lock:
            self._purge_user_plugin_modules()
            self._extra_handlers.clear()
            self._extra_openai_tools.clear()
            self._extra_meta.clear()
            self._load_extra_into_storage()
            self._merge()

    def _clear_storage(self) -> None:
        self._builtin_handlers.clear()
        self._builtin_openai_tools.clear()
        self._builtin_meta.clear()
        self._extra_handlers.clear()
        self._extra_openai_tools.clear()
        self._extra_meta.clear()
        self._handlers.clear()
        self._openai_tools.clear()
        self._plugins_meta.clear()

    def _purge_builtin_plugin_modules(self) -> None:
        import app.plugins as plugins_pkg

        root = plugins_pkg.__name__
        prefix = root + "."
        for key in list(sys.modules):
            if key.startswith(prefix) and key != root:
                del sys.modules[key]

    def _purge_user_plugin_modules(self) -> None:
        for key in list(sys.modules):
            if key.startswith("agent_user_plugin_"):
                del sys.modules[key]

    def _load_builtin_into_storage(self) -> None:
        import app.plugins as plugins_pkg

        for _finder, name, ispkg in pkgutil.iter_modules(
            plugins_pkg.__path__, plugins_pkg.__name__ + "."
        ):
            short = name.rsplit(".", 1)[-1]
            if short.startswith("_"):
                continue
            if ispkg:
                continue
            try:
                mod = importlib.import_module(name)
            except Exception:
                logger.exception("failed to import built-in plugin %s", name)
                continue
            self._register_module(
                mod,
                source=f"builtin:{name}",
                handlers=self._builtin_handlers,
                tools=self._builtin_openai_tools,
                meta=self._builtin_meta,
            )

    def _load_extra_into_storage(self) -> None:
        raw = (config.PLUGINS_EXTRA_DIR or "").strip()
        if not raw:
            return
        root = Path(raw)
        if not root.is_dir():
            logger.warning("AGENT_PLUGINS_EXTRA_DIR is not a directory: %s", root)
            return
        allow = config.plugins_allowed_sha256()
        for path in sorted(root.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                data = path.read_bytes()
            except OSError:
                logger.exception("cannot read plugin file %s", path)
                continue
            digest = hashlib.sha256(data).hexdigest()
            if allow is not None and digest not in allow:
                logger.error(
                    "rejecting extra plugin %s: sha256 %s not in AGENT_PLUGINS_ALLOWED_SHA256",
                    path,
                    digest,
                )
                continue
            mod_name = f"agent_user_plugin_{path.stem}"
            try:
                spec = importlib.util.spec_from_file_location(mod_name, path)
                if spec is None or spec.loader is None:
                    logger.error("cannot load plugin spec: %s", path)
                    continue
                mod = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = mod
                spec.loader.exec_module(mod)
            except Exception:
                logger.exception("failed to load extra plugin %s", path)
                continue
            self._register_module(
                mod,
                source=f"file:{path}",
                handlers=self._extra_handlers,
                tools=self._extra_openai_tools,
                meta=self._extra_meta,
                file_sha256=digest,
            )

    def _register_module(
        self,
        mod: Any,
        source: str,
        handlers: dict[str, Handler],
        tools: list[dict[str, Any]],
        meta: list[dict[str, Any]],
        *,
        file_sha256: str | None = None,
    ) -> None:
        mod_tools = getattr(mod, "TOOLS", None)
        mod_handlers = getattr(mod, "HANDLERS", None)
        if mod_tools is None and mod_handlers is None:
            return
        if not isinstance(mod_tools, list) or not isinstance(mod_handlers, dict):
            logger.error("invalid plugin exports (need TOOLS list and HANDLERS dict): %s", source)
            return

        pid = getattr(mod, "PLUGIN_ID", None) or getattr(mod, "__name__", "unknown")
        ver = str(getattr(mod, "__version__", "0"))
        tool_names: list[str] = []
        pending_handlers: dict[str, Handler] = {}
        pending_specs: list[dict[str, Any]] = []

        for spec in mod_tools:
            if not isinstance(spec, dict):
                continue
            fn = spec.get("function") or {}
            name = fn.get("name")
            if not name:
                logger.warning("skip tool without name in %s", source)
                continue
            if name in handlers or name in pending_handlers:
                raise ValueError(f"duplicate tool name '{name}' while loading {source}")
            handler = mod_handlers.get(name)
            if not callable(handler):
                raise ValueError(f"tool '{name}' has no callable handler in {source}")
            pending_handlers[name] = handler  # type: ignore[assignment]
            pending_specs.append(spec)
            tool_names.append(name)

        handlers.update(pending_handlers)
        tools.extend(pending_specs)

        if not tool_names:
            if mod_handlers:
                logger.warning(
                    "plugin %s exports HANDLERS but no valid TOOLS entries",
                    source,
                )
            return

        for declared in mod_handlers:
            if declared not in tool_names:
                logger.warning(
                    "plugin %s declares handler %r without matching TOOLS entry",
                    source,
                    declared,
                )

        entry: dict[str, Any] = {
            "id": pid,
            "version": ver,
            "source": source,
            "tools": tool_names,
        }
        if file_sha256 is not None:
            entry["sha256"] = file_sha256
        meta.append(entry)
        logger.info("loaded plugin %s v%s (%d tools) [%s]", pid, ver, len(tool_names), source)

    def _merge(self) -> None:
        overlap = set(self._builtin_handlers) & set(self._extra_handlers)
        if overlap:
            raise ValueError(
                f"extra plugins define tool names that already exist as built-ins: {sorted(overlap)}"
            )
        self._handlers = {**self._builtin_handlers, **self._extra_handlers}
        self._openai_tools = list(self._builtin_openai_tools) + list(self._extra_openai_tools)
        self._plugins_meta = list(self._builtin_meta) + list(self._extra_meta)

    @property
    def openai_tools(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._openai_tools)

    @property
    def plugins_meta(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._plugins_meta)

    def run_tool(self, name: str, arguments: dict[str, Any]) -> str:
        with self._lock:
            handler = self._handlers.get(name)
        if not handler:
            return json.dumps({"ok": False, "error": f"unknown tool: {name}"})
        ok = True
        try:
            out = handler(dict(arguments or {}))
            payload = json.loads(out) if out else {}
            if isinstance(payload, dict) and payload.get("ok") is False:
                ok = False
        except Exception as e:
            ok = False
            out = json.dumps({"ok": False, "error": str(e)})
        db.log_tool_invocation(name, dict(arguments or {}), out, ok)
        return out


_registry: ToolRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> ToolRegistry:
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = ToolRegistry()
            _registry.load_all()
        return _registry


def reload_registry(scope: str = "all") -> ToolRegistry:
    global _registry
    s = (scope or "all").strip().lower()
    if s not in ("all", "extra"):
        raise ValueError("scope must be 'all' or 'extra'")

    with _registry_lock:
        if s == "extra":
            if _registry is None:
                reg = ToolRegistry()
                reg.load_all()
                _registry = reg
                return reg
            _registry.reload_extra_only()
            return _registry

        candidate = ToolRegistry()
        candidate.load_all()
        _registry = candidate
        return candidate
