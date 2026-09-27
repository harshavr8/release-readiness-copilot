# Release-Readiness Copilot — Project Skeleton

Agentic QA/Release-Readiness Copilot built with MCP + LangGraph.

## What's in here so far
- `run.py` — runs the LangGraph pipeline once and prints/saves a report
- `graph/` — single-pass pipeline (Days 5-7): fetch_commits -> fetch_test_results -> classify_failures -> build_report
  - `classifier.py` has the Claude classifier plus an `--offline` rule-based stand-in for testing without an API key
  - Loop-back (Days 8-9): a classification is flagged for review if its confidence is
    <= 75%, OR its reasoning contains hedging language ("but", "however", "possibly", ...) -
    catches cases where the model scored itself confident while its own explanation was
    still arguing with itself. Flagged items route through `gather_more_context` ->
    `reclassify_failures`, re-asked with one extra piece of evidence: diffs of commits that
    landed *after* the failing one, so it can catch "this was a pre-existing bug the next
    commit already fixes" cases a single-pass, per-commit classifier can't see. Capped at
    1 loop (`MAX_LOOPS` in `state.py`). See `needs_review()` in `graph/nodes.py`.

## Known limitation
Claude's classifications aren't perfectly stable run-to-run on the same seeded data - e.g.
the gateway retry-logic test has flipped between "flaky" and "caused_by_change" across runs,
both times with a defensible but hedgy explanation. Worth being upfront about in an interview:
the loop-back is the mitigation for this, not a claim that classification is deterministic.
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

- `graph/report.py` — Day 10: turns classifications into a scored, structured report.
  Risk score and go/no-go are a deterministic formula over the classifications, NOT
  another LLM call - see `POINTS` and `_recommendation()` for the exact rule. Each run
  saves both `reports/report-<timestamp>.json` (for tooling / CI gates) and
  `reports/report-<timestamp>.md` (for the demo/screenshot).

## Not built yet
- Optional PyTorch pre-classifier (Day 11)
