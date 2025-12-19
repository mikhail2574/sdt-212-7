from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import time
import random

import requests


@dataclass(frozen=True)
class OpenRouterClient:
    api_key: str
    model: str
    app_url: str | None = None
    app_name: str | None = None

    def _post(self, headers: dict[str, str], payload: dict[str, Any], timeout_s: int) -> requests.Response:
        return requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout_s,
        )

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        response_format_json: bool = False,
        timeout_s: int = 45,
        max_retries: int = 3,
        backoff_base_s: float = 0.6,
        backoff_max_s: float = 6.0,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.app_url:
            headers["HTTP-Referer"] = self.app_url
        if self.app_name:
            headers["X-Title"] = self.app_name

        base_payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        # We try JSON response_format first (nice), but fall back if OpenRouter/prov rejects it.
        payload_with_rf = dict(base_payload)
        if response_format_json:
            payload_with_rf["response_format"] = {"type": "json_object"}

        def parse_or_raise(r: requests.Response) -> str:
            if r.status_code >= 400:
                # Include body for debugging (OpenRouter usually returns a helpful message here).
                raise RuntimeError(f"OpenRouter HTTP {r.status_code}: {r.text[:800]}")
            data = r.json()
            return data["choices"][0]["message"]["content"]

        # --- First attempt (optionally with response_format)
        try:
            r = self._post(headers, payload_with_rf if response_format_json else base_payload, timeout_s)

            # If provider rejects response_format, you typically get 400. Retry once WITHOUT response_format.
            if response_format_json and r.status_code == 400:
                r2 = self._post(headers, base_payload, timeout_s)
                return parse_or_raise(r2)

            # Transient errors -> handled below by retry loop
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"Transient OpenRouter {r.status_code}", response=r)

            return parse_or_raise(r)

        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as e:
            # Retry only transient errors
            last_err: Exception = e

            for attempt in range(max_retries):
                sleep_s = min(backoff_max_s, backoff_base_s * (2**attempt))
                sleep_s = sleep_s * (0.85 + random.random() * 0.3)  # jitter
                time.sleep(sleep_s)

                try:
                    r = self._post(headers, payload_with_rf if response_format_json else base_payload, timeout_s)

                    if response_format_json and r.status_code == 400:
                        r2 = self._post(headers, base_payload, timeout_s)
                        return parse_or_raise(r2)

                    if r.status_code in (429, 500, 502, 503, 504):
                        raise requests.HTTPError(f"Transient OpenRouter {r.status_code}", response=r)

                    return parse_or_raise(r)

                except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as e2:
                    last_err = e2
                    continue

            raise last_err
