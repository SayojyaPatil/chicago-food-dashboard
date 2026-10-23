"""Opt-in PostgreSQL integration test. CI provides a disposable database."""
import os
import unittest
import psycopg2
from etl import etl


@unittest.skipUnless(os.getenv("RUN_DB_INTEGRATION") == "1", "Needs isolated PostgreSQL test database")
class PostgresIntegrationTests(unittest.TestCase):
    def test_full_upsert_refreshes_existing_record(self):
        conn = psycopg2.connect(os.environ["TEST_DATABASE_URL"])
        try:
            etl.create_tables(conn)
            record = {"inspection_id": "ci-test-id-10001", "dba_name": "Before", "risk": "Risk 1 (High)", "results": "Fail"}
            etl.load_records(conn, [record])
            newer = {**record, "dba_name": "After", "risk": "Risk 3 (Low)", "results": "Pass"}
            etl.load_records(conn, [newer])
            with conn.cursor() as cur:
                cur.execute("SELECT dba_name, risk, results FROM inspections WHERE inspection_id=%s", (record["inspection_id"],))
                self.assertEqual(cur.fetchone(), ("After", "Low", "Pass"))
                cur.execute("DELETE FROM inspections WHERE inspection_id=%s", (record["inspection_id"],))
            conn.commit()
        finally:
            conn.close()
