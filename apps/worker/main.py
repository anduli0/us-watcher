"""Worker entrypoint: ``python apps/worker/main.py``.

Runs the APScheduler jobs (news sync, ET-scheduled briefs, orchestrator,
recommendations). Shares the same DATABASE_URL as the API.
"""

from __future__ import annotations

import asyncio

from us_watcher.worker.scheduler import run_worker

if __name__ == "__main__":
    asyncio.run(run_worker())
