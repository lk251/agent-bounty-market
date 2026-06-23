from __future__ import annotations

import hmac
import json
import time
from hashlib import sha256
from sqlite3 import Connection
from typing import Any

from .util import sha256_bytes, utc_now


class StripeWebhookError(RuntimeError):
    pass


def verify_stripe_signature(
    *,
    payload: bytes,
    signature_header: str,
    endpoint_secret: str,
    now: int | None = None,
    tolerance_seconds: int = 300,
) -> int:
    if not endpoint_secret:
        raise StripeWebhookError("Stripe webhook endpoint secret is required")
    timestamp, signatures = _parse_signature_header(signature_header)
    current_time = int(time.time()) if now is None else int(now)
    if tolerance_seconds >= 0 and abs(current_time - timestamp) > tolerance_seconds:
        raise StripeWebhookError("Stripe webhook signature timestamp is outside tolerance")
    signed_payload = f"{timestamp}.".encode("utf-8") + payload
    expected = hmac.new(endpoint_secret.encode("utf-8"), signed_payload, sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise StripeWebhookError("Stripe webhook signature verification failed")
    return timestamp


def record_stripe_webhook_event(
    conn: Connection,
    *,
    payload: bytes,
    signature_header: str,
    endpoint_secret: str,
    now: int | None = None,
    tolerance_seconds: int = 300,
) -> dict[str, Any]:
    signature_timestamp = verify_stripe_signature(
        payload=payload,
        signature_header=signature_header,
        endpoint_secret=endpoint_secret,
        now=now,
        tolerance_seconds=tolerance_seconds,
    )
    try:
        event = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StripeWebhookError("Stripe webhook payload must be UTF-8 JSON") from exc
    if not isinstance(event, dict):
        raise StripeWebhookError("Stripe webhook event must be a JSON object")
    return record_verified_stripe_event(
        conn,
        event=event,
        payload=payload,
        signature_timestamp=signature_timestamp,
    )


def record_verified_stripe_event(
    conn: Connection,
    *,
    event: dict[str, Any],
    payload: bytes,
    signature_timestamp: int = 0,
) -> dict[str, Any]:
    event_id = _required_str(event, "id")
    event_type = _required_str(event, "type")
    livemode = event.get("livemode")
    if livemode is not False:
        raise StripeWebhookError("Stripe webhook event must be test-mode")
    data = event.get("data")
    obj = data.get("object") if isinstance(data, dict) else None
    object_id = obj.get("id") if isinstance(obj, dict) and isinstance(obj.get("id"), str) else None
    account_id = event.get("account") if isinstance(event.get("account"), str) else None
    api_version = event.get("api_version") if isinstance(event.get("api_version"), str) else None
    payload_hash = sha256_bytes(payload)
    existing = conn.execute("SELECT * FROM stripe_webhook_events WHERE event_id = ?", (event_id,)).fetchone()
    if existing:
        if existing["payload_sha256"] != payload_hash:
            raise StripeWebhookError("Stripe webhook event id replayed with different payload")
        return {
            "event_id": event_id,
            "event_type": event_type,
            "event": event,
            "replayed": True,
            "status": existing["status"],
            "action": existing["action"],
        }
    received_at = utc_now()
    with conn:
        conn.execute(
            """
            INSERT INTO stripe_webhook_events(
                event_id, event_type, livemode, payload_sha256, signature_timestamp,
                received_at, status, api_version, account_id, object_id, processing_attempts
            )
            VALUES (?, ?, 0, ?, ?, ?, 'recorded', ?, ?, ?, 0)
            """,
            (event_id, event_type, payload_hash, signature_timestamp, received_at, api_version, account_id, object_id),
        )
    return {
        "event_id": event_id,
        "event_type": event_type,
        "event": event,
        "replayed": False,
        "status": "recorded",
        "action": None,
    }


def finish_stripe_webhook_event(conn: Connection, *, event_id: str, status: str, action: str | None = None, error: str | None = None) -> None:
    with conn:
        conn.execute(
            """
            UPDATE stripe_webhook_events
            SET status = ?, action = ?, error = ?, processed_at = ?,
                processing_attempts = processing_attempts + 1
            WHERE event_id = ?
            """,
            (status, action, error, utc_now(), event_id),
        )


def _parse_signature_header(value: str) -> tuple[int, list[str]]:
    fields: dict[str, list[str]] = {}
    for part in value.split(","):
        if "=" not in part:
            continue
        key, raw = part.split("=", 1)
        fields.setdefault(key.strip(), []).append(raw.strip())
    timestamps = fields.get("t") or []
    signatures = fields.get("v1") or []
    if len(timestamps) != 1 or not signatures:
        raise StripeWebhookError("Stripe-Signature header must contain t and v1")
    try:
        timestamp = int(timestamps[0])
    except ValueError as exc:
        raise StripeWebhookError("Stripe-Signature timestamp must be an integer") from exc
    return timestamp, signatures


def _required_str(event: dict[str, Any], key: str) -> str:
    value = event.get(key)
    if not isinstance(value, str) or not value:
        raise StripeWebhookError(f"Stripe webhook missing {key}")
    return value
