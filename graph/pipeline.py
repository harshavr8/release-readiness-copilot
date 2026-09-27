"""Graph with the Days 8-9 loop-back:

fetch_commits -> fetch_test_results -> classify_failures
    -> [conditional] -> gather_more_context -> reclassify_failures -> [conditional, capped]
    -> build_report
"""

from langgraph.graph import END, START, StateGraph

from graph.nodes import (
    build_report,
    classify_failures,
    fetch_commits,
    fetch_test_results,
    gather_more_context,
    reclassify_failures,
    route_after_classification,
)
from graph.state import CopilotState


def build_graph():
    g = StateGraph(CopilotState)
    g.add_node("fetch_commits", fetch_commits)
    g.add_node("fetch_test_results", fetch_test_results)
    g.add_node("classify_failures", classify_failures)
    g.add_node("gather_more_context", gather_more_context)
    g.add_node("reclassify_failures", reclassify_failures)
    g.add_node("build_report", build_report)

    g.add_edge(START, "fetch_commits")
    g.add_edge("fetch_commits", "fetch_test_results")
    g.add_edge("fetch_test_results", "classify_failures")

    # The agentic decision point: loop back for more context, or move on.
    g.add_conditional_edges(
        "classify_failures",
        route_after_classification,
        {"gather_more_context": "gather_more_context", "build_report": "build_report"},
    )
    g.add_edge("gather_more_context", "reclassify_failures")
    g.add_conditional_edges(
        "reclassify_failures",
        route_after_classification,
        {"gather_more_context": "gather_more_context", "build_report": "build_report"},
    )

    g.add_edge("build_report", END)
    return g.compile()
