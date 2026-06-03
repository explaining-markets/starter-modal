"""Small helpers for working with a verified webhook event payload.

A verified event looks like::

    {
      "id": "<matches Webhook-Id; use as your idempotency key>",
      "event_id": "<uuid>",
      "event_type": "EARNINGS_RELEASE",   # or "TEST"
      "timing_category": "SCHEDULED",
      "event_datetime": "2026-01-15T21:00:00Z",
      "focal_assets": [{"identifier_type": "TICKER", "identifier_value": "AAPL"}],
      "information_url": "https://...signed...",
      "prediction_deadline": "2026-01-15T21:05:00Z"
    }
"""

from __future__ import annotations

from datetime import datetime, timezone


def is_test(event: dict) -> bool:
    """True for the portal's synthetic 'Test Webhook' deliveries — skip these."""
    return event.get("event_type") == "TEST"


def tickers(event: dict) -> list[str]:
    """The focal asset tickers you need to predict on."""
    return [asset["identifier_value"] for asset in event.get("focal_assets", [])]


def to_submission(event_id: str, predictions: list[dict]) -> dict:
    """Shape the POST /predictions request body."""
    return {"event_id": event_id, "predictions": predictions}


def log_deadline(event: dict) -> None:
    """Print the prediction deadline and seconds remaining, best-effort."""
    deadline = event.get("prediction_deadline")
    if not deadline:
        return
    try:
        dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        remaining = (dt - datetime.now(timezone.utc)).total_seconds()
        print(f"[event {event.get('event_id')}] deadline {deadline} (~{remaining:.0f}s left)")
    except ValueError:
        print(f"[event {event.get('event_id')}] deadline {deadline}")
