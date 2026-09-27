"""Day 10: turn classifications into a structured, scored release report.

Deliberately NOT another LLM call. The LLM's job is classification, where
judgment genuinely helps; turning classifications into a risk score and a
go/no-go call is a deterministic policy so it's reproducible and you can
explain the exact rule that fired, rather than "the model decided."
"""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

from graph.state import FailureClassification

Recommendation = Literal["go", "go_with_caution", "needs_human_review", "no_go"]

# Points contributed per failure, scaled by the model's confidence in that
# classification. A confident regression should dominate the score; flaky
# and infra failures matter, but much less, since they aren't evidence the
# new code is broken.
POINTS = {"caused_by_change": 30, "flaky": 8, "unrelated": 3}

# A single caused_by_change failure at/above this confidence is a no-go on
# its own, regardless of everything else - one real regression is enough.
NO_GO_CONFIDENCE = 0.70

# Even after the loop-back's one reconsideration, a classification can still
# land below this. That's not the model being wrong - it's the model being
# honest that the evidence is genuinely ambiguous (seen in practice: the
# gateway retry test landing at 55% because a real timing-flaky test also
# sits near a change that plausibly affects timing). Rather than asserting
# a label at that confidence, route it to a human instead of letting it
# silently become "the answer."
HUMAN_REVIEW_CONFIDENCE = 0.60


class CommitReport(BaseModel):
    sha: str
    message: str
    author: str | None = None
    status: Literal["clean", "has_failures"]
    failures: list[FailureClassification]


class ReleaseReport(BaseModel):
    generated_at: str
    mode: str
    recommendation: Recommendation
    risk_score: int  # 0-100
    summary: str
    counts: dict[str, int]
    needs_human_review: list[FailureClassification]
    commits: list[CommitReport]


def _recommendation(
    classifications: list[FailureClassification], low_confidence: list[FailureClassification]
) -> tuple[Recommendation, str]:
    confident_regressions = [
        c for c in classifications if c.label == "caused_by_change" and c.confidence >= NO_GO_CONFIDENCE
    ]
    if confident_regressions:
        names = ", ".join(c.test_name for c in confident_regressions)
        return "no_go", f"{len(confident_regressions)} likely regression(s) found: {names}."

    if low_confidence:
        names = ", ".join(c.test_name for c in low_confidence)
        return "needs_human_review", (
            f"{len(low_confidence)} failure(s) stayed under {HUMAN_REVIEW_CONFIDENCE:.0%} confidence even after "
            f"reconsideration - genuinely ambiguous, not a call to automate: {names}."
        )

    other_failures = [c for c in classifications if c.label != "caused_by_change"]
    if other_failures:
        return "go_with_caution", (
            f"No confident regressions, but {len(other_failures)} failure(s) "
            "flagged as flaky/infra - noisy, worth a human glance before shipping."
        )

    return "go", "No failing tests attributable to recent changes."


def build_release_report(
    commits: list[dict], classifications: list[FailureClassification], mode: str
) -> ReleaseReport:
    risk_score = min(100, round(sum(POINTS[c.label] * c.confidence for c in classifications)))
    low_confidence = [c for c in classifications if c.confidence < HUMAN_REVIEW_CONFIDENCE]
    recommendation, summary = _recommendation(classifications, low_confidence)

    by_sha: dict[str, list[FailureClassification]] = {}
    for c in classifications:
        by_sha.setdefault(c.commit_sha, []).append(c)

    commit_reports = [
        CommitReport(
            sha=c["sha"],
            message=c["message"],
            author=c.get("author"),
            status="has_failures" if by_sha.get(c["sha"]) else "clean",
            failures=by_sha.get(c["sha"], []),
        )
        for c in sorted(commits, key=lambda c: c["timestamp"])
    ]

    counts = {k: sum(1 for c in classifications if c.label == k) for k in POINTS}

    return ReleaseReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        mode=mode,
        recommendation=recommendation,
        risk_score=risk_score,
        summary=summary,
        counts=counts,
        needs_human_review=low_confidence,
        commits=commit_reports,
    )


LABEL_TEXT = {
    "caused_by_change": "Likely caused by this change",
    "flaky": "Likely flaky",
    "unrelated": "Unrelated (infra / pre-existing)",
}
REC_TEXT = {
    "go": "✅ GO",
    "go_with_caution": "⚠️ GO WITH CAUTION",
    "needs_human_review": "🧐 NEEDS HUMAN REVIEW",
    "no_go": "🛑 NO-GO",
}


def render_markdown(report: ReleaseReport) -> str:
    lines = [
        "# Release-Readiness Report",
        "",
        f"**Recommendation:** {REC_TEXT[report.recommendation]}  ",
        f"**Risk score:** {report.risk_score}/100  ",
        f"**Generated:** {report.generated_at}  ",
        f"**Mode:** {report.mode}",
        "",
        f"> {report.summary}",
        "",
        "## Commits",
        "",
    ]
    for c in report.commits:
        badge = "🟢" if c.status == "clean" else "🔴"
        lines.append(f"### {badge} `{c.sha}` {c.message}")
        if not c.failures:
            lines.append("- No failing tests")
        for f in c.failures:
            flag = " *(reconsidered after loop-back)*" if f.revised else ""
            lines.append(f"- **{LABEL_TEXT[f.label]}** ({f.confidence:.0%}){flag} — `{f.test_name}`")
            lines.append(f"  {f.reasoning}")
        lines.append("")

    if report.needs_human_review:
        lines += ["## 🧐 Needs Human Review", "", "Stayed below 60% confidence even after the loop-back:", ""]
        for f in report.needs_human_review:
            lines.append(f"- `{f.test_name}` ({f.confidence:.0%}, currently labeled *{LABEL_TEXT[f.label]}*)")
            lines.append(f"  {f.reasoning}")
        lines.append("")

    lines += [
        "## Summary",
        "",
        "| Classification | Count |",
        "|---|---|",
    ]
    for label, count in report.counts.items():
        lines.append(f"| {LABEL_TEXT[label]} | {count} |")

    return "\n".join(lines)
