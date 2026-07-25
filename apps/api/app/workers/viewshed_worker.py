"""Viewshed worker process.

Polls for pending ``AnalysisRun`` rows of kind ``viewshed`` and computes their
``Viewshed`` rows. Run as its own process (a Docker Compose service in
production; directly with ``uv run`` for local development) so viewshed
computation never blocks the API.

Usage:
    uv run --project apps/api python -m app.workers.viewshed_worker
"""

from __future__ import annotations

import signal
import sys
import time
from types import FrameType

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import get_session_factory
from app.services.viewsheds import process_pending_viewshed_runs

POLL_INTERVAL_S = 5.0

_log = get_logger(__name__)
_shutdown_requested = False


def _handle_shutdown(signum: int, _frame: FrameType | None) -> None:
    global _shutdown_requested
    _log.info("worker_shutdown_requested", signal=signum)
    _shutdown_requested = True


def run_forever(poll_interval_s: float = POLL_INTERVAL_S) -> None:
    """Poll for pending viewshed runs until asked to stop."""
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.use_json_logs)
    session_factory = get_session_factory()

    _log.info("viewshed_worker_started", poll_interval_s=poll_interval_s)
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    while not _shutdown_requested:
        session = session_factory()
        try:
            processed = process_pending_viewshed_runs(session, settings)
            session.commit()
            if processed:
                _log.info("viewshed_worker_batch", runs_processed=len(processed))
        except Exception:  # noqa: BLE001 - the poll loop must survive any single batch failing
            session.rollback()
            _log.exception("viewshed_worker_batch_failed")
        finally:
            session.close()
        time.sleep(poll_interval_s)

    _log.info("viewshed_worker_stopped")


if __name__ == "__main__":
    run_forever()
    sys.exit(0)
