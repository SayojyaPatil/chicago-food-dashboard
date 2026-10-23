"""Unit tests for deterministic ETL normalization; no database required."""
import unittest
from etl.etl import clean_record


class CleanRecordTests(unittest.TestCase):
    def test_normalizes_risk_and_date(self):
        row = {"inspection_id": " 42 ", "risk": "Risk 1 (High)", "inspection_date": "2024-06-18T00:00:00", "city": ""}
        result = clean_record(row)
        self.assertEqual(result["inspection_id"], "42")
        self.assertEqual(result["risk"], "High")
        self.assertEqual(result["inspection_date"].isoformat(), "2024-06-18")
        self.assertEqual(result["city"], "Chicago")
        self.assertEqual(result["state"], "IL")

    def test_optional_values(self):
        result = clean_record({"inspection_id": "100"})
        self.assertIsNone(result["latitude"])
        self.assertIsNone(result["inspection_date"])
        self.assertIsNone(result["facility_type"])

    def test_invalid_date(self):
        result = clean_record({"inspection_id": "100", "inspection_date": "invalid"})
        self.assertIsNone(result["inspection_date"])


if __name__ == "__main__":
    unittest.main()
