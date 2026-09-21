"""Node 3 brains: classify each failing test.

Two modes:
  - LLM (default when ANTHROPIC_API_KEY is set): Claude via langchain-anthropic,
    with structured output so we get validated objects back.
  - offline (no key, or --offline): a crude rule-based stand-in so the graph
    can be run and tested end to end without an API call. NOT the real thing.
"""

import json
import os

from graph.state import ClassificationBatch, FailureClassification

MODEL = os.environ.get("COPILOT_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = """You are a senior QA lead deciding whether each failing test is
(a) caused_by_change, (b) flaky, or (c) unrelated to the commit it ran against.

Evidence to use:
- The commit's message, files_changed and diff_summary.
- The failing test's name and error message.
- history_last_10_runs for that test: a test that fails intermittently with no
  code change is flaky; a test that passed 10/10 and now fails is a strong
  signal of a real regression IF the diff plausibly touches that behavior.
- Infra/environment errors (DNS, connection, timeouts unrelated to the diff)
  are 'unrelated' or 'flaky', not regressions.
- A failure can be a real bug the commit did NOT introduce. If the diff has
  nothing to do with the failing test, say 'unrelated' and explain.

Return one classification per failing test. Be honest about confidence."""


def _failures(commits: list[dict], runs: list[dict]) -> list[dict]:
    by_sha = {c["sha"]: c for c in commits}
    out = []
    for run in runs:
        for r in run["results"]:
            if r["status"] == "failed":
                out.append(
                    {
                        "run_id": run["run_id"],
                        "commit": by_sha.get(run["commit_sha"], {"sha": run["commit_sha"]}),
                        "test_name": r["test_name"],
                        "error": r.get("error"),
                        "history_last_10_runs": r.get("history_last_10_runs", []),
                    }
                )
    return out


def classify_with_llm(commits: list[dict], runs: list[dict]) -> list[FailureClassification]:
    from langchain_anthropic import ChatAnthropic

    failures = _failures(commits, runs)
    llm = ChatAnthropic(model=MODEL, temperature=0).with_structured_output(ClassificationBatch)
    batch = llm.invoke(
        [
            ("system", SYSTEM_PROMPT),
            ("human", "Classify these failures:\n" + json.dumps(failures, indent=2)),
        ]
    )
    return batch.classifications


def classify_offline(commits: list[dict], runs: list[dict]) -> list[FailureClassification]:
    """Crude heuristic stand-in. Good enough to exercise the graph, nothing more."""
    out = []
    for f in _failures(commits, runs):
        hist = f["history_last_10_runs"]
        err = (f["error"] or "")
        commit = f["commit"]
        module = f["test_name"].split(".")[0].removeprefix("test_")  # e.g. "checkout"
        touches = any(module in path for path in commit.get("files_changed", []))

        if "ConnectionError" in err or "DNS" in err:
            label, conf, why = "unrelated", 0.8, "Environment/network error; diff does not touch networking."
        elif "failed" in hist:
            label, conf, why = "flaky", 0.7, f"Failed {hist.count('failed')}/10 recent runs without a consistent code cause."
        elif touches:
            label, conf, why = "caused_by_change", 0.75, f"Passed 10/10 before; commit modifies files related to '{module}'."
        else:
            label, conf, why = "unrelated", 0.6, f"Commit files {commit.get('files_changed')} don't relate to '{module}'."
        out.append(
            FailureClassification(
                run_id=f["run_id"], test_name=f["test_name"], commit_sha=commit["sha"],
                label=label, confidence=conf, reasoning=why,
            )
        )
    return out
