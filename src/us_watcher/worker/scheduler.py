"""APScheduler worker — scheduled data refresh & briefings (spec §37).

Jobs run on the America/New_York calendar (DST handled by the IANA timezone in
each CronTrigger). Every job is wrapped with a pipeline lock (idempotency /
duplicate-run prevention), retries with backoff, structured logging, and an
audit event. One job failing never stops the scheduler.

Run: ``python apps/worker/main.py`` (or via the autostart bat).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from us_watcher.briefing.service import generate_daily_brief
from us_watcher.config import get_settings
from us_watcher.db.repositories import add_audit_event, release_lock, try_acquire_lock
from us_watcher.domain.enums import BriefingType
from us_watcher.domain.time import is_trading_day, now_utc, session_status, to_et
from us_watcher.infrastructure.db import create_all
from us_watcher.logging_config import get_logger

log = get_logger("us_watcher.worker")

_NY = "America/New_York"


async def _run_guarded(
    name: str,
    fn: Callable[[], Awaitable[dict]],
    *,
    ttl: int = 1800,
    notify: Callable[[], Awaitable[object]] | None = None,
) -> None:
    """Run a job under a daily lock with retry/backoff and audit. Never raises.

    ``notify`` (optional) fires once after the job succeeds — used to push the
    daily brief / recommendations to Telegram. A notification failure is logged
    but never fails the job itself.
    """
    key = f"{name}:{to_et(now_utc()).date().isoformat()}"
    holder = f"worker-{id(asyncio.current_task())}"
    if not await try_acquire_lock(key, holder=holder, ttl_seconds=ttl):
        log.info("worker.skip_locked", job=name, key=key)
        return
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            result = await fn()
            log.info("worker.job_ok", job=name, attempt=attempt, result=_compact(result))
            await add_audit_event(f"worker.{name}", f"{name} completed", payload=_compact(result))
            if notify is not None:
                try:
                    await notify()
                except Exception as exc:  # delivery must never fail the job
                    log.warning("worker.notify_failed", job=name, error=str(exc)[:200])
            return
        except Exception as exc:  # isolate; retry with backoff
            last_err = exc
            log.warning("worker.job_retry", job=name, attempt=attempt, error=str(exc)[:200])
            await asyncio.sleep(2 ** attempt)
    log.error("worker.job_failed", job=name, error=str(last_err)[:300])
    await add_audit_event(f"worker.{name}.failed", f"{name} failed after retries",
                          payload={"error": str(last_err)[:300]})
    await release_lock(key)  # allow a manual rerun


def _compact(d: dict) -> dict:
    return {k: v for k, v in d.items() if not isinstance(v, list | dict)} if isinstance(d, dict) else {}


# ---- jobs ----
async def job_news_sync() -> None:
    from us_watcher.newsfeed.service import sync_news
    await _run_guarded("news_sync", sync_news, ttl=3000)


def _market_day_now() -> bool:
    """True when today (ET) is a regular trading day (not weekend/holiday)."""
    return is_trading_day(to_et(now_utc()).date())


async def job_premarket() -> None:
    # Intraday briefs only make sense on a live session day. On weekends/holidays
    # the forward-looking FULL brief (next-session forecast) carries the day.
    if not _market_day_now():
        log.info("worker.skip_nontrading", job="premarket_brief")
        return
    await _run_guarded("premarket_brief", lambda: generate_daily_brief(BriefingType.PREMARKET))


async def job_midday() -> None:
    if not _market_day_now():
        log.info("worker.skip_nontrading", job="midday_update")
        return
    await _run_guarded("midday_update", lambda: generate_daily_brief(BriefingType.MIDDAY))


async def job_closing() -> None:
    if not _market_day_now():
        log.info("worker.skip_nontrading", job="closing_brief")
        return
    await _run_guarded("closing_brief", lambda: generate_daily_brief(BriefingType.CLOSING))


async def job_full_brief() -> None:
    from us_watcher.notify.digest import send_brief_digest
    await _run_guarded(
        "full_brief", lambda: generate_daily_brief(BriefingType.FULL), notify=send_brief_digest
    )


async def job_recommendations() -> None:
    from us_watcher.agent_service.recommendation_pipeline import generate_recommendations
    from us_watcher.notify.digest import send_recommendations_digest
    await _run_guarded(
        "recommendations", generate_recommendations, ttl=3600, notify=send_recommendations_digest
    )


async def job_orchestrator() -> None:
    from us_watcher.agent_service.orchestrator import run_orchestrator
    await _run_guarded("orchestrator", lambda: run_orchestrator(objective="market_overview", trigger="scheduled"))


async def job_evaluate() -> None:
    from us_watcher.accuracy.evaluate import evaluate_recommendations
    await _run_guarded("evaluate", evaluate_recommendations, ttl=3600)


async def job_heartbeat() -> None:
    log.info("worker.heartbeat", session=session_status(), utc=now_utc().isoformat())


async def ensure_today_brief() -> None:
    """Catch-up guarantee: if the machine was asleep at the ET brief times (which
    fall in the Korean night), the cron jobs are missed and no brief exists for
    today. On every worker boot/resume, if today's FULL brief is still absent,
    generate it now and push the digest. The pipeline lock makes this idempotent
    with the cron job.

    Timing depends on whether the market trades today:
    - **Trading day**: wait until after the close (18:00 ET) so the FULL brief
      reflects the completed session — the cron job owns the on-time run.
    - **Non-trading day (weekend/holiday)**: the next-session (Monday) forecast is
      ready as soon as the prior close is in, and 18:00 ET falls in the Korean
      pre-dawn. Generate as soon as the worker is up, at ANY hour, so the Korean
      weekend daytime always has a fresh Monday-forecast brief instead of nothing.
    """
    from us_watcher.db.repositories import briefing_by_date
    from us_watcher.notify.digest import send_brief_digest

    et_now = to_et(now_utc())
    today = et_now.date().isoformat()
    trading = is_trading_day(et_now.date())
    if trading and et_now.hour < 18:
        return  # trading day, before the full-brief hour — let the cron job own it
    existing = await briefing_by_date(today, language="en", briefing_type="full")
    if existing is not None:
        return  # already generated today (cron or a prior catch-up)
    log.info("worker.brief_catchup", date=today, et_hour=et_now.hour, trading=trading)
    await _run_guarded(
        "full_brief", lambda: generate_daily_brief(BriefingType.FULL), notify=send_brief_digest
    )


# Briefs whose ET trigger lands in the Korean night are easily missed when the
# laptop sleeps; a generous grace window + coalesce lets APScheduler still fire
# them once on wake instead of silently skipping.
_BRIEF_MISFIRE = {"misfire_grace_time": 6 * 3600, "coalesce": True, "max_instances": 1}


def build_scheduler() -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone="UTC")
    # News: hourly (cheap, keeps the scrapbook current).
    sched.add_job(job_news_sync, IntervalTrigger(minutes=60), id="news_sync", max_instances=1)
    sched.add_job(job_heartbeat, IntervalTrigger(minutes=5), id="heartbeat", max_instances=1)
    # ET-scheduled briefs (DST-correct via IANA timezone).
    sched.add_job(job_premarket, CronTrigger(hour=7, minute=0, timezone=_NY), id="premarket", **_BRIEF_MISFIRE)
    sched.add_job(job_midday, CronTrigger(hour=12, minute=30, timezone=_NY), id="midday", **_BRIEF_MISFIRE)
    sched.add_job(job_closing, CronTrigger(hour=16, minute=15, timezone=_NY), id="closing", **_BRIEF_MISFIRE)
    sched.add_job(job_orchestrator, CronTrigger(hour=17, minute=45, timezone=_NY),
                  id="orchestrator", **_BRIEF_MISFIRE)
    sched.add_job(job_recommendations, CronTrigger(hour=17, minute=50, timezone=_NY),
                  id="recommendations", **_BRIEF_MISFIRE)
    # Evaluate matured recommendation outcomes (after the close, before the full brief).
    sched.add_job(job_evaluate, CronTrigger(hour=17, minute=55, timezone=_NY), id="evaluate", **_BRIEF_MISFIRE)
    sched.add_job(job_full_brief, CronTrigger(hour=18, minute=0, timezone=_NY), id="full_brief", **_BRIEF_MISFIRE)
    # Weekly outlook: Sunday 18:00 ET (reuses the full brief for now).
    sched.add_job(job_full_brief, CronTrigger(day_of_week="sun", hour=18, minute=0, timezone=_NY),
                  id="weekly", **_BRIEF_MISFIRE)
    return sched


async def run_worker() -> None:
    settings = get_settings()
    if settings.is_sqlite:
        await create_all()
    sched = build_scheduler()
    sched.start()
    jobs = ", ".join(j.id for j in sched.get_jobs())
    log.info("worker.started", timezone=_NY, jobs=jobs, today=to_et(now_utc()).date().isoformat())
    # Run an immediate news sync on boot so the scrapbook is never empty.
    await job_news_sync()
    # Catch up on any brief missed while the machine was asleep (see above).
    await ensure_today_brief()
    stop = asyncio.Event()
    try:
        await stop.wait()  # run until cancelled
    except (KeyboardInterrupt, asyncio.CancelledError):  # pragma: no cover
        sched.shutdown(wait=False)
