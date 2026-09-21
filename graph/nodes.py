"""LangGraph nodes for the single-pass pipeline (Days 5-7)."""

from graph.classifier import classify_offline, classify_with_llm
from graph.mcp_client import call_tool
from graph.state import CopilotState

LABEL_TEXT = {
    "caused_by_change": "LIKELY CAUSED BY THIS CHANGE",
    "flaky": "LIKELY FLAKY",
    "unrelated": "UNRELATED (infra / pre-existing)",
}


async def fetch_commits(state: CopilotState) -> dict:
    """Node 1: pull recent commits via the MCP server."""
    return {"commits": await call_tool("get_recent_commits", {"limit": 10})}


async def fetch_test_results(state: CopilotState) -> dict:
    """Node 2: pull recent test runs via the MCP server."""
    return {"test_runs": await call_tool("get_test_results", {"limit": 10})}


def classify_failures(state: CopilotState) -> dict:
    """Node 3: classify each failing test."""
    fn = classify_offline if state.get("mode") == "offline" else classify_with_llm
    return {"classifications": fn(state["commits"], state["test_runs"])}


def build_report(state: CopilotState) -> dict:
    """Node 4: plain-text report grouped by commit."""
    commits = sorted(state["commits"], key=lambda c: c["timestamp"])
    by_sha: dict[str, list] = {}
    for c in state.get("classifications", []):
        by_sha.setdefault(c.commit_sha, []).append(c)

    lines = ["RELEASE-READINESS REPORT", "=" * 24, f"mode: {state.get('mode')}", ""]
    for commit in commits:
        lines.append(f"[{commit['sha']}] {commit['message']}")
        items = by_sha.get(commit["sha"], [])
        if not items:
            lines.append("    no failing tests")
        for c in items:
            lines.append(f"    {LABEL_TEXT[c.label]} ({c.confidence:.0%}) - {c.test_name}")
            lines.append(f"        {c.reasoning}")
        lines.append("")

    counts = {k: sum(1 for c in state.get("classifications", []) if c.label == k) for k in LABEL_TEXT}
    lines.append("SUMMARY: " + ", ".join(f"{v} {LABEL_TEXT[k].lower()}" for k, v in counts.items()))
    return {"report": "\n".join(lines)}
