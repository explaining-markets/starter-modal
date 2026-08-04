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
from typing import Literal

import httpx
from openai import OpenAI
from pydantic import BaseModel, Field

from explaining_markets.config import openai_model

_openai: OpenAI | None = None  # lazy: importing this file must not require a key
_openai_warned = False         # one-shot warning when no key is configured

# Timeouts, sized against the 5-minute prediction window that opens when your
# handler ACKs the webhook. Worst case is 15 + (120 x 2) + 15 = 270s, which
# fits with ~30s to spare. Nothing upstream retries a failed prediction — once
# the delivery is ACKed the platform considers it done — so the one retry here
# is the only one you get. Raising either value can push you past the deadline.
SUMMARY_TIMEOUT_SECONDS = 15.0
LLM_TIMEOUT_SECONDS = 120.0
LLM_MAX_RETRIES = 1
STRATEGY_VERSION = "quarterlens-rulebook-ab-v3"


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
    summary = httpx.get(event["information_url"], timeout=SUMMARY_TIMEOUT_SECONDS)
    summary.raise_for_status()
    summary_json = summary.json()

    # One model call per focal asset, in series — so the LLM budget below is
    # per asset, not per event. Today every event carries a single asset; if
    # that changes and you need several, run them concurrently rather than
    # raising the timeout.
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
    """Tested reasoning scaffold and submitted prediction.

    The four categorical diagnostics force a consistent pass over the main
    economic mechanisms before the model emits the only field the competition
    receives: ``predicted_percentile``. This exact scaffold was used in the
    sealed 2026Q2 A/B evaluation.
    """

    headline_surprise: Literal["negative", "mixed", "positive", "unknown"]
    forward_outlook: Literal["negative", "mixed", "positive", "unknown"]
    earnings_quality: Literal["low", "mixed", "high", "unknown"]
    expectations_bar: Literal["low", "normal", "high", "unknown"]
    key_driver: str = Field(max_length=180)
    predicted_percentile: float = Field(ge=0.0, le=1.0)


SYSTEM_PROMPT = """\
You are a senior event-driven equity analyst. Predict the focal stock's
next-day abnormal-return percentile across this quarter's earnings events:
0 is the worst reaction, 0.50 is the median, and 1 is the best.

Core directive: assume ordinary good news is priced in. Public companies are
expected to grow, beat estimates, and improve margins. Rank the *unexpected
change in expectations*, not the absolute quality of the company or quarter.
An incremental beat-and-raise is usually 0.40-0.60; strong results with flat
guidance can be sell-the-news. Values above 0.75 or below 0.25 require a
material, clearly unexpected catalyst or disappointment.

Decision order:
1. Quantitative surprise versus consensus and prior guidance, not raw growth.
2. Forward guidance and changes to the trajectory; this normally outweighs
   backward-looking headline EPS.
3. Persistence and quality: recurring operations beat one-time accounting,
   mix, tax, commodity, revaluation, or timing benefits.
4. Expectations risk: premium/high-growth stocks need immediate delivery.
   Discount long-dated roadmap promises. Routine financial-sector buybacks
   are maintenance, not a catalyst.
5. Contradictions and vetoes: do not average away a concrete forward cut,
   worsening unit economics, execution failure, churn, or demand deceleration
   merely because other bullets sound positive.

Validated rulebook patterns from prior data:
- Pre-profit revenue growth above 30% with flat/worsening operating losses:
  usually 0.10-0.20, especially if growth is peaking.
- Cautionary forward language such as "aggressive consensus", "gradual
  recovery", or guiding to the low end: 0.35-0.50. A >50% growth deceleration
  or one-time-inflated EPS with no forward acceleration can justify 0.10-0.25.
- Record margins driven by non-recurring benefits plus an execution failure
  and a major geography down >15%: 0.10-0.20 despite positive demand language.
- For telecom/utilities, rising churn can cap the result near 0.50 unless
  offset by a distinctly stronger cash-flow or guidance catalyst.

Use the full cross-sectional range when warranted. Do not mechanically pull
every answer toward 0.50: ranking ability, not mean calibration, is the goal.
"""


def _summary_text(summary: dict | object) -> str:
    """Render a disclosure bundle as clean facts instead of raw JSON.

    The competition information URL returns a bundle whose ``items`` include a
    ``kind == "facts"`` entry with a list of contemporaneous fact bullets. This
    matches the official research baseline's input format. Keep backward
    compatibility with older ``{"summary": "..."}`` payloads and preserve a
    JSON fallback for unexpected schemas.
    """
    if not isinstance(summary, dict):
        return json.dumps(summary)

    direct_summary = summary.get("summary")
    if isinstance(direct_summary, str) and direct_summary.strip():
        return direct_summary.strip()

    bundle = summary.get("disclosure")
    if not isinstance(bundle, dict):
        bundle = summary
    items = bundle.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict) or item.get("kind") != "facts":
                continue
            content = item.get("content")
            if isinstance(content, list) and content:
                return "\n".join(f"- {fact}" for fact in content)

    return json.dumps(summary)


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
        # picks up OPENAI_API_KEY from env
        _openai = OpenAI(
            timeout=LLM_TIMEOUT_SECONDS, max_retries=LLM_MAX_RETRIES
        )

    summary_text = _summary_text(summary)[:8000]

    user_prompt = (
        f"Event type: {event_type}\n"
        f"Ticker: {ticker}\n\n"
        f"Contemporaneous earnings-call facts:\n{summary_text}\n\n"
        "Return the next-day unexpected, market-adjusted return percentile."
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
