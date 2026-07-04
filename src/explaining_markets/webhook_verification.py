"""Reference verifier for Explaining Markets Competition webhooks.

Vendored, stdlib-only. This is a verbatim copy of the competition's canonical
verifier, copied in (rather than installed from PyPI) so the starter is
self-contained and has zero runtime dependencies for verification. If/when that
package is published, you can swap this file for a pinned dependency — see
``docs/advanced.md``.

Webhooks are signed Standard-Webhooks style: HMAC-SHA256 over
``Webhook-Id . Webhook-Timestamp . raw_body`` using your ``whsec_...`` secret.

Usage::

    from explaining_markets import verify_webhook, WebhookVerificationError

    raw_body = await request.body()  # raw bytes — never request.json()
    try:
        event = verify_webhook(
            raw_body=raw_body,
            headers=request.headers,
            secret=os.environ["EM_WEBHOOK_SECRET"],
        )
    except WebhookVerificationError:
        return Response(status_code=401)

    process(event)  # event is the parsed JSON payload, post-verification
"""

from __future__ import annotations

import base64
import hmac
import json
import time
from collections.abc import Mapping
from hashlib import sha256
from typing import Any

__all__ = [
    "DEFAULT_TOLERANCE_SECONDS",
    "WebhookVerificationError",
    "verify_webhook",
]

DEFAULT_TOLERANCE_SECONDS = 5 * 60
_SECRET_PREFIX = "whsec_"
_SIGNATURE_VERSION = "v1"


class WebhookVerificationError(Exception):
    """Raised when the webhook payload is missing/forged/expired."""


def _decode_secret(secret: str) -> bytes:
    if not secret.startswith(_SECRET_PREFIX):
        raise WebhookVerificationError("signing secret must start with whsec_")
    body = secret[len(_SECRET_PREFIX):]
    pad = "=" * (-len(body) % 4)
    try:
        return base64.urlsafe_b64decode(body + pad)
    except Exception as exc:
        raise WebhookVerificationError("signing secret body is not valid base64url") from exc


def _normalize_headers(headers: Mapping[str, str] | Mapping[bytes, bytes]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in headers.items():
        key = k.decode("ascii") if isinstance(k, (bytes, bytearray)) else str(k)
        val = v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else str(v)
        out[key.lower()] = val
    return out


def verify_webhook(
    *,
    raw_body: bytes,
    headers: Mapping[str, str] | Mapping[bytes, bytes],
    secret: str,
    tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
    now: int | None = None,
) -> dict[str, Any]:
    """Verify a webhook delivery and return the parsed JSON payload.

    Raises ``WebhookVerificationError`` on any verification failure. **Always**
    pass the raw request body bytes — re-serializing parsed JSON breaks
    verification.
    """
    h = _normalize_headers(headers)
    webhook_id = h.get("webhook-id")
    timestamp_raw = h.get("webhook-timestamp")
    signature_header = h.get("webhook-signature")

    if not webhook_id or not timestamp_raw or not signature_header:
        raise WebhookVerificationError("missing one of Webhook-Id, Webhook-Timestamp, Webhook-Signature")

    try:
        timestamp = int(timestamp_raw)
    except ValueError as exc:
        raise WebhookVerificationError("Webhook-Timestamp is not an integer") from exc

    current = int(time.time()) if now is None else now
    if abs(current - timestamp) > tolerance_seconds:
        raise WebhookVerificationError(
            f"Webhook-Timestamp outside {tolerance_seconds}s tolerance"
        )

    key = _decode_secret(secret)
    signed_payload = (
        webhook_id.encode("utf-8") + b"." + str(timestamp).encode("ascii") + b"." + raw_body
    )
    expected = base64.b64encode(hmac.new(key, signed_payload, sha256).digest()).decode("ascii")

    matched = False
    for chunk in signature_header.split():
        if "," not in chunk:
            continue
        version, value = chunk.split(",", 1)
        if version != _SIGNATURE_VERSION:
            continue
        if hmac.compare_digest(expected, value):
            matched = True
            break
    if not matched:
        raise WebhookVerificationError("no matching v1 signature")

    try:
        return json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise WebhookVerificationError("body is not valid JSON") from exc
