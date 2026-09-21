# Release-Readiness Copilot — Project Skeleton

Agentic QA/Release-Readiness Copilot built with MCP + LangGraph.

## What's in here so far
- `run.py` — runs the LangGraph pipeline once and prints/saves a report
- `graph/` — single-pass pipeline (Days 5-7): fetch_commits -> fetch_test_results -> classify_failures -> build_report
  - `classifier.py` has the Claude classifier plus an `--offline` rule-based stand-in for testing without an API key
- `data/commits.json`, `data/test_runs.json` — seeded synthetic data (5 commits, 5 test runs)
  mixing a real regression, a flaky test, an infra/env failure, and a clean fix.
- `mcp_server/server.py` — MCP server exposing two tools:
  - `get_recent_commits(limit)`
  - `get_test_results(commit_sha, limit)`

## Setup
```
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
```

## Test the MCP server standalone
```
python mcp_server/server.py
```
Or inspect it interactively (requires Node.js):
```
npx @modelcontextprotocol/inspector python mcp_server/server.py
```

## Run the pipeline
```
python run.py --offline          # no API key, heuristic classifier
export ANTHROPIC_API_KEY=...     # then:
python run.py                    # Claude classifies the failures
```
Model defaults to `claude-sonnet-5`; override with `COPILOT_MODEL`.

## Not built yet
- Agentic loop-back logic (Days 8-9): re-query history when confidence is low
- Structured JSON report + go/no-go recommendation, markdown/HTML render (Day 10)
- Optional PyTorch pre-classifier (Day 11)
