"""Validate proof receipts without treating unverified artifacts as proofs."""

from __future__ import annotations

import hashlib
from pathlib import Path


def validate_artifact(path: str | Path, expected_sha256: str) -> bool:
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if digest != expected_sha256:
        raise ValueError("proof artifact hash mismatch")
    return True
