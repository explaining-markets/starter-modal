"""Configuration read from the environment.

In deployment these come from your local ``.env`` file, which Modal loads at
deploy time (see ``.env.example`` and ``modal_app.py``).

Required:
  EM_API_KEY         your submission's API key; sent as the X-API-Key header
  EM_WEBHOOK_SECRET  your signing secret (whsec_...); verifies incoming webhooks

Optional:
  EM_API_BASE_URL    API base URL (default: production)
  OPENAI_API_KEY     when set, predict.py makes real LLM calls; otherwise it
                     falls back to a 0.5 baseline so the round-trip still works
  OPENAI_MODEL       model name for predict.py (default: gpt-5.4-nano)
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_API_BASE_URL = "https://api.explainingmarkets.ai/v1"
DEFAULT_OPENAI_MODEL = "gpt-5.4-nano"


@dataclass(frozen=True)
class Config:
    api_key: str
    webhook_secret: str
    api_base_url: str

    @classmethod
    def from_env(cls) -> "Config":
        """Load and validate required config. Raises if a required var is missing."""
        return cls(
            api_key=_require("EM_API_KEY"),
            webhook_secret=_require("EM_WEBHOOK_SECRET"),
            api_base_url=os.environ.get("EM_API_BASE_URL", DEFAULT_API_BASE_URL).rstrip("/"),
        )


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. Add it to your .env file "
            f"(copy .env.example to .env), then re-deploy. See the README."
        )
    return value


def openai_model() -> str:
    return os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
