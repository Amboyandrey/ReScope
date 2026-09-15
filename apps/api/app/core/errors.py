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
