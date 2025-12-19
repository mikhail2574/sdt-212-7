from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: str
    openrouter_model: str
    openrouter_app_url: str | None
    openrouter_app_name: str | None
    max_steps: int

    @staticmethod
    def load() -> "Settings":
        key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY is missing. Put it into .env")

        model = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini").strip()
        app_url = os.getenv("OPENROUTER_APP_URL", "").strip() or None
        app_name = os.getenv("OPENROUTER_APP_NAME", "").strip() or None

        # Step cap prevents infinite loops / runaway cost.
        max_steps = int(os.getenv("MAX_STEPS", "3"))

        return Settings(
            openrouter_api_key=key,
            openrouter_model=model,
            openrouter_app_url=app_url,
            openrouter_app_name=app_name,
            max_steps=max_steps,
        )
