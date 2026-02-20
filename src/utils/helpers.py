"""Common helper functions for the banking document pipeline."""

import hashlib
import os
from pathlib import Path
from datetime import datetime


def compute_file_hash(file_bytes: bytes) -> str:
    """Compute SHA-256 hash of file for deduplication and audit."""
    return hashlib.sha256(file_bytes).hexdigest()


def validate_file_extension(filename: str, allowed: list[str]) -> bool:
    """Check if file extension is in allowed list."""
    ext = Path(filename).suffix.lower().lstrip(".")
    return ext in allowed


def get_file_size_mb(file_bytes: bytes) -> float:
    """Get file size in megabytes."""
    return len(file_bytes) / (1024 * 1024)


def mask_sensitive_data(value: str, visible_chars: int = 4) -> str:
    """
    Mask sensitive data for logging (PII protection).
    Shows only last N characters: "1234567890" → "******7890"
    """
    if not value or len(value) <= visible_chars:
        return "****"
    return "*" * (len(value) - visible_chars) + value[-visible_chars:]


def generate_audit_filename(document_id: str, extension: str = "json") -> str:
    """Generate timestamped audit filename."""
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return f"{document_id}_{timestamp}.{extension}"


def sanitize_filename(filename: str) -> str:
    """Remove potentially dangerous characters from filenames."""
    keepchars = (" ", ".", "_", "-")
    return "".join(c for c in filename if c.isalnum() or c in keepchars).rstrip()
