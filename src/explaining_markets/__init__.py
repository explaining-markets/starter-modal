"""Plumbing for the Explaining Markets Modal starter.

You almost never need to touch this package — edit ``predict.py`` instead.

Modules:
  config               — reads EM_* / OPENAI_* environment variables
  webhook_verification — vendored HMAC-SHA256 verifier (stdlib only)
  client               — submits predictions to the competition API
  event_utils          — small helpers for working with event payloads
"""

from explaining_markets.webhook_verification import (
    WebhookVerificationError,
    verify_webhook,
)

__all__ = ["WebhookVerificationError", "verify_webhook"]
