# Advanced notes

The hero README keeps the path to a first deploy as short as possible. This file
collects everything intentionally left out of it.

## The webhook verifier is vendored

`explaining_markets/webhook_verification.py` is a verbatim copy of the
competition's reference verifier (stdlib-only, zero runtime dependencies). It's
vendored — not installed from PyPI — so the starter is self-contained.

If the competition later publishes the verifier as a package, you can delete the
vendored file and depend on the pinned package instead, importing
`verify_webhook` / `WebhookVerificationError` from there. The frozen test vectors
in `tests/test_vectors.json` will keep passing either way, since both
implementations pin to the same values.

## Why synchronous (no queue) in v1

`modal_app.py` verifies → predicts → submits → ACKs 200, all in one request. Your
per-event deadline starts when you ACK 200, so you've always submitted before the
clock starts. This is the simplest correct design.

If your `predict()` becomes slow (long LLM chains, multiple tools) and webhook
deliveries start timing out, move to a queue: ACK 200 immediately, push the
verified event onto a `modal.Queue`, and process + submit in a separate Modal
function. Keep the `Webhook-Id` dedupe guard — retries still happen.

## Idempotency

Deliveries are deduped on the `Webhook-Id` header (equal to `event["id"]`) via a
`modal.Dict` that persists across redeploys. The server retries on 5xx and
timeout, so the same event can arrive more than once; the dedupe guard makes
reprocessing a no-op.

## Not included by design

No Docker, Terraform, GitHub Actions, custom CLI, or multiple deployment modes —
Modal's persistent deployments, public web endpoints, and Secrets cover the
starter. Add those only if your own setup needs them.
