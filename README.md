# Branching LangGraph Agent — Quick Research Buddy

A multi-step LangGraph agent that:

- routes user inputs via an LLM planner/router to tools (`search`, `calc`, `remember`)
- maintains memory across turns via `InMemorySaver` + `thread_id`
- keeps a scratchpad of tool notes
- composes a final answer using memory + scratchpad

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: set OPENROUTER_API_KEY
```
