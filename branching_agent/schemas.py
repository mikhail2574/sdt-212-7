from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


NextNode = Literal["search", "calc", "remember", "final"]


class RouteDecision(BaseModel):
    next: NextNode = Field(..., description="Next node to execute.")
    tool_input: str = Field("", description="Input for the next tool node.")
    reason: str = Field("", description="Short reason for this routing choice.")


class ProfileFacts(BaseModel):
    # Keep it flexible: store arbitrary simple facts as strings.
    facts: dict[str, str] = Field(default_factory=dict)
