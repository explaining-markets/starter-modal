# Explaining Markets — Modal starter

A minimal [Modal](https://modal.com) starter for the Explaining Markets
competition. Deploy a signed webhook receiver, verify events, and submit
predictions from Python.

**Edit `predict.py`. Everything else is plumbing.**

```
predict.py                 ← your strategy lives here
modal_app.py               ← FastAPI app + webhook handler (don't touch)
explaining_markets/        ← config, verifier, API client, helpers (plumbing)
tests/                     ← predict shape + webhook verification
```

When an event fires, the competition sends a **signed webhook** to your URL. This
app verifies the signature, calls your `predict(event)`, and POSTs the result back
to the API — all before it ACKs the webhook, so you're always inside your deadline.

---

## Quickstart

### 0. Install

```bash
uv sync                       # (or: python -m venv .venv && pip install -e ".[dev]")
```

You'll also need a [Modal account](https://modal.com) and the CLI authenticated:

```bash
uv run modal setup            # (or: modal setup)
```

### 1. Sign up and create a submission

In the [portal](https://explainingmarkets.ai), complete your profile, then create
a submission and give it a public name. It stays in `draft` until both credentials
and a webhook URL are set.

### 2. Get your credentials

On the submission's **Credentials** tab, generate your **API key** and **signing
secret** (`whsec_...`). They're shown **once** — store them now; rotation is the
recovery path. The API key authenticates your prediction requests; the signing
secret verifies incoming webhooks.

### 3. Store them as a Modal Secret

Create a Modal Secret named `explaining-markets` carrying your credentials:

```bash
uv run modal secret create explaining-markets \
  EM_API_KEY=...           \
  EM_WEBHOOK_SECRET=whsec_... \
  OPENAI_API_KEY=...          # optional; omit to use the 0.5 baseline
# (or drop the `uv run` prefix if you installed with pip)
```

`EM_API_BASE_URL` defaults to the beta API and `OPENAI_MODEL` to `gpt-5.4-nano`;
add them to the secret only if you want to override. See `.env.example` for the
full list.

### 4. Deploy

```bash
uv run modal deploy modal_app.py     # (or: modal deploy modal_app.py)
```

Modal prints a persistent public URL. Your webhook endpoint is that URL with
`/competition/webhook` appended. The deployment keeps running after you close your
laptop.

### 5. Set your webhook URL and smoke-test

On the submission's **Webhook** tab, paste your endpoint URL
(`https://...modal.run/competition/webhook`). Once credentials and a webhook URL
are both set, the submission becomes `active`.

Click **Test Webhook** to send a synthetic delivery. The handler verifies it,
sees `event_type == "TEST"`, and ACKs with 200 without submitting. The **Health**
tab shows rolling delivery counters so you can confirm the round trip.

### 6. Edit `predict.py`

This is the only file you edit. `predict(event)` is called once per event after
verification; return one prediction per focal asset:

```python
def predict(event: dict) -> list[dict]:
    return [
        {"identifier_value": "AAPL", "predicted_percentile": 0.92},
    ]
```

`predicted_percentile` is a float in `[0, 1]` — where you think the asset's
next-day *unexpected* return lands in its historical distribution (0 = worst,
0.50 = median, 1 = best). The default implementation asks an OpenAI model for a
calibrated percentile; with no `OPENAI_API_KEY` set it returns `0.5` so the
round-trip works before you plug in your real model.

Re-deploy after editing:

```bash
uv run modal deploy modal_app.py
```

You can POST again before the deadline to update — the last accepted POST wins.

---

## Run the tests

```bash
uv run pytest                 # (or: pytest)
```

Both suites run fully offline — no API key, no network. One checks that
`predict()` returns the right shape; the other verifies the webhook verifier
against the competition's frozen, published signing vectors.

---

## Troubleshooting

Webhook signatures cover the **exact bytes** the server sent. The most common
mistakes (all handled correctly by `modal_app.py`, but worth knowing if you
customize it):

- **Re-serializing the body before verification.** `json.dumps(json.loads(body))`
  reorders keys and adds spaces — verification fails. Always verify the raw bytes.
- **Using `request.json()` instead of `request.body()`.** Same issue: the parsed
  dict is no longer the original byte string. The handler reads `await
  request.body()`.
- **Ignoring the timestamp.** The verifier defaults to a 5-minute tolerance. If
  your clock drifts, pass `tolerance_seconds=` to `verify_webhook`.
- **Not deduping on `Webhook-Id`.** The server retries on 5xx and timeout, so the
  same event can arrive more than once. This app dedupes via a `modal.Dict`.

If predictions aren't landing: confirm the `explaining-markets` Modal Secret has
`EM_API_KEY` and `EM_WEBHOOK_SECRET`, that the submission is `active`, and that
you pasted the `/competition/webhook` URL (not the bare deploy URL) into the
portal. The **Health** tab's prediction counter should increment for non-TEST
events.

For queue-based processing, swapping the vendored verifier for a published
package, and other extensions, see [`docs/advanced.md`](docs/advanced.md).
