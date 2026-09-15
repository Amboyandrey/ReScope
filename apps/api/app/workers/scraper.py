"""The scraper worker's entry point — run as `arq app.workers.scraper.WorkerSettings` (see the
`scraper` service in infra/docker-compose.yml). Separate process and image from
app/workers/main.py: this one carries Chromium and is the only one that ever touches it."""

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.services.jobs import SCRAPE_QUEUE_NAME
from app.workers.scrape_company import scrape_company

settings = get_settings()


class WorkerSettings:
    functions = [scrape_company]
    queue_name = SCRAPE_QUEUE_NAME
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    # One job at a time: each launches its own Chromium instance, and rendering a dozen pages
    # plus one extraction call already takes real wall-clock time — no reason to run several
    # browsers per worker process before there's evidence the resources are there for it.
    max_jobs = 1
    job_timeout = 900
    keep_result = 0
