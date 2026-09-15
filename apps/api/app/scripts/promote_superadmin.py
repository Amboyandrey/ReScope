"""Promotes an existing account to superadmin — the only way one gets created; there's no
signup-time flag or seed for it, matching how ReCore leaves its own is_superuser flip to a manual
step.

Usage: uv run python -m app.scripts.promote_superadmin someone@example.com
"""

import asyncio
import sys

from sqlalchemy import select

from app.core.db import async_session_factory
from app.models import User


async def promote(email: str) -> None:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None:
            print(f"No account found for {email}", file=sys.stderr)
            raise SystemExit(1)
        user.is_superadmin = True
        await db.commit()
        print(f"{email} is now a superadmin.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: uv run python -m app.scripts.promote_superadmin <email>", file=sys.stderr)
        raise SystemExit(1)
    asyncio.run(promote(sys.argv[1]))
