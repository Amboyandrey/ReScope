"""ORM models. Importing this package registers every table on `Base.metadata` for Alembic."""

from app.models.audit_log import AuditLog
from app.models.company import Company, Competency, CompetencyKind, Offering, OfferingKind, ProfileStatus
from app.models.crm import CompanyTag, Contact, Note, SavedSearch, Tag
from app.models.embedding import EMBEDDING_DIMENSIONS, Embedding, SourceKind
from app.models.import_job import Import, ImportKind, ImportStatus
from app.models.plan import Plan
from app.models.platform_settings import SETTINGS_ROW_ID, PlatformSettings
from app.models.role import Role, role_at_least
from app.models.scrape import ProfileChange, ScrapeJob, ScrapeMode, ScrapePage, ScrapeStatus
from app.models.tenant import Invitation, Membership, Tenant
from app.models.usage import UsageEvent, UsageKind
from app.models.user import User

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "SETTINGS_ROW_ID",
    "AuditLog",
    "Company",
    "CompanyTag",
    "Competency",
    "CompetencyKind",
    "Contact",
    "Embedding",
    "Import",
    "ImportKind",
    "ImportStatus",
    "Invitation",
    "Membership",
    "Note",
    "Offering",
    "OfferingKind",
    "Plan",
    "PlatformSettings",
    "ProfileChange",
    "ProfileStatus",
    "Role",
    "SavedSearch",
    "ScrapeJob",
    "ScrapeMode",
    "ScrapePage",
    "ScrapeStatus",
    "SourceKind",
    "Tag",
    "Tenant",
    "UsageEvent",
    "UsageKind",
    "User",
    "role_at_least",
]
