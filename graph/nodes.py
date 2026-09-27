"""LangGraph nodes for the pipeline, including the Days 8-9 loop-back."""

from graph.classifier import (
    classify_offline,
    classify_with_llm,
    reclassify_offline,
    reclassify_with_llm,
)
from graph.report import build_release_report, render_markdown
from graph.mcp_client import call_tool
from graph.state import CONFIDENCE_THRESHOLD, MAX_LOOPS, CopilotState, FailureClassification

LABEL_TEXT = {
    "caused_by_change": "LIKELY CAUSED BY THIS CHANGE",
    "flaky": "LIKELY FLAKY",
    "unrelated": "UNRELATED (infra / pre-existing)",
}

# Words that show up when the model's reasoning hedges - i.e. it's arguing
# with itself even though the confidence score doesn't reflect it. Caught
# in practice: a classification scored 75% ("caused_by_change") whose own
# reasoning said "amplified by retries, but... plausibly causes/increases".
# A confidence-only check misses that; this catches it.
HEDGE_MARKERS = ("but ", "however", "possibly", "could also", "though it")


def needs_review(c: FailureClassification) -> bool:
    if c.confidence <= CONFIDENCE_THRESHOLD:
        return True
    reasoning = c.reasoning.lower()
    return any(marker in reasoning for marker in HEDGE_MARKERS)


async def fetch_commits(state: CopilotState) -> dict:
    """Node 1: pull recent commits via the MCP server."""
    return {"commits": await call_tool("get_recent_commits", {"limit": 10})}


async def fetch_test_results(state: CopilotState) -> dict:
    """Node 2: pull recent test runs via the MCP server."""
    return {"test_runs": await call_tool("get_test_results", {"limit": 10})}


def classify_failures(state: CopilotState) -> dict:
    """Node 3: classify each failing test."""
    fn = classify_offline if state.get("mode") == "offline" else classify_with_llm
    return {"classifications": fn(state["commits"], state["test_runs"]), "loop_count": 0}


def route_after_classification(state: CopilotState) -> str:
    """Conditional edge: loop back for more context on low-confidence or
    self-contradicting classifications, up to MAX_LOOPS times. This is the
    'agentic' decision point - the graph branches based on how sure the
    model actually was, not a fixed sequence."""
    flagged = [c for c in state.get("classifications", []) if needs_review(c)]
    if flagged and state.get("loop_count", 0) < MAX_LOOPS:
        return "gather_more_context"
    return "build_report"


def gather_more_context(state: CopilotState) -> dict:
    """Node: no new fetch needed here - later commits are already in state
    from Node 1. This node just marks which classifications are under review,
    so the reasoning ('why did it loop') stays inspectable in the report."""
    flagged = [c for c in state["classifications"] if needs_review(c)]
    print(
        f"[loop-back] {len(flagged)} classification(s) flagged (confidence <= {CONFIDENCE_THRESHOLD:.0%}, "
        f"or hedging language in the reasoning) - pulling later-commit context before deciding: "
        + ", ".join(f"{c.test_name} ({c.confidence:.0%})" for c in flagged)
    )
    return {}


def reclassify_failures(state: CopilotState) -> dict:
    """Node: re-run just the flagged classifications with extra context, then
    merge the results back in and bump the loop counter so we don't loop
    forever."""
    classifications = state["classifications"]
    flagged = [c for c in classifications if needs_review(c)]
    fn = reclassify_offline if state.get("mode") == "offline" else reclassify_with_llm
    revised = fn(flagged, state["commits"], state["test_runs"])

    revised_by_key = {(c.run_id, c.test_name): c for c in revised}
    merged = [revised_by_key.get((c.run_id, c.test_name), c) for c in classifications]
    return {"classifications": merged, "loop_count": state.get("loop_count", 0) + 1}


def build_report(state: CopilotState) -> dict:
    """Node 4: plain-text report grouped by commit."""
    commits = sorted(state["commits"], key=lambda c: c["timestamp"])
    report = build_release_report(commits, state.get("classifications", []), state.get("mode", ""))
    return {"report": report, "report_markdown": render_markdown(report)}
