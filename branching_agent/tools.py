from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests

from .openrouter import OpenRouterClient
from .prompts import REMEMBER_SYSTEM
from .schemas import ProfileFacts
from .util import extract_first_json_object


# -----------------------
# Tool: Wikipedia Summary
# -----------------------

def wiki_summary(title: str, *, timeout_s: int = 20) -> dict[str, str]:
    """
    Wikipedia REST summary tool.
    API: https://en.wikipedia.org/api/rest_v1/page/summary/{title}
    """
    safe_title = quote(title.strip().replace(" ", "_"))
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{safe_title}"

    headers = {
        "Accept": "application/json",
        # Wikipedia may block requests without a UA.
        "User-Agent": "sdt-212-branching-agent/1.0 (educational; contact: none)",
        # Some Wikimedia endpoints prefer Api-User-Agent too.
        "Api-User-Agent": "sdt-212-branching-agent/1.0 (educational; contact: none)",
    }

    try:
        r = requests.get(url, timeout=timeout_s, headers=headers)
    except Exception as e:
        return {
            "title": title,
            "extract": f"Network error while calling Wikipedia: {e}",
            "url": url,
        }

    if r.status_code == 404:
        return {
            "title": title,
            "extract": f"No Wikipedia page found for '{title}'. Try a different title.",
            "url": url,
        }

    # Handle common blocks / throttles gracefully
    if r.status_code in (403, 429):
        return {
            "title": title,
            "extract": f"Wikipedia API returned {r.status_code}. Try again later or use a different query.",
            "url": url,
        }

    if r.status_code >= 400:
        return {
            "title": title,
            "extract": f"Wikipedia API error {r.status_code}: {r.text[:200]}",
            "url": url,
        }

    data = r.json()
    extract = (data.get("extract") or "").strip()
    page = (data.get("content_urls", {}) or {}).get("desktop", {}) or {}
    page_url = page.get("page") or url

    return {"title": data.get("title") or title, "extract": extract, "url": page_url}



# -----------------------
# Tool: Safe Calculator
# -----------------------

_ALLOWED_CHARS = re.compile(r"^[0-9+\-*/().%\s^]+$")

class _SafeEval(ast.NodeVisitor):
    """
    AST-based safe evaluator for arithmetic expressions.
    Allowed:
      - numbers
      - +, -, *, /, //, %, **, parentheses
      - unary +/-.

    Notes:
      - '^' is mapped to '**' before parsing (common student expectation).
    """

    def __init__(self) -> None:
        self.node_count = 0
        self.max_nodes = 64

    def _bump(self) -> None:
        self.node_count += 1
        if self.node_count > self.max_nodes:
            raise ValueError("Expression too complex.")

    def visit(self, node: ast.AST) -> Any:
        self._bump()
        return super().visit(node)

    def visit_Expression(self, node: ast.Expression) -> float:
        return float(self.visit(node.body))

    def visit_Constant(self, node: ast.Constant) -> float:
        if isinstance(node.value, (int, float)):
            if math.isfinite(float(node.value)):
                return float(node.value)
        raise ValueError("Only finite numbers are allowed.")

    def visit_UnaryOp(self, node: ast.UnaryOp) -> float:
        val = float(self.visit(node.operand))
        if isinstance(node.op, ast.UAdd):
            return +val
        if isinstance(node.op, ast.USub):
            return -val
        raise ValueError("Unary operator not allowed.")

    def visit_BinOp(self, node: ast.BinOp) -> float:
        left = float(self.visit(node.left))
        right = float(self.visit(node.right))

        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise ValueError("Division by zero.")
            return left / right
        if isinstance(node.op, ast.FloorDiv):
            if right == 0:
                raise ValueError("Division by zero.")
            return left // right
        if isinstance(node.op, ast.Mod):
            if right == 0:
                raise ValueError("Modulo by zero.")
            return left % right
        if isinstance(node.op, ast.Pow):
            # Keep exponentiation bounded.
            if abs(right) > 1000:
                raise ValueError("Exponent too large.")
            return left ** right

        raise ValueError("Binary operator not allowed.")

    def generic_visit(self, node: ast.AST) -> Any:
        raise ValueError(f"Disallowed syntax: {type(node).__name__}")


def safe_calc(expr: str) -> str:
    raw = (expr or "").strip()
    if not raw:
        raise ValueError("Empty expression.")

    if len(raw) > 120:
        raise ValueError("Expression too long.")

    if not _ALLOWED_CHARS.match(raw):
        raise ValueError("Expression contains disallowed characters.")

    # Treat '^' as exponentiation (not XOR).
    normalized = raw.replace("^", "**")

    tree = ast.parse(normalized, mode="eval")
    evaluator = _SafeEval()
    result = evaluator.visit(tree)

    # Pretty formatting: avoid trailing .0 when integer-ish.
    if abs(result - round(result)) < 1e-12:
        return str(int(round(result)))
    return str(result)


# -----------------------
# Tool: Remember Facts (LLM Extraction)
# -----------------------

@dataclass(frozen=True)
class RememberTool:
    llm: OpenRouterClient

    def extract_facts(self, user_message: str) -> dict[str, str]:
        messages = [
            {"role": "system", "content": REMEMBER_SYSTEM},
            {"role": "user", "content": user_message.strip()},
        ]

        # Try JSON response_format first for better reliability.
        text = self.llm.chat_completion(messages, temperature=0.0, response_format_json=True)
        payload = extract_first_json_object(text)

        facts = ProfileFacts.model_validate(payload).facts
        # Normalize values to short strings.
        normalized: dict[str, str] = {}
        for k, v in facts.items():
            k2 = str(k).strip().lower().replace(" ", "_")[:50]
            v2 = str(v).strip()[:200]
            if k2 and v2:
                normalized[k2] = v2
        return normalized
