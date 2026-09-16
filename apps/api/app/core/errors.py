"""Domain exceptions — services raise these, one handler in main.py turns them into responses."""


class AppError(Exception):
    """Base for exceptions that map to a specific HTTP response instead of a raw 500."""

    status_code: int = 500
    detail: str = "Something went wrong."

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.detail)
        if detail is not None:
            self.detail = detail


class EmailAlreadyRegistered(AppError):
    status_code = 409
    detail = "An account with this email already exists."


class InvalidCredentials(AppError):
    """Same message for an unknown email and a wrong password — neither is confirmed."""

    status_code = 401
    detail = "Invalid email or password."


class SessionInvalid(AppError):
    status_code = 401
    detail = "Your session has expired. Please sign in again."


class CsrfTokenInvalid(AppError):
    status_code = 403
    detail = "Invalid CSRF token."


class RateLimited(AppError):
    status_code = 429
    detail = "Too many attempts. Please try again later."


class TenantNotFound(AppError):
    """Raised for a tenant that doesn't exist, or the caller isn't a member of.

    404, not 403 — telling a non-member a tenant exists would itself leak information.
    """

    status_code = 404
    detail = "Tenant not found."


class SlugTaken(AppError):
    status_code = 409
    detail = "That subdomain is already taken."


class SlugReserved(AppError):
    status_code = 422
    detail = "That subdomain is reserved."


class InsufficientRole(AppError):
    status_code = 403
    detail = "You don't have permission to do that."


class MemberNotFound(AppError):
    status_code = 404
    detail = "Member not found."


class LastOwnerError(AppError):
    status_code = 409
    detail = "A tenant must always have at least one owner."


class InvitationInvalid(AppError):
    status_code = 400
    detail = "This invitation is invalid or has expired."


class InvitationNotFound(AppError):
    status_code = 404
    detail = "Invitation not found."


class CompanyNotFound(AppError):
    status_code = 404
    detail = "Company not found."


class CompanyAlreadyTracked(AppError):
    status_code = 409
    detail = "This company is already tracked in this workspace."


class InvalidDomain(AppError):
    status_code = 422
    detail = "Enter a valid company website or domain."


class QuotaExceeded(AppError):
    status_code = 402
    detail = "This tenant's plan quota is used up for this month."


class ScrapingPaused(AppError):
    status_code = 503
    detail = "Scraping is temporarily paused platform-wide."


class SuperadminRequired(AppError):
    status_code = 403
    detail = "This action requires platform administrator access."


class TagNotFound(AppError):
    status_code = 404
    detail = "Tag not found."


class TagAlreadyExists(AppError):
    status_code = 409
    detail = "A tag with this name already exists."


class SavedSearchNotFound(AppError):
    status_code = 404
    detail = "Saved search not found."


class CredentialNotFound(AppError):
    status_code = 404
    detail = "No credential is registered for that provider."


class CredentialValidationFailed(AppError):
    """The detail is filled in with the provider's own rejection reason at raise time."""

    status_code = 422
    detail = "That key could not be validated."


class BrowserUseKeyRequired(AppError):
    status_code = 422
    detail = "Register a Browser Use key (or ask the platform to enable one) before switching to it."


class ChatKeyRequired(AppError):
    status_code = 422
    detail = "Register a key for that provider before switching chat to it."


class ConversationNotFound(AppError):
    status_code = 404
    detail = "Conversation not found."


class ChatQuotaExceeded(AppError):
    status_code = 402
    detail = "This tenant's plan chat quota is used up for this month."
