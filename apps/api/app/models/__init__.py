"""ORM models. Importing this package registers every table on `Base.metadata` for Alembic."""

from app.models.user import User

__all__ = ["User"]
