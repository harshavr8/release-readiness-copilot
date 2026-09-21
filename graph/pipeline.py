"""Single-pass graph: fetch_commits -> fetch_test_results -> classify -> report."""

from langgraph.graph import END, START, StateGraph

from graph.nodes import build_report, classify_failures, fetch_commits, fetch_test_results
from graph.state import CopilotState


def build_graph():
    g = StateGraph(CopilotState)
    g.add_node("fetch_commits", fetch_commits)
    g.add_node("fetch_test_results", fetch_test_results)
    g.add_node("classify_failures", classify_failures)
    g.add_node("build_report", build_report)

    g.add_edge(START, "fetch_commits")
    g.add_edge("fetch_commits", "fetch_test_results")
    g.add_edge("fetch_test_results", "classify_failures")
    g.add_edge("classify_failures", "build_report")
    g.add_edge("build_report", END)
    return g.compile()
