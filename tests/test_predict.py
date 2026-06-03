"""predict() returns the right shape on the no-OpenAI-key fallback path.

With OPENAI_API_KEY unset, predict() must still return one well-formed prediction
per focal asset (the 0.5 baseline) without making any network calls. We stub the
disclosure fetch so the test is fully offline.
"""

from __future__ import annotations

import predict as predict_module


SAMPLE_EVENT = {
    "id": "evt_test_1",
    "event_id": "11111111-1111-1111-1111-111111111111",
    "event_type": "EARNINGS_RELEASE",
    "timing_category": "SCHEDULED",
    "event_datetime": "2026-01-15T21:00:00Z",
    "focal_assets": [
        {"identifier_type": "TICKER", "identifier_value": "AAPL"},
        {"identifier_type": "TICKER", "identifier_value": "MSFT"},
    ],
    "information_url": "https://example.test/disclosure",
    "prediction_deadline": "2026-01-15T21:05:00Z",
}


class _FakeResponse:
    def raise_for_status(self) -> None:  # noqa: D401 - stub
        return None

    def json(self) -> dict:
        return {"summary": "Quarterly results in line with expectations."}


def test_predict_fallback_shape(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(predict_module.httpx, "get", lambda *a, **k: _FakeResponse())

    preds = predict_module.predict(SAMPLE_EVENT)

    assert isinstance(preds, list)
    assert len(preds) == len(SAMPLE_EVENT["focal_assets"])
    returned = {p["identifier_value"] for p in preds}
    assert returned == {"AAPL", "MSFT"}
    for p in preds:
        assert set(p) == {"identifier_value", "predicted_percentile"}
        assert 0.0 <= p["predicted_percentile"] <= 1.0
        assert p["predicted_percentile"] == 0.5  # fallback baseline
