"""
Separate Workflow Registry for cron jobs only.
100% separated from Tool Registry. No mix. No tool pollution.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from . import config
from .registry import _stable_module_slug, _iter_tool_py_files

logger = logging.getLogger(__name__)

WorkflowHandler = Callable[[dict[str, Any]], str]


class WorkflowRegistry:
    """Scans ONLY for cron workflows, no tools. 100% separate."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: list[dict[str, Any]] = []

    def load_all(self) -> None:
        with self._lock:
            self._jobs.clear()

            dirs = config.tool_scan_directories()
            if not dirs:
                return

            for dir_idx, directory in enumerate(dirs):
                if not directory.is_dir():
                    continue
                for path in _iter_tool_py_files(directory):
                    try:
                        slug = _stable_module_slug(directory, path, dir_idx)
                        mod_name = f"agent_workflow_{slug}"
                        spec = importlib.util.spec_from_file_location(mod_name, path)
                        if spec is None or spec.loader is None:
                            continue
                        mod = importlib.util.module_from_spec(spec)
                        sys.modules[mod_name] = mod
                        spec.loader.exec_module(mod)
                    except Exception:
                        continue

                    handlers = getattr(mod, "HANDLERS", None)
                    minutes = getattr(mod, "RUN_EVERY_MINUTES", None)

                    if not isinstance(handlers, dict) or not handlers:
                        continue
                    if not isinstance(minutes, (int, float)) or minutes <= 0:
                        continue

                    run_on_start = getattr(mod, "RUN_ON_STARTUP", False)
                    handler_name = next(iter(handlers.keys()))

                    self._jobs.append({
                        'name': handler_name,
                        'handler': handlers[handler_name],
                        'interval_seconds': minutes * 60,
                        'last_run': 0.0,
                        'run_on_start': run_on_start
                    })

                    logger.info(f"Registered workflow cron job: {handler_name} every {minutes} minutes [WORKFLOW ONLY, NO TOOLS]")

    @property
    def jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._jobs)


_workflow_registry: WorkflowRegistry | None = None
_workflow_registry_lock = threading.Lock()


def get_workflow_registry() -> WorkflowRegistry:
    global _workflow_registry
    with _workflow_registry_lock:
        if _workflow_registry is None:
            _workflow_registry = WorkflowRegistry()
            _workflow_registry.load_all()
        return _workflow_registry