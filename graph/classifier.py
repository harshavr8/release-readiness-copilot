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
    llm = ChatAnthropic(model=MODEL).with_structured_output(ClassificationBatch)
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


# ---------------------------------------------------------------------------
# Loop-back reclassification (Days 8-9)
#
# Triggered when a first-pass classification comes back under
# CONFIDENCE_THRESHOLD. Rather than just asking the model to "try again" on
# the same evidence, we pull one extra piece of context it didn't have: the
# diffs of commits that landed *after* the failing one. That's what lets it
# notice, e.g., that the very next commit fixes the bug a failure exposed —
# evidence a single-pass, per-commit classifier structurally can't see.
# ---------------------------------------------------------------------------

RECLASSIFY_SYSTEM_PROMPT = SYSTEM_PROMPT + """

You are being asked to RECONSIDER a low-confidence classification. You now
also have the diffs of commits that landed AFTER the one under review. Use
them to check one specific thing: does a later commit fix the same area the
failing test covers? If so, that's strong evidence this was a pre-existing
bug the current commit merely exposed, not something the current commit
caused - label it 'unrelated' with higher confidence. If nothing later is
relevant, you may keep your original label, but raise or lower confidence
based on the full picture now available, and make sure your reasoning
doesn't contradict itself (e.g., don't cite a clean pass history as evidence
of flakiness - that's evidence AGAINST flakiness)."""


def _later_commits(commit_sha: str, commits: list[dict]) -> list[dict]:
    ordered = sorted(commits, key=lambda c: c["timestamp"])
    idx = next((i for i, c in enumerate(ordered) if c["sha"] == commit_sha), None)
    return ordered[idx + 1 :] if idx is not None else []


def _needs_review(classifications: list[FailureClassification]) -> list[FailureClassification]:
    return [c for c in classifications if c.confidence < CONFIDENCE_THRESHOLD]


def reclassify_with_llm(
    flagged: list[FailureClassification], commits: list[dict], runs: list[dict]
) -> list[FailureClassification]:
    from langchain_anthropic import ChatAnthropic

    by_run_test = {(f["run_id"], f["test_name"]): f for f in _failures(commits, runs)}
    llm = ChatAnthropic(model=MODEL).with_structured_output(ClassificationBatch)

    payload = []
    for c in flagged:
        f = by_run_test.get((c.run_id, c.test_name), {})
        payload.append(
            {
                "original_classification": c.model_dump(),
                "commit": f.get("commit"),
                "test_name": c.test_name,
                "error": f.get("error"),
                "history_last_10_runs": f.get("history_last_10_runs", []),
                "later_commits": _later_commits(c.commit_sha, commits),
            }
        )

    batch = llm.invoke(
        [
            ("system", RECLASSIFY_SYSTEM_PROMPT),
            ("human", "Reconsider these low-confidence classifications:\n" + json.dumps(payload, indent=2)),
        ]
    )
    revised = batch.classifications
    for c in revised:
        c.revised = True
    return revised


def reclassify_offline(
    flagged: list[FailureClassification], commits: list[dict], runs: list[dict]
) -> list[FailureClassification]:
    """Offline stand-in: bump confidence to 'unrelated' if a later commit's
    diff_summary mentions the same module the failing test covers."""
    out = []
    for c in flagged:
        module = c.test_name.split(".")[0].removeprefix("test_")
        later = _later_commits(c.commit_sha, commits)
        fix = next(
            (lc for lc in later if module in " ".join(lc.get("files_changed", [])) or module in lc.get("diff_summary", "")),
            None,
        )
        if fix:
            out.append(
                FailureClassification(
                    run_id=c.run_id, test_name=c.test_name, commit_sha=c.commit_sha,
                    label="unrelated", confidence=0.85,
                    reasoning=f"Commit {fix['sha']} ('{fix['message']}') lands right after and fixes the '{module}' "
                    "area this test covers - this was a pre-existing bug, not something this commit caused.",
                    revised=True,
                )
            )
        else:
            c.confidence = min(0.8, c.confidence + 0.1)
            c.revised = True
            out.append(c)
    return out
