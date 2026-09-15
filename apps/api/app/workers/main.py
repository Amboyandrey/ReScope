"""arq worker settings — the background process for embeddings, scheduling and imports.

The scraping tiers get their own worker process and image later (Chromium is heavy and crashy);
this one stays light. Jobs are registered in `functions` as they're added.
"""

from typing import Any

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging


async def startup(ctx: dict[str, Any]) -> None:
    """Configure logging once per worker process."""
    configure_logging(get_settings().debug)


class WorkerSettings:
    """What `arq app.workers.main.WorkerSettings` runs."""

    functions: list[Any] = []
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 5
    job_timeout = 600
