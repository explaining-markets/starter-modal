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

## Credentials: `.env` vs Modal's secret store

By default the app reads credentials from your local `.env` at deploy time via
`modal.Secret.from_dotenv(__file__)` in `modal_app.py`. That keeps setup to "fill
in a file and deploy" — no secret-management command to copy.

If you'd rather keep credentials in Modal's secret store (e.g. for CI, or to avoid
a local file), create a named secret once:

```bash
uv run modal secret create explaining-markets \
  EM_API_KEY=... EM_WEBHOOK_SECRET=whsec_... OPENAI_API_KEY=...
```

then swap the decorator in `modal_app.py`:

```python
secrets=[modal.Secret.from_name("explaining-markets")]
```

## Webhook path and URL

The handler is registered on both `POST /` (primary) and `POST /competition/webhook`
(alias), so either URL works. We serve it at the root so the URL Modal prints on
deploy *is* your webhook URL, with nothing to append.

The URL's subdomain comes from `@modal.asgi_app(label="explaining-markets")`, which
makes it `https://{your-workspace}--explaining-markets.modal.run` instead of the
longer default. Change the `label` to change the subdomain.

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
