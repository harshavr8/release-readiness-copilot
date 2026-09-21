"""Shared state passed between LangGraph nodes."""

from typing import Literal, Optional, TypedDict

from pydantic import BaseModel, Field

Label = Literal["caused_by_change", "flaky", "unrelated"]


class FailureClassification(BaseModel):
    run_id: str
    test_name: str
    commit_sha: str
    label: Label = Field(
        description="caused_by_change: the commit's diff plausibly broke it. "
        "flaky: intermittent, history shows it fails without code changes. "
        "unrelated: environment/infra, or a bug this commit did not introduce."
    )
    confidence: float = Field(ge=0, le=1)
    reasoning: str = Field(description="One or two sentences citing the evidence used.")


class ClassificationBatch(BaseModel):
    classifications: list[FailureClassification]


class CopilotState(TypedDict, total=False):
    commits: list[dict]
    test_runs: list[dict]
    classifications: list[FailureClassification]
    report: str
    mode: Optional[str]  # "llm" or "offline"
