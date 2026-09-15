"""Enqueuing scrape jobs onto the scraper worker's own queue (app/workers/scraper.py).

A dedicated queue name — not arq's default — is what keeps a scrape job from ever landing on the
lightweight `worker` process (app/workers/main.py): that process has no Chromium and would just
fail the job outright if it ever dequeued one. The two processes never compete for each other's work.
"""

import uuid

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings

from app.core.config import get_settings

settings = get_settings()

SCRAPE_QUEUE_NAME = "scrape_queue"

_pool: ArqRedis | None = None


async def _get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _pool


async def enqueue_scrape_job(*, job_id: uuid.UUID, tenant_id: uuid.UUID, company_id: uuid.UUID) -> None:
    """Queue a scrape job. `_job_id` is the job's own id, so a retry that re-enqueues the same
    `ScrapeJob` row coalesces rather than running two scrapes of the same company concurrently."""
    pool = await _get_pool()
    await pool.enqueue_job(
        "scrape_company",
        str(job_id),
        str(tenant_id),
        str(company_id),
        _queue_name=SCRAPE_QUEUE_NAME,
        _job_id=f"scrape:{job_id}",
    )
