from __future__ import annotations

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
from dotenv import load_dotenv

from branching_agent import build_app


def main() -> None:
    load_dotenv()

    ap = argparse.ArgumentParser()
    ap.add_argument("--thread-id", default="demo")
    args = ap.parse_args()

    app = build_app()
    cfg = {"configurable": {"thread_id": args.thread_id}}

    print(f"REPL started. thread_id={args.thread_id}. Ctrl+C to exit.\n")

    while True:
        try:
            user = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye.")
            return

        if not user:
            continue

        out = app.invoke({"user_input": user}, config=cfg)
        print(f"agent> {out.get('final_answer','')}\n")


if __name__ == "__main__":
    main()
