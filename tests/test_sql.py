"""Both SQL dialects must define the same metrics with the same counting rules."""

import unittest

from backend import sql


class DialectParityTests(unittest.TestCase):
    def test_same_metrics_in_both_dialects(self):
        self.assertEqual(set(sql.POSTGRES), set(sql.BIGQUERY))

    def test_rates_count_only_real_outcomes(self):
        # "Out of Business", "No Entry" etc. are not inspections of food safety.
        for dialect in (sql.POSTGRES, sql.BIGQUERY):
            for name, query in dialect.items():
                if name == "freshness":
                    continue
                with self.subTest(metric=name):
                    self.assertIn(sql.OUTCOMES, query)

    def test_windows_anchor_to_newest_inspection(self):
        # A stale snapshot should still show a full year, not an empty window.
        for name in ("risk_distribution", "top_facility_types", "zip_fail_rates",
                     "top_violations", "kpi_summary", "pass_fail_trend"):
            with self.subTest(metric=name):
                self.assertIn("MAX(inspection_date)", sql.POSTGRES[name])
                self.assertIn("MAX(inspection_date)", sql.BIGQUERY[name])
                self.assertNotIn("CURRENT_DATE", sql.BIGQUERY[name])

    def test_agent_tools_use_the_same_outcome_set(self):
        from backend.agent import tools
        self.assertEqual(tools.OUTCOMES, sql.OUTCOMES)


if __name__ == "__main__":
    unittest.main()
