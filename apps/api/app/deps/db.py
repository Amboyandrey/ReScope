"""Typed dependency aliases so routers declare `db: DbSession` instead of repeating `Depends(get_db)`."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db

DbSession = Annotated[AsyncSession, Depends(get_db)]
