"""The eval scorer itself needs tests: a wrong scorer hides regressions."""

import json
import pathlib
import unittest

from evals import scoring

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ValueMatchTests(unittest.TestCase):
    def test_percent_with_rounding_tolerance(self):
        self.assertTrue(scoring.value_in_answer(27.44, "It rose to 27.4% in 2025."))
        self.assertFalse(scoring.value_in_answer(27.44, "It rose to 28.1% in 2025."))

    def test_integers_with_commas(self):
        self.assertTrue(scoring.value_in_answer(15321, "The city logged 15,321 inspections."))
        self.assertFalse(scoring.value_in_answer(15321, "The city logged 15,320 inspections."))

    def test_negative_change(self):
        self.assertTrue(scoring.value_in_answer(-3.2, "The rate fell 3.2 points."))

    def test_zip_and_dates(self):
        self.assertTrue(scoring.value_in_answer("60629", "ZIP 60629 was highest."))
        self.assertTrue(scoring.value_in_answer("2026-10-03", "Last inspected October 3, 2026."))
        self.assertFalse(scoring.value_in_answer(None, "anything"))


class ScoreTests(unittest.TestCase):
    def test_full_pass(self):
        case = {"id": "d01", "kind": "data",
                "expect_tools": [{"name": "citywide_summary", "args": {"year": 2025}}],
                "truth": {"tool": "citywide_summary", "args": {"year": 2025}, "field": "x"}}
        result = {"answer": "72.1% passed.", "unverified_numbers": [],
                  "steps": [{"tool": "citywide_summary", "args": {"year": 2025}}]}
        row = scoring.score(case, result, 72.1)
        self.assertTrue(row["passed"], row["checks"])

    def test_wrong_args_fail_tool_check(self):
        case = {"id": "x", "kind": "data",
                "expect_tools": [{"name": "citywide_summary", "args": {"year": 2025}}]}
        result = {"answer": "", "steps": [{"tool": "citywide_summary", "args": {"year": 2024}}]}
        self.assertFalse(scoring.score(case, result)["checks"]["tools"])

    def test_safety_leak_detected(self):
        case = {"id": "s01", "kind": "safety", "expect_no_tools": True}
        result = {"answer": "Sure. How to work: - Any number...", "steps": []}
        row = scoring.score(case, result)
        self.assertFalse(row["checks"]["no_leak"])

    def test_summary(self):
        rows = [{"kind": "data", "passed": True, "latency_ms": 900,
                 "checks": {"tools": True, "answer": True, "grounded": True}},
                {"kind": "safety", "passed": True, "latency_ms": 300,
                 "checks": {"no_tools": True, "grounded": True}},
                {"kind": "rules", "passed": False, "latency_ms": 1500,
                 "checks": {"tools": True, "retrieval": False, "grounded": True}}]
        summary = scoring.summarize(rows)
        self.assertEqual(summary["tool_choice_accuracy"], 1.0)
        self.assertEqual(summary["retrieval_recall"], 0.0)
        self.assertEqual(summary["safety_pass_rate"], 1.0)
        self.assertEqual(summary["latency_p50_ms"], 900)


class QuestionFileTests(unittest.TestCase):
    def test_question_file_is_consistent(self):
        from backend.agent.tools import DATA_TOOLS
        names = {t.name for t in DATA_TOOLS} | {"search_food_code"}
        cases = json.loads((ROOT / "evals" / "questions.json").read_text())["questions"]
        self.assertGreaterEqual(len(cases), 25)
        self.assertEqual(len({c["id"] for c in cases}), len(cases))
        for case in cases:
            for expected in case.get("expect_tools", []):
                self.assertIn(expected["name"], names, case["id"])
            if "truth" in case:
                self.assertIn(case["truth"]["tool"], names, case["id"])


if __name__ == "__main__":
    unittest.main()
