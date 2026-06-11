"""Modal deployment for the Explaining Markets starter.

This is plumbing — you shouldn't need to edit it. It defines a small FastAPI app
with two routes and deploys it as a persistent, public web endpoint:

    GET  /                      health check
    POST /competition/webhook   receive a signed event, verify, predict, submit

Deploy:    modal deploy modal_app.py     (or: uv run modal deploy modal_app.py)
Dev/local: modal serve modal_app.py      (or: uv run modal serve modal_app.py)

The webhook handler is synchronous: it verifies the signature, runs your
`predict()` from predict.py, submits the result, and only then ACKs with 200.
That's safe because your per-event deadline starts when you ACK 200 — so you've
always submitted before the clock starts. Deliveries are deduped on the
`Webhook-Id` header (the server retries on 5xx/timeout, so the same event can
arrive more than once).

Note: we deliberately do NOT use `from __future__ import annotations` here. The
route handlers are defined inside `web()`, and FastAPI must see the real `Request`
/ `Response` classes (not stringized annotations it can't resolve from this nested
scope) to inject them correctly — otherwise it treats `request` as a query
parameter and rejects every delivery with 422.
"""

import modal

app = modal.App("explaining-markets-starter")

image = (
    modal.Image.debian_slim()
    .pip_install("fastapi[standard]", "httpx", "openai", "pydantic")
    .add_local_python_source("explaining_markets", "predict")
)

# Distributed key-value store for idempotency. Persists across redeploys, so a
# retried webhook is never processed twice. Keyed on the Webhook-Id header.
seen_webhooks = modal.Dict.from_name("em-webhook-dedupe", create_if_missing=True)


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("explaining-markets")],
)
@modal.asgi_app()
def web():
    from fastapi import FastAPI, Request, Response

    from explaining_markets import WebhookVerificationError, verify_webhook
    from explaining_markets.client import submit_predictions
    from explaining_markets.config import Config
    from explaining_markets.event_utils import is_test, log_deadline
    from predict import predict

    api = FastAPI(title="Explaining Markets starter")

    @api.get("/")
    def health() -> dict:
        return {"ok": True, "service": "explaining-markets-starter"}

    @api.post("/competition/webhook")
    async def competition_webhook(request: Request) -> Response:
        config = Config.from_env()

        raw_body = await request.body()  # raw bytes — never request.json()
        try:
            event = verify_webhook(
                raw_body=raw_body,
                headers=request.headers,
                secret=config.webhook_secret,
            )
        except WebhookVerificationError as exc:
            return Response(content=str(exc), status_code=401)

        # Idempotency: the Webhook-Id header (== event["id"]) is stable across
        # retries. Skip anything we've already handled.
        webhook_id = event.get("id")
        if webhook_id and webhook_id in seen_webhooks:
            return Response(status_code=200)

        # The portal's "Test Webhook" button sends a synthetic TEST event — ACK
        # it so the smoke test passes, but don't predict or submit.
        if is_test(event):
            if webhook_id:
                seen_webhooks[webhook_id] = True
            return Response(status_code=200)

        log_deadline(event)
        predictions = predict(event)
        submit_predictions(
            event_id=event["event_id"],
            predictions=predictions,
            config=config,
        )

        if webhook_id:
            seen_webhooks[webhook_id] = True
        return Response(status_code=200)

    return api
