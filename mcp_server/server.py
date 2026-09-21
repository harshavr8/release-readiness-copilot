"""
MCP server for the Release-Readiness Copilot.

Exposes two tools over MCP:
  - get_recent_commits: returns recent commit/diff summaries
  - get_test_results: returns recent test run results, optionally filtered by commit sha

Run standalone for testing:
    python server.py

Inspect with the MCP inspector:
    npx @modelcontextprotocol/inspector python server.py
"""

import json
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

DATA_DIR = Path(__file__).parent.parent / "data"

mcp = FastMCP("release-readiness-copilot")


def _load(filename: str) -> list[dict]:
    with open(DATA_DIR / filename) as f:
        return json.load(f)


@mcp.tool()
def get_recent_commits(limit: int = 10) -> list[dict]:
    """
    Return the most recent commits with their diff summaries.

    Args:
        limit: maximum number of commits to return, most recent first.
    """
    commits = _load("commits.json")
    commits_sorted = sorted(commits, key=lambda c: c["timestamp"], reverse=True)
    return commits_sorted[:limit]


@mcp.tool()
def get_test_results(commit_sha: Optional[str] = None, limit: int = 10) -> list[dict]:
    """
    Return recent test run results, each containing per-test pass/fail status,
    error messages, and recent history for failed tests (to help distinguish
    flaky tests from real regressions).

    Args:
        commit_sha: if provided, only return the test run(s) associated with this commit.
        limit: maximum number of test runs to return, most recent first.
    """
    runs = _load("test_runs.json")
    if commit_sha:
        runs = [r for r in runs if r["commit_sha"] == commit_sha]
    runs_sorted = sorted(runs, key=lambda r: r["timestamp"], reverse=True)
    return runs_sorted[:limit]


if __name__ == "__main__":
    mcp.run()
