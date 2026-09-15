"""Reading and changing the one row of platform-wide operator controls."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ScrapingPaused
from app.models import SETTINGS_ROW_ID, PlatformSettings


async def get_platform_settings(db: AsyncSession) -> PlatformSettings:
    """Fetch the singleton row — always present, seeded by migration 0005."""
    settings = await db.get(PlatformSettings, SETTINGS_ROW_ID)
    assert settings is not None  # seeded by migration; never deleted
    return settings


async def set_scraping_paused(db: AsyncSession, *, paused: bool) -> PlatformSettings:
    """Flip the killswitch. Superadmin-only — enforced by the caller (the router dependency)."""
    settings = await get_platform_settings(db)
    settings.scraping_paused = paused
    await db.flush()
    return settings


async def assert_scraping_not_paused(db: AsyncSession) -> None:
    """Raise `ScrapingPaused` if the killswitch is on — checked before enqueue and again inside
    the scraper worker itself, since time passes between the two."""
    settings = await get_platform_settings(db)
    if settings.scraping_paused:
        raise ScrapingPaused()
