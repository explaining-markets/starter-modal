"""Verify the vendored verifier against the frozen, published test vectors.

These vectors are pinned by the competition's server-side signer, so passing
here means a real broadcast will verify too. Time is pinned via ``now=`` so the
timestamp-tolerance check is deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from explaining_markets import WebhookVerificationError, verify_webhook

VECTORS_PATH = Path(__file__).resolve().parent / "test_vectors.json"


def _vector() -> dict:
    return json.loads(VECTORS_PATH.read_text())["vectors"][0]


def _headers(vec: dict, *, signature: str | None = None, ts: int | None = None) -> dict[str, str]:
    return {
        "webhook-id": vec["webhook_id"],
        "webhook-timestamp": str(ts if ts is not None else vec["timestamp"]),
        "webhook-signature": signature if signature is not None else vec["expected_signature_header"],
    }


def test_happy_path_returns_parsed_payload() -> None:
    vec = _vector()
    payload = verify_webhook(
        raw_body=vec["raw_body"].encode(),
        headers=_headers(vec),
        secret=vec["secret"],
        now=vec["timestamp"],
    )
    assert payload["id"] == vec["webhook_id"]


def test_rejects_missing_headers() -> None:
    vec = _vector()
    with pytest.raises(WebhookVerificationError, match="missing"):
        verify_webhook(
            raw_body=vec["raw_body"].encode(),
            headers={},
            secret=vec["secret"],
            now=vec["timestamp"],
        )


def test_rejects_old_timestamp() -> None:
    vec = _vector()
    with pytest.raises(WebhookVerificationError, match="tolerance"):
        verify_webhook(
            raw_body=vec["raw_body"].encode(),
            headers=_headers(vec),
            secret=vec["secret"],
            now=vec["timestamp"] + 10_000,
        )


def test_rejects_bad_signature() -> None:
    vec = _vector()
    with pytest.raises(WebhookVerificationError, match="signature"):
        verify_webhook(
            raw_body=vec["raw_body"].encode(),
            headers=_headers(vec, signature="v1,deadbeef"),
            secret=vec["secret"],
            now=vec["timestamp"],
        )


def test_rejects_body_tamper() -> None:
    vec = _vector()
    with pytest.raises(WebhookVerificationError, match="signature"):
        verify_webhook(
            raw_body=(vec["raw_body"] + " ").encode(),  # one trailing space breaks HMAC
            headers=_headers(vec),
            secret=vec["secret"],
            now=vec["timestamp"],
        )
