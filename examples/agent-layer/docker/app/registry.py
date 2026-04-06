"""Load tool tools only from configured directories (``*.py`` files); no package hardcoding."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import re
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from . import config
from . import db

logger = logging.getLogger(__name__)

# First path segment under each tool scan root → ``tools_meta[].layer`` (optional).
KNOWN_TOOL_LAYERS = frozenset({"core", "knowledge", "external", "productivity", "domains"})


class _RouterAccum:
    """Mutable state while scanning modules for router metadata (``TOOL_DOMAIN``, triggers, …)."""

    __slots__ = ("cat_TOOL_DESCRIPTION", "cat_TOOL_LABEL", "order", "tools", "TOOL_TRIGGERS")

    def __init__(self) -> None:
        self.tools: dict[str, set[str]] = {}
        self.TOOL_TRIGGERS: dict[str, set[str]] = {}
        self.order: list[str] = []
        self.cat_TOOL_LABEL: dict[str, str] = {}
        self.cat_TOOL_DESCRIPTION: dict[str, str] = {}

Handler = Callable[[dict[str, Any]], str]


def _path_under_or_equal(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def _iter_tool_py_files(root: Path) -> list[Path]:
    """All ``*.py`` under ``root`` (recursive), excluding ``__init__.py``, ``_*``, ``__pycache__``."""
    out: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        if path.name.startswith("_") or path.name == "__init__.py":
            continue
        out.append(path)
    return out


def _stable_module_slug(directory: Path, path: Path, dir_idx: int) -> str:
    """Unique import-safe suffix for ``spec_from_file_location`` (avoids stem collisions across subdirs)."""
    try:
        rel = path.resolve().relative_to(directory.resolve())
    except (ValueError, OSError):
        rel = Path(path.name)
    rel_no_suffix = rel.with_suffix("")
    parts = [re.sub(r"[^a-zA-Z0-9_]", "_", str(p)) for p in rel_no_suffix.parts]
    slug = "_".join(p for p in parts if p).strip("_") or "tool"
    if slug and slug[0].isdigit():
        slug = f"m_{slug}"
    return f"{dir_idx}_{slug}"


class ToolRegistry:
    """Scans ``AGENT_TOOL_DIRS`` or default ``tools`` + optional extra mount."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handlers: dict[str, Handler] = {}
        self._chat_tool_specs: list[dict[str, Any]] = []
        self._tools_meta: list[dict[str, Any]] = []
        self._router_cat_tools: dict[str, frozenset[str]] = {}
        self._router_cat_TOOL_TRIGGERS: dict[str, frozenset[str]] = {}
        self._router_cat_order: list[str] = []
        self._router_cat_TOOL_LABEL: dict[str, str] = {}
        self._router_cat_TOOL_DESCRIPTION: dict[str, str] = {}

    def load_all(self) -> None:
        with self._lock:
            self._clear_storage()
            self._purge_dynamic_tool_modules()
            acc_h: dict[str, Handler] = {}
            acc_tools: list[dict[str, Any]] = []
            acc_meta: list[dict[str, Any]] = []
            router = _RouterAccum()

            allow = config.tools_allowed_sha256()
            extra_raw = (config.TOOLS_EXTRA_DIR or "").strip()
            extra_root: Path | None = None
            if extra_raw:
                try:
                    extra_root = Path(extra_raw).expanduser().resolve()
                except OSError:
                    extra_root = Path(extra_raw).expanduser()

            dirs = config.tool_scan_directories()
            if not dirs:
                logger.warning("no tool directories to scan (set AGENT_TOOL_DIRS or ship tools)")

            for dir_idx, directory in enumerate(dirs):
                if not directory.is_dir():
                    logger.warning("skip missing tool directory: %s", directory)
                    continue
                for path in _iter_tool_py_files(directory):
                    try:
                        rel_to_root = path.resolve().relative_to(directory.resolve())
                    except (ValueError, OSError):
                        rel_to_root = Path(path.name)
                    layer_from_path: str | None = None
                    if rel_to_root.parts:
                        cand = rel_to_root.parts[0].lower()
                        if cand in KNOWN_TOOL_LAYERS:
                            layer_from_path = cand
                    try:
                        data = path.read_bytes()
                    except OSError:
                        logger.exception("cannot read tool file %s", path)
                        continue
                    digest = hashlib.sha256(data).hexdigest()
                    try:
                        path_r = path.resolve()
                    except OSError:
                        path_r = path
                    needs_sha = (
                        allow is not None
                        and extra_root is not None
                        and extra_root.is_dir()
                        and _path_under_or_equal(path_r, extra_root)
                    )
                    if needs_sha and digest not in allow:
                        logger.error(
                            "rejecting tool (not in AGENT_TOOLS_ALLOWED_SHA256): %s",
                            path,
                        )
                        continue
                    slug = _stable_module_slug(directory, path, dir_idx)
                    mod_name = f"agent_tool_{slug}"
                    try:
                        spec = importlib.util.spec_from_file_location(mod_name, path)
                        if spec is None or spec.loader is None:
                            logger.error("cannot load tool spec: %s", path)
                            continue
                        mod = importlib.util.module_from_spec(spec)
                        sys.modules[mod_name] = mod
                        spec.loader.exec_module(mod)
                    except Exception:
                        logger.exception("failed to load tool %s", path)
                        continue
                    self._register_module(
                        mod,
                        source=f"file:{path}",
                        handlers=acc_h,
                        tools=acc_tools,
                        meta=acc_meta,
                        file_sha256=digest,
                        router=router,
                        tool_layer=layer_from_path,
                    )

            self._handlers = acc_h
            self._chat_tool_specs = acc_tools
            self._tools_meta = acc_meta
            self._router_cat_tools = {k: frozenset(v) for k, v in router.tools.items()}
            self._router_cat_TOOL_TRIGGERS = {k: frozenset(v) for k, v in router.TOOL_TRIGGERS.items()}
            self._router_cat_order = list(router.order)
            self._router_cat_TOOL_LABEL = dict(router.cat_TOOL_LABEL)
            self._router_cat_TOOL_DESCRIPTION = dict(router.cat_TOOL_DESCRIPTION)

    def _clear_storage(self) -> None:
        self._handlers.clear()
        self._chat_tool_specs.clear()
        self._tools_meta.clear()
        self._router_cat_tools = {}
        self._router_cat_TOOL_TRIGGERS = {}
        self._router_cat_order = []
        self._router_cat_TOOL_LABEL = {}
        self._router_cat_TOOL_DESCRIPTION = {}

    def _purge_dynamic_tool_modules(self) -> None:
        for key in list(sys.modules):
            if key.startswith("agent_tool_"):
                del sys.modules[key]

    def _register_module(
        self,
        mod: Any,
        source: str,
        handlers: dict[str, Handler],
        tools: list[dict[str, Any]],
        meta: list[dict[str, Any]],
        *,
        file_sha256: str | None = None,
        router: _RouterAccum | None = None,
        tool_layer: str | None = None,
    ) -> None:
        mod_tools = getattr(mod, "TOOLS", None)
        mod_handlers = getattr(mod, "HANDLERS", None)
        if mod_tools is None and mod_handlers is None:
            return
        if mod_handlers is None:
            return
        if mod_tools is None:
            mod_tools = []
        if not isinstance(mod_tools, list) or not isinstance(mod_handlers, dict):
            logger.error(
                "invalid tool exports (need TOOLS list and HANDLERS dict): %s", source
            )
            return

        pid = getattr(mod, "TOOL_ID", None) or getattr(mod, "__name__", "unknown")
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
                continue
            handler = mod_handlers.get(name)
            if not callable(handler):
                logger.error(
                    "skip tool %r in %s: no callable handler in HANDLERS",
                    name,
                    source,
                )
                continue
            pending_handlers[name] = handler  # type: ignore[assignment]
            pending_specs.append(spec)
            tool_names.append(name)

        handlers.update(pending_handlers)
        tools.extend(pending_specs)

        if not tool_names:
            # Only cron workflows, no tools → DO NOT ADD TO TOOL REGISTRY
            logger.info(
                "skipping workflow %s v%s (%d handlers) - separate workflow registry will load this", pid, ver, len(mod_handlers)
            )
            return

        for declared in mod_handlers:
            if declared not in tool_names:
                logger.warning(
                    "tool %s declares handler %r without matching TOOLS entry",
                    source,
                    declared,
                )

        entry: dict[str, Any] = {
            "id": pid,
            "version": ver,
            "source": source,
            "tools": tool_names,
            "module": mod,
        }
        if file_sha256 is not None:
            entry["sha256"] = file_sha256
        if tool_layer is not None:
            entry["layer"] = tool_layer
        tags = getattr(mod, "TOOL_TAGS", None)
        if isinstance(tags, (list, tuple, frozenset, set)):
            tl = [str(x).strip() for x in tags if str(x).strip()]
            if tl:
                entry["tags"] = tl
        elif isinstance(tags, str) and tags.strip():
            entry["tags"] = [
                x.strip() for x in tags.replace(";", ",").split(",") if x.strip()
            ]
        dom = getattr(mod, "TOOL_DOMAIN", None)
        if isinstance(dom, str) and dom.strip():
            entry["domain"] = dom.strip().lower()
        req = getattr(mod, "TOOL_REQUIRES", None)
        if isinstance(req, (list, tuple, frozenset, set)):
            rl = [str(x).strip() for x in req if str(x).strip()]
            if rl:
                entry["requires"] = rl
        ptm = getattr(mod, "AGENT_TOOL_META_BY_NAME", None)
        if isinstance(ptm, dict) and ptm:
            per: dict[str, Any] = {}
            for k, v in ptm.items():
                if not isinstance(v, dict):
                    continue
                nk = str(k).strip()
                if not nk:
                    continue
                row: dict[str, Any] = {}
                r2 = v.get("requires")
                if isinstance(r2, (list, tuple)):
                    lr = [str(x).strip() for x in r2 if str(x).strip()]
                    if lr:
                        row["requires"] = lr
                t2 = v.get("tags")
                if isinstance(t2, (list, tuple)):
                    lt = [str(x).strip() for x in t2 if str(x).strip()]
                    if lt:
                        row["tags"] = lt
                if row:
                    per[nk] = row
            if per:
                entry["per_tool"] = per
        meta.append(entry)
        logger.info(
            "loaded tool %s v%s (%d tools) [%s]", pid, ver, len(tool_names), source
        )

        if router is not None and tool_names:
            rcat = getattr(mod, "TOOL_DOMAIN", None)
            if isinstance(rcat, str) and rcat.strip():
                key = rcat.strip().lower()
                if key not in router.order:
                    router.order.append(key)
                router.tools.setdefault(key, set()).update(tool_names)
                if key not in router.cat_TOOL_LABEL:
                    lab = getattr(mod, "TOOL_LABEL", None)
                    if isinstance(lab, str) and lab.strip():
                        router.cat_TOOL_LABEL[key] = lab.strip()
                if key not in router.cat_TOOL_DESCRIPTION:
                    cdesc = getattr(mod, "TOOL_DESCRIPTION", None)
                    if isinstance(cdesc, str) and cdesc.strip():
                        router.cat_TOOL_DESCRIPTION[key] = cdesc.strip()
                if "TOOL_TRIGGERS" in mod.__dict__:
                    tr = mod.TOOL_TRIGGERS
                    parts: list[str] = []
                    if isinstance(tr, str):
                        parts = [
                            x.strip().lower()
                            for x in tr.replace(";", ",").split(",")
                            if x.strip()
                        ]
                    elif isinstance(tr, (list, tuple, frozenset, set)):
                        parts = [str(x).strip().lower() for x in tr if str(x).strip()]
                    if parts:
                        router.TOOL_TRIGGERS.setdefault(key, set()).update(parts)
                else:
                    tid = str(pid).strip().lower()
                    if tid:
                        router.TOOL_TRIGGERS.setdefault(key, set()).add(tid)

    def router_tool_names_for_category(self, category: str) -> frozenset[str]:
        with self._lock:
            return self._router_cat_tools.get(category.strip().lower(), frozenset())

    def _router_category_order(self) -> list[str]:
        """Call with ``self._lock`` held."""
        known = frozenset(self._router_cat_tools.keys())
        order: list[str] = []
        seen: set[str] = set()
        for c in config.AGENT_TOOL_DOMAIN_ORDER:
            if c in known and c not in seen:
                order.append(c)
                seen.add(c)
        for c in self._router_cat_order:
            if c in known and c not in seen:
                order.append(c)
                seen.add(c)
        return order

    def list_router_categories_catalog(self) -> list[dict[str, Any]]:
        """Category ids with optional TOOL_LABEL/TOOL_DESCRIPTION from modules; tool counts only (no schemas)."""
        with self._lock:
            order = self._router_category_order()
            out: list[dict[str, Any]] = []
            for cid in order:
                tools = self._router_cat_tools.get(cid)
                if not tools:
                    continue
                TOOL_LABEL = self._router_cat_TOOL_LABEL.get(cid) or cid
                desc = self._router_cat_TOOL_DESCRIPTION.get(cid) or ""
                out.append(
                    {
                        "id": cid,
                        "TOOL_LABEL": TOOL_LABEL,
                        "TOOL_DESCRIPTION": desc,
                        "tool_count": len(tools),
                    }
                )
            return out

    def list_router_category_tools_lite(self, category: str) -> list[dict[str, str]]:
        """Registered tool function names + TOOL_DESCRIPTIONs for one router category; no parameter schemas."""
        c = category.strip().lower()
        with self._lock:
            names = self._router_cat_tools.get(c)
            if not names:
                return []
            name_set = set(names)
            rows: list[dict[str, str]] = []
            for spec in self._chat_tool_specs:
                fn = spec.get("function") if isinstance(spec, dict) else None
                if not isinstance(fn, dict):
                    continue
                n = fn.get("name")
                if not n or n not in name_set:
                    continue
                rows.append(
                    {
                        "name": str(n),
                        "TOOL_DESCRIPTION": (fn.get("TOOL_DESCRIPTION") or "").strip(),
                    }
                )
        rows.sort(key=lambda r: r["name"])
        return rows

    def classify_tool_router_categories(self, user_text: str) -> frozenset[str]:
        """Every category whose trigger set matches ``user_text`` (substring, lowercased)."""
        if not (user_text or "").strip():
            return frozenset()
        tl = user_text.lower()
        with self._lock:
            order = self._router_category_order()
            TOOL_TRIGGERS_map = self._router_cat_TOOL_TRIGGERS
        matched: set[str] = set()
        for cat in order:
            for sub in TOOL_TRIGGERS_map.get(cat, frozenset()):
                if sub and sub in tl:
                    matched.add(cat)
                    break
        return frozenset(matched)

    def classify_tool_router_category(self, user_text: str) -> str | None:
        """First matching category in router order (legacy single-winner)."""
        cats = self.classify_tool_router_categories(user_text)
        if not cats:
            return None
        with self._lock:
            order = self._router_category_order()
        for c in order:
            if c in cats:
                return c
        return next(iter(cats))

    @property
    def chat_tool_specs(self) -> list[dict[str, Any]]:
        """Specs in Chat Completions ``tools[]`` shape (HTTP wire format only; tools are yours)."""
        with self._lock:
            return list(self._chat_tool_specs)

    @property
    def tools_meta(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._tools_meta)

    def meta_entry_for_tool_name(self, registered_function_name: str) -> dict[str, Any] | None:
        """
        First ``tools_meta`` row whose ``tools`` list contains this registered function ``name``
        (same scan order as load; use when exposing module path to ``get_tool_help``).
        """
        n = (registered_function_name or "").strip()
        if not n:
            return None
        with self._lock:
            for entry in self._tools_meta:
                tlist = entry.get("tools")
                if isinstance(tlist, list) and n in tlist:
                    return dict(entry)
        return None

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
    """Full rescan of tool directories. ``scope`` is kept for API compatibility only."""
    global _registry
    s = (scope or "all").strip().lower()
    if s not in ("all", "extra"):
        raise ValueError("scope must be 'all' or 'extra'")

    with _registry_lock:
        candidate = ToolRegistry()
        candidate.load_all()
        _registry = candidate
        return _registry
