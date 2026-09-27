"""Run the Release-Readiness Copilot once and print the report.

    python run.py             # uses Claude (needs ANTHROPIC_API_KEY)
    python run.py --offline   # rule-based stand-in, no API call
"""

import argparse
import asyncio
import os
from datetime import datetime
from pathlib import Path

from graph.pipeline import build_graph


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="skip the LLM, use heuristics")
    args = ap.parse_args()

    if not args.offline and not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY not set. Set it, or run with --offline.")

    result = await build_graph().ainvoke({"mode": "offline" if args.offline else "llm"})
    report = result["report"]
    print(result["report_markdown"])

    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    json_path = Path("reports") / f"report-{stamp}.json"
    md_path = Path("reports") / f"report-{stamp}.md"
    json_path.write_text(report.model_dump_json(indent=2))
    md_path.write_text(result["report_markdown"])
    print(f"\nsaved to {json_path} and {md_path}")


if __name__ == "__main__":
    asyncio.run(main())
