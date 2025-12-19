from __future__ import annotations

import json


def extract_first_json_object(text: str) -> dict:
    """
    Robustly extract the first JSON object from a model response.
    Strips common code fences and then searches for the outermost { ... }.
    """
    if not text:
        raise ValueError("Empty text, cannot extract JSON.")

    cleaned = text.strip()

    # Strip code fences if present.
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        # Some models emit ```json\n{...}\n```
        cleaned = cleaned.replace("json\n", "", 1).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"Could not locate JSON object in: {text[:200]}")

    payload = cleaned[start : end + 1]
    return json.loads(payload)
