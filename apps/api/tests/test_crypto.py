"""Envelope encryption round-trips, and that tampering breaks it."""

import pytest

from app.core.crypto import decrypt_secret, encrypt_secret


def test_round_trips_a_secret() -> None:
    secret = encrypt_secret("sk-ant-super-secret-key")
    assert decrypt_secret(secret) == "sk-ant-super-secret-key"


def test_two_encryptions_of_the_same_plaintext_differ() -> None:
    """Fresh nonces and data keys every time — ciphertext never repeats even for the same input."""
    first = encrypt_secret("sk-ant-super-secret-key")
    second = encrypt_secret("sk-ant-super-secret-key")
    assert first.ciphertext != second.ciphertext
    assert first.wrapped_key != second.wrapped_key


def test_tampered_ciphertext_fails_to_decrypt() -> None:
    secret = encrypt_secret("sk-ant-super-secret-key")
    tampered = secret._replace(ciphertext=b"\x00" + secret.ciphertext[1:])
    with pytest.raises(Exception):  # noqa: B017 — AESGCM raises its own InvalidTag, not ours
        decrypt_secret(tampered)
