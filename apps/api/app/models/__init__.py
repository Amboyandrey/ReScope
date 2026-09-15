"""ORM models. Importing this package registers every table on `Base.metadata` for Alembic."""

from app.models.audit_log import AuditLog
from app.models.company import Company, Competency, CompetencyKind, Offering, OfferingKind, ProfileStatus
from app.models.embedding import EMBEDDING_DIMENSIONS, Embedding, SourceKind
from app.models.plan import Plan
from app.models.role import Role, role_at_least
from app.models.scrape import ProfileChange, ScrapeJob, ScrapeMode, ScrapePage, ScrapeStatus
from app.models.tenant import Invitation, Membership, Tenant
from app.models.user import User

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "AuditLog",
    "Company",
    "Competency",
    "CompetencyKind",
    "Embedding",
    "Invitation",
    "Membership",
    "Offering",
    "OfferingKind",
    "Plan",
    "ProfileChange",
    "ProfileStatus",
    "Role",
    "ScrapeJob",
    "ScrapeMode",
    "ScrapePage",
    "ScrapeStatus",
    "SourceKind",
    "Tenant",
    "User",
    "role_at_least",
]
