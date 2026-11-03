import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from backend import main


class APIUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def test_health(self):
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_all_list_metrics_routes(self):
        routes = ["pass-fail-trend", "risk-distribution", "top-facility-types", "zip-fail-rates", "top-violations"]
        for route in routes:
            with self.subTest(route=route), patch.object(main, "query", return_value=[{"sample": 1}]) as query:
                response = self.client.get(f"/metrics/{route}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), [{"sample": 1}])
                query.assert_called_once()

    def test_kpi(self):
        with patch.object(main, "query_one", return_value={"total_inspections": 24}):
            response = self.client.get('/metrics/kpi-summary')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_inspections"], 24)

    def test_db_health_success(self):
        conn = MagicMock()
        with patch.object(main, "get_conn", return_value=conn):
            response = self.client.get('/health/db')
        self.assertEqual(response.status_code, 200)
        conn.close.assert_called_once()

    def test_db_health_unavailable(self):
        import psycopg2
        with patch.object(main, "get_conn", side_effect=psycopg2.OperationalError("offline")):
            response = self.client.get('/health/db')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Database unavailable")

    def test_cors_does_not_allow_arbitrary_origin(self):
        response = self.client.get('/health', headers={"Origin": "https://untrusted.invalid"})
        self.assertNotEqual(response.headers.get("access-control-allow-origin"), "*")
        self.assertNotIn("https://untrusted.invalid", response.headers.get("access-control-allow-origin", ""))


if __name__ == '__main__':
    unittest.main()
