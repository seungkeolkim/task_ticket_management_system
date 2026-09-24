"""Stable JSON hashing for persisted input and skill snapshots."""

import hashlib
import json
from typing import Any


def canonical_json_sha256(value: Any) -> str:
    """JSON 값을 canonical 형식으로 직렬화해 SHA-256 hash를 계산한다."""
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
