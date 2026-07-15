"""★ THIS IS THE ONLY FILE YOU NEED TO EDIT. ★

`predict(event)` is called once per competition event, after the webhook has
already been verified for you. Return one prediction per focal asset. Everything
else in this repo (webhook verification, dedupe, submission) is plumbing.

The default implementation asks an OpenAI model for a calibrated percentile. If
`OPENAI_API_KEY` is not set, it returns a 0.5 baseline so the full deploy →
receive → submit round-trip still works without burning credits. Replace the body
of `predict` with whatever strategy you like — the only contract is the return
shape documented below.
"""

from __future__ import annotations

import json
import os

import httpx
from openai import OpenAI
from pydantic import BaseModel, Field

from explaining_markets.config import openai_model

_openai: OpenAI | None = None  # lazy: importing this file must not require a key
_openai_warned = False         # one-shot warning when no key is configured


def predict(event: dict) -> list[dict]:
    """Return predictions for one Explaining Markets event.

    `event` is the verified webhook payload. Useful fields:
      event["event_type"]          e.g. "EARNINGS_RELEASE"
      event["focal_assets"]        list of {"identifier_type", "identifier_value"}
      event["information_url"]     short-lived signed URL with the event summary JSON
      event["prediction_deadline"] ISO timestamp; submit before this fires

    Required return: a list of dicts, one per focal asset:
      [{"identifier_value": "AAPL", "predicted_percentile": 0.71}, ...]

    `predicted_percentile` is a float in [0, 1] — where you predict the asset's
    next-day abnormal (market-adjusted) return will rank across all of the
    quarter's event outcomes: 0 = the quarter's most negative reaction,
    0.50 = median, 1 = its most positive. It's a cross-sectional rank across the
    quarter's events, not a percentile within the asset's own history.
    """
    summary = httpx.get(event["information_url"], timeout=10.0)
    summary.raise_for_status()
    summary_json = summary.json()

    return [
        {
            "identifier_value": asset["identifier_value"],
            "predicted_percentile": _ask_llm(
                summary=summary_json,
                ticker=asset["identifier_value"],
                event_type=event["event_type"],
            ),
        }
        for asset in event["focal_assets"]
    ]


# ----------------------------------------------------------------------
# Default strategy: a single calibrated LLM call per asset.
# Swap this out, or rewrite `predict` entirely, to enter your own model.
# ----------------------------------------------------------------------


class Prediction(BaseModel):
    """Structured response shape for the LLM call.

    The `Field(ge=0, le=1)` constraint flows through into the JSON schema OpenAI's
    structured-outputs mode enforces during decoding, so the model is guaranteed to
    return a percentile in [0, 1] — no manual clamping or fallback parsing needed.
    """

    predicted_percentile: float = Field(ge=0.0, le=1.0)


SYSTEM_PROMPT = """\
You are a senior equity analyst predicting how a stock will react to an event.

Predict a single percentile in [0, 1] for how the focal asset's next-day
abnormal return will rank across all of the quarter's event outcomes:
0 = the quarter's most negative reaction, 0.50 = median, 1 = its most positive.
The relevant return is the *unexpected*, market-adjusted return — a
great-but-fully-priced-in beat is not a top-decile event.

Calibration discipline:
- Long-run base rates: about 25% of events land "up" (>0.75), 50% "neutral"
  (0.25-0.75), 25% "down" (<0.25). Default toward 0.40-0.60 when signals are
  mixed or modest.
- Reserve values above 0.80 or below 0.20 for cases with unambiguous,
  multi-signal evidence. Do not exceed 0.90 or fall below 0.10 without
  overwhelming, lopsided evidence.
- Tone alone (confident vs hedging language) should move you no more than
  ~0.03 absent quantitative confirmation.
"""


def _ask_llm(*, summary: dict, ticker: str, event_type: str) -> float:
    """Ask the configured model for a calibrated percentile via structured outputs.

    Returns the model's `predicted_percentile`. Falls back to 0.5 if no
    `OPENAI_API_KEY` is configured or the model refuses; the [0, 1] bound is
    enforced by the JSON schema, not by us.
    """
    global _openai, _openai_warned
    if not os.environ.get("OPENAI_API_KEY"):
        if not _openai_warned:
            print(
                "[WARN] OPENAI_API_KEY not set — submitting 0.5 placeholder. "
                "Set the key (or edit predict.py) for real predictions."
            )
            _openai_warned = True
        return 0.5
    if _openai is None:
        _openai = OpenAI()  # picks up OPENAI_API_KEY from env

    summary_text = summary.get("summary") if isinstance(summary, dict) else None
    if not summary_text:
        summary_text = json.dumps(summary)
    summary_text = summary_text[:8000]

    user_prompt = (
        f"Event type: {event_type}\n"
        f"Ticker: {ticker}\n\n"
        f"Event summary:\n{summary_text}\n\n"
        "Weigh, in roughly this order:\n"
        "  1. Quantitative surprise vs expectations — revenue, EPS, segment metrics.\n"
        "  2. Guidance / outlook — raises, holds, cuts vs the prior trajectory.\n"
        "  3. Strategic shifts — product launches, M&A, capital allocation, leadership.\n"
        "  4. Tone and confidence in management commentary (small weight).\n"
        "  5. Risks called out — regulatory, supply chain, demand, competition.\n\n"
        f"Predict the next-day unexpected-return percentile for {ticker}."
    )

    resp = _openai.chat.completions.parse(
        model=openai_model(),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format=Prediction,
    )
    parsed = resp.choices[0].message.parsed
    if parsed is None:
        return 0.5  # model refused; competition expects a number
    return parsed.predicted_percentile
