from __future__ import annotations

import re
from uuid import uuid4

CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def correlation_id(value: str | None, prefix: str) -> str:
    candidate = (value or "").strip()
    return candidate if CORRELATION_ID_PATTERN.fullmatch(candidate) else f"{prefix}_{uuid4().hex}"
