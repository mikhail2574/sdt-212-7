from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


import argparse
from datetime import datetime
from dotenv import load_dotenv

from branching_agent import build_app


TESTS = [
    # Memory (remember + recall)
    "My name is Misha and I live in Leipzig. I prefer concise answers.",
    "What's my name and where do I live?",
    # Calculator
    "(2+3)*4.5",
    "2*(3+4)^2",
    # Search (Wikipedia)
    "Ada Lovelace",
    "What is a black hole?",
    # Mixed / should go final without tools if possible
    "Summarize what you know about me from memory in one sentence.",
    # Remember another preference
    "My preference: when you use search, cite sources.",
    # Search again (should cite)
    "What is Kubernetes?",
    # Calc error handling
    "((2+3)/0)",
]


def md_escape(s: str) -> str:
    return s.replace("\n", "\\n")


def main() -> None:
    load_dotenv()

    ap = argparse.ArgumentParser()
    ap.add_argument("--thread-id", default="demo")
    ap.add_argument("--out", default="artifacts/demo_run.md")
    args = ap.parse_args()

    app = build_app()
    cfg = {"configurable": {"thread_id": args.thread_id}}

    lines: list[str] = []
    lines.append("# Demo Run — Branching LangGraph Agent\n")
    lines.append(f"- Date: {datetime.now().isoformat(timespec='seconds')}\n")
    lines.append(f"- thread_id: `{args.thread_id}`\n")
    lines.append("\n---\n")

    for i, user in enumerate(TESTS, start=1):
        lines.append(f"## Test {i}\n")
        lines.append(f"**Input:** `{md_escape(user)}`\n\n")

        # Stream internal states to capture router decisions + tool outputs.
        # We keep this readable: log only router + scratchpad growth.
        last_router = None
        last_scratch_len = 0
        last_final = None

        for state in app.stream({"user_input": user}, config=cfg, stream_mode="values"):
            router = (state.get("router") or None)
            scratch = (state.get("scratchpad") or [])
            final_answer = state.get("final_answer") or None

            if router and router != last_router:
                last_router = router
                lines.append("**Planner:**\n")
                lines.append(f"- next: `{router.get('next')}`\n")
                lines.append(f"- tool_input: `{md_escape(str(router.get('tool_input',''))[:120])}`\n")
                lines.append(f"- reason: `{md_escape(str(router.get('reason',''))[:200])}`\n\n")

            if len(scratch) > last_scratch_len and scratch:
                # Log only when scratchpad grows (tool appended a note).
                entry = scratch[-1]
                lines.append("**Tool note:**\n")
                lines.append(f"- tool: `{entry.get('tool')}`\n")
                lines.append(f"- input: `{md_escape(str(entry.get('input',''))[:120])}`\n")
                lines.append(f"- result: `{md_escape(str(entry.get('result',''))[:600])}`\n\n")

            # Always update the last seen length (including when it gets cleared)
            last_scratch_len = len(scratch)


            if final_answer and final_answer != last_final:
                last_final = final_answer

        # The last run already produced the answer; pull from last_final.
        lines.append("**Final answer:**\n\n")
        lines.append(f"{last_final or ''}\n\n")
        lines.append("---\n")

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("".join(lines))

    print(f"Wrote demo log to: {args.out}")


if __name__ == "__main__":
    main()
