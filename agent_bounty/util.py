from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def parse_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def file_digest(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def require_positive_amount(amount: int) -> None:
    if not isinstance(amount, int) or amount <= 0:
        raise ValueError("amount must be a positive integer in minor currency units")


def require_currency(currency: str) -> str:
    clean = currency.strip().upper()
    if len(clean) != 3 or not clean.isalpha():
        raise ValueError("currency must be a 3-letter code")
    return clean
