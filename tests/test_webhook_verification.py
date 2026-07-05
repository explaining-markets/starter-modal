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


def _load_vectors() -> list[dict]:
    return json.loads(VECTORS_PATH.read_text())["vectors"]


def _vector() -> dict:
    """The single-signature vector (scalar ``secret``)."""
    return next(v for v in _load_vectors() if "secret" in v)


def _rotation_vector() -> dict:
    """The rotation-overlap vector (``secrets`` list, multi-signature header)."""
    return next(v for v in _load_vectors() if "secrets" in v)


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


def test_rotation_verifies_with_each_secret() -> None:
    """During secret rotation the sender emits `v1,new v1,old`; a handler holding
    EITHER the current or the previous secret must accept the delivery."""
    vec = _rotation_vector()
    for secret in vec["secrets"]:
        payload = verify_webhook(
            raw_body=vec["raw_body"].encode(),
            headers=_headers(vec),
            secret=secret,
            now=vec["timestamp"],
        )
        assert payload["id"] == vec["webhook_id"]


def test_rotation_rejects_unrelated_secret() -> None:
    """A secret that signed neither signature in the header is rejected."""
    vec = _rotation_vector()
    unrelated = "whsec_" + "A" * 43  # valid base64url, not one of the signers
    with pytest.raises(WebhookVerificationError, match="signature"):
        verify_webhook(
            raw_body=vec["raw_body"].encode(),
            headers=_headers(vec),
            secret=unrelated,
            now=vec["timestamp"],
        )


def test_accepts_signatures_in_any_order() -> None:
    """`accept if any verifies` — the order of the space-delimited signatures in
    the header must not matter."""
    vec = _rotation_vector()
    reversed_header = " ".join(reversed(vec["expected_signature_header"].split()))
    payload = verify_webhook(
        raw_body=vec["raw_body"].encode(),
        headers=_headers(vec, signature=reversed_header),
        secret=vec["secrets"][0],
        now=vec["timestamp"],
    )
    assert payload["id"] == vec["webhook_id"]


def test_normalizes_byte_headers() -> None:
    """ASGI servers pass headers as byte-keyed mappings; the verifier accepts both."""
    vec = _vector()
    byte_headers = {
        b"webhook-id": vec["webhook_id"].encode(),
        b"webhook-timestamp": str(vec["timestamp"]).encode(),
        b"webhook-signature": vec["expected_signature_header"].encode(),
    }
    payload = verify_webhook(
        raw_body=vec["raw_body"].encode(),
        headers=byte_headers,
        secret=vec["secret"],
        now=vec["timestamp"],
    )
    assert payload["id"] == vec["webhook_id"]
