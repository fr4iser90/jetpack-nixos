"""
Simple background cron scheduler for workflow jobs.
Automatically scans tools for RUN_EVERY_MINUTES and executes them periodically.
"""

from __future__ import annotations

import asyncio
import threading
import time
import logging
from typing import Any

from .workflow_registry import get_workflow_registry

logger = logging.getLogger(__name__)

_cron_thread: threading.Thread | None = None
_stop_event = threading.Event()


def start_cron_scheduler() -> None:
    """Start background cron scheduler thread."""
    global _cron_thread

    if _cron_thread is not None and _cron_thread.is_alive():
        return

    _stop_event.clear()
    _cron_thread = threading.Thread(target=_cron_worker, daemon=True, name="cron-scheduler")
    _cron_thread.start()


def stop_cron_scheduler() -> None:
    """Stop background cron scheduler thread."""
    _stop_event.set()
    if _cron_thread is not None:
        _cron_thread.join(timeout=10)


def _cron_worker() -> None:
    logger.info("Cron scheduler started")
    registry = get_workflow_registry()
    cron_jobs = registry.jobs

    if not cron_jobs:
        logger.info("No cron jobs found, scheduler exiting")
        return

    while not _stop_event.is_set():
        now = time.time()

        for job in cron_jobs:
            if job['run_on_start'] and job['last_run'] == 0:
                pass
            elif now - job['last_run'] < job['interval_seconds']:
                continue

            logger.info(f"Executing cron job: {job['name']}")

            try:
                result = job['handler']({})
                if asyncio.iscoroutine(result):
                    result = asyncio.run(result)
                logger.debug(f"Cron job {job['name']} completed: {str(result)[:120]}")
            except Exception as e:
                logger.exception(f"Cron job {job['name']} failed")

            job['last_run'] = now

        # Sleep 10 seconds between checks
        _stop_event.wait(timeout=10)

    logger.info("Cron scheduler stopped")