from __future__ import annotations

from typing import Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph

from .config import Settings
from .openrouter import OpenRouterClient
from .prompts import FINAL_SYSTEM, PLANNER_SYSTEM
from .schemas import RouteDecision
from .tools import RememberTool, safe_calc, wiki_summary
from .util import extract_first_json_object


class AgentState(TypedDict, total=False):
    # Conversation
    messages: list[BaseMessage]

    # Persistent memory (profile facts)
    profile: dict[str, str]

    # Per-turn scratchpad with tool outputs
    scratchpad: list[dict[str, Any]]

    # Planner state
    step: int
    router: dict[str, Any]

    # IO
    user_input: str
    final_answer: str


def build_app() -> Any:
    settings = Settings.load()
    llm = OpenRouterClient(
        api_key=settings.openrouter_api_key,
        model=settings.openrouter_model,
        app_url=settings.openrouter_app_url,
        app_name=settings.openrouter_app_name,
    )
    remember = RememberTool(llm=llm)

    def ingest(state: AgentState) -> AgentState:
        text = (state.get("user_input") or "").strip()
        messages = list(state.get("messages") or [])
        messages.append(HumanMessage(content=text))

        # Reset per-turn scratchpad + step counter.
        return {
            "messages": messages,
            "scratchpad": [],
            "step": 0,
        }

    def planner(state: AgentState) -> AgentState:
        step = int(state.get("step") or 0) + 1

        # Hard guardrail: if planner loops too much, force final.
        if step > settings.max_steps:
            decision = RouteDecision(next="final", tool_input="", reason="step_cap_reached").model_dump()
            return {"step": step, "router": decision}

        last_user = ""
        msgs = state.get("messages") or []
        if msgs and isinstance(msgs[-1], HumanMessage):
            last_user = msgs[-1].content or ""

        profile = state.get("profile") or {}
        scratch = state.get("scratchpad") or []

        planner_user = {
            "user_message": last_user,
            "profile": profile,
            "scratchpad": scratch,
        }

        messages = [
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": str(planner_user)},
        ]

        # Retry once if JSON invalid.
        for attempt in range(2):
            text = llm.chat_completion(messages, temperature=0.0, response_format_json=True)
            try:
                payload = extract_first_json_object(text)
                decision = RouteDecision.model_validate(payload).model_dump()
                return {"step": step, "router": decision}
            except Exception:
                if attempt == 0:
                    # Strengthen instruction.
                    messages.append(
                        {
                            "role": "user",
                            "content": "Your previous output was invalid. Output ONLY a valid JSON object with keys next/tool_input/reason.",
                        }
                    )
                    continue
                # Fallback heuristic routing.
                u = last_user.lower().strip()
                if any(tok in u for tok in ["my name is", "i live", "i am from", "call me", "i prefer"]):
                    decision = RouteDecision(next="remember", tool_input=last_user, reason="heuristic_profile_fact").model_dump()
                elif any(ch.isdigit() for ch in u) and any(op in u for op in ["+", "-", "*", "/", "(", ")", "^"]):
                    decision = RouteDecision(next="calc", tool_input=last_user, reason="heuristic_math").model_dump()
                elif any(u.startswith(w) for w in ["who", "what", "when", "where", "tell me about", "explain"]):
                    decision = RouteDecision(next="search", tool_input=last_user, reason="heuristic_search").model_dump()
                else:
                    decision = RouteDecision(next="final", tool_input="", reason="heuristic_final").model_dump()

                return {"step": step, "router": decision}

    def tool_search(state: AgentState) -> AgentState:
        decision = state.get("router") or {}
        query = (decision.get("tool_input") or "").strip()
        if not query:
            query = (state.get("messages") or [])[-1].content.strip()

        # For Wikipedia summary, "best effort": query as title.
        result = wiki_summary(query)

        scratch = list(state.get("scratchpad") or [])
        scratch.append({"tool": "search", "input": query, "result": result})

        return {"scratchpad": scratch}

    def tool_calc(state: AgentState) -> AgentState:
        decision = state.get("router") or {}
        expr = (decision.get("tool_input") or "").strip()
        if not expr:
            expr = (state.get("messages") or [])[-1].content.strip()

        scratch = list(state.get("scratchpad") or [])

        try:
            value = safe_calc(expr)
            scratch.append({"tool": "calc", "input": expr, "result": {"value": value}})
        except Exception as e:
            scratch.append({"tool": "calc", "input": expr, "result": {"error": str(e)}})

        return {"scratchpad": scratch}

    def tool_remember(state: AgentState) -> AgentState:
        decision = state.get("router") or {}
        msg = (decision.get("tool_input") or "").strip()
        if not msg:
            msg = (state.get("messages") or [])[-1].content.strip()

        profile = dict(state.get("profile") or {})
        scratch = list(state.get("scratchpad") or [])

        facts = remember.extract_facts(msg)
        profile.update(facts)

        scratch.append({"tool": "remember", "input": msg, "result": {"facts": facts}})

        return {"profile": profile, "scratchpad": scratch}

    def final_node(state: AgentState) -> AgentState:
        msgs = list(state.get("messages") or [])
        profile = state.get("profile") or {}
        scratch = state.get("scratchpad") or []

        last_user = ""
        if msgs and isinstance(msgs[-1], HumanMessage):
            last_user = msgs[-1].content or ""

        final_user = {
            "user_message": last_user,
            "profile": profile,
            "scratchpad": scratch,
        }

        messages = [
            {"role": "system", "content": FINAL_SYSTEM},
            {"role": "user", "content": str(final_user)},
        ]

        text = llm.chat_completion(messages, temperature=0.2, response_format_json=False)
        answer = (text or "").strip()

        msgs.append(AIMessage(content=answer))

        # Clear scratchpad after answering (per-turn notes).
        return {"messages": msgs, "final_answer": answer, "scratchpad": []}

    # -----------------------
    # Graph wiring
    # -----------------------
    graph = StateGraph(AgentState)

    graph.add_node("ingest", ingest)
    graph.add_node("planner", planner)
    graph.add_node("search", tool_search)
    graph.add_node("calc", tool_calc)
    graph.add_node("remember", tool_remember)
    graph.add_node("final", final_node)

    graph.set_entry_point("ingest")
    graph.add_edge("ingest", "planner")

    def route_from_planner(state: AgentState) -> str:
        router = state.get("router") or {}
        nxt = router.get("next", "final")
        if nxt not in {"search", "calc", "remember", "final"}:
            return "final"
        return str(nxt)

    graph.add_conditional_edges(
        "planner",
        route_from_planner,
        {
            "search": "search",
            "calc": "calc",
            "remember": "remember",
            "final": "final",
        },
    )

    graph.add_edge("search", "planner")
    graph.add_edge("calc", "planner")
    graph.add_edge("remember", "planner")
    graph.add_edge("final", END)

    checkpointer = InMemorySaver()
    return graph.compile(checkpointer=checkpointer)
