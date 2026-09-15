"""Writing and reading screenshot bytes on the shared storage volume — the same
bind-mounted-volume, write-bytes-under-a-key pattern ReCore uses for chat attachments.

Synchronous, matching that precedent: these are local files under a bind-mounted volume, not a
network store, so a thread hop buys nothing here.
"""

import uuid
from pathlib import Path

from app.core.config import get_settings

settings = get_settings()


def save_screenshot(tenant_id: uuid.UUID, job_id: uuid.UUID, png_bytes: bytes) -> str:
    """Write one screenshot and return its storage key."""
    key = f"{tenant_id}/{job_id}/{uuid.uuid4()}.png"
    path = Path(settings.storage_dir) / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_bytes)
    return key


def read_screenshot(storage_key: str) -> bytes:
    """Read a screenshot's bytes back by its stored key."""
    return (Path(settings.storage_dir) / storage_key).read_bytes()
