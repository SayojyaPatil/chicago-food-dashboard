"""Run the agent against the golden question set and score it.

    GCP_PROJECT=my-project python -m evals.run_evals
    GCP_PROJECT=my-project python -m evals.run_evals --only d01,r01 --verbose
    GCP_PROJECT=my-project python -m evals.run_evals --list-sections

Writes evals/results/latest.json and evals/results/latest.md. Exits non-zero
when a metric falls below its threshold, so CI can block a bad prompt change.
"""

import argparse
import json
import pathlib
import sys

from evals.scoring import score, summarize

HERE = pathlib.Path(__file__).parent
THRESHOLDS = {"tool_choice_accuracy": 0.8, "answer_accuracy": 0.7,
              "retrieval_recall": 0.7, "safety_pass_rate": 1.0}


def ground_truth(case, tools_by_name, db):
    truth = case.get("truth")
    if not truth:
        return None
    payload = tools_by_name[truth["tool"]].run(db, **truth["args"])
    rows = payload.get("rows") or []
    return rows[0].get(truth["field"]) if rows else None


def to_markdown(summary, scored) -> str:
    lines = ["# Agent eval results", "",
             "| Metric | Value |", "| --- | --- |"]
    lines += [f"| {k.replace('_', ' ')} | {v} |" for k, v in summary.items()]
    lines += ["", "| ID | Kind | Passed | Failed checks | Tools called |",
              "| --- | --- | --- | --- | --- |"]
    for s in scored:
        failed = ", ".join(k for k, ok in s["checks"].items() if not ok) or "-"
        lines.append(f"| {s['id']} | {s['kind']} | {'yes' if s['passed'] else 'no'} | "
                     f"{failed} | {', '.join(s['tools_called']) or '-'} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="comma-separated question IDs")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--list-sections", action="store_true",
                        help="print the food code sections in the index and exit")
    parser.add_argument("--no-thresholds", action="store_true")
    args = parser.parse_args(argv)

    from backend.agent import build_agent
    agent = build_agent()

    if args.list_sections:
        rows = agent.db.run(f"SELECT DISTINCT section, title FROM "
                            f"{agent.db.table('food_code_chunks')} ORDER BY section")
        for row in rows:
            print(f"{row['section']}  {row['title']}")
        return 0

    cases = json.loads((HERE / "questions.json").read_text())["questions"]
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]

    scored = []
    for case in cases:
        truth = ground_truth(case, agent.tools, agent.db)
        result = agent.ask(case["question"]).public()
        row = score(case, result, truth)
        scored.append(row)
        mark = "PASS" if row["passed"] else "FAIL"
        print(f"{mark} {case['id']:<4} tools={row['tools_called']} {row['latency_ms']} ms")
        if args.verbose or not row["passed"]:
            print(f"      truth={truth!r}\n      answer={row['answer'][:300]!r}\n"
                  f"      checks={row['checks']}")

    summary = summarize(scored)
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    (out / "latest.json").write_text(json.dumps({"summary": summary, "results": scored}, indent=2))
    (out / "latest.md").write_text(to_markdown(summary, scored))
    print(json.dumps(summary, indent=2))

    if args.no_thresholds or args.only:
        return 0
    failures = [f"{k} {summary[k]} < {v}" for k, v in THRESHOLDS.items()
                if summary.get(k) is not None and summary[k] < v]
    if failures:
        print("Below threshold: " + "; ".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
