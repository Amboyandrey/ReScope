"""Domain exceptions — services raise these, one handler in main.py turns them into responses."""


class AppError(Exception):
    """Base for exceptions that map to a specific HTTP response instead of a raw 500."""

    status_code: int = 500
    detail: str = "Something went wrong."

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.detail)
        if detail is not None:
            self.detail = detail
