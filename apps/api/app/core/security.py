"""Password hashing and random tokens — the primitives auth is built on."""

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# argon2-cffi's defaults (Argon2id, 64 MiB, 3 passes) track OWASP's current guidance.
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a plaintext password for storage."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Check a plaintext password against a stored hash without raising on a mismatch."""
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def generate_token() -> str:
    """A random URL-safe token with enough entropy for a session id, CSRF token, or invite."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 of a token, for storing lookups of secrets (invites) without storing the secret."""
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_match(a: str, b: str) -> bool:
    """Constant-time comparison, so timing can't reveal a correct prefix."""
    return hmac.compare_digest(a, b)
