"""BigQuery ETL logic that runs without GCP: watermarks, paging, cleaning, MERGE."""

import datetime as dt
import unittest
from unittest.mock import Mock

from etl import bq_load


class StartDateTests(unittest.TestCase):
    def test_first_run_backfills(self):
        self.assertEqual(bq_load.start_date(None, 14, "2022-01-01"), dt.date(2022, 1, 1))

    def test_later_runs_look_back(self):
        self.assertEqual(bq_load.start_date(dt.date(2026, 11, 2), 14), dt.date(2026, 10, 19))


class FetchSinceTests(unittest.TestCase):
    def test_pages_until_short_batch_with_where_clause(self):
        session = Mock()
        full = [{"inspection_id": str(i)} for i in range(bq_load.BATCH_SIZE)]
        session.get.side_effect = [Mock(**{"json.return_value": full}),
                                   Mock(**{"json.return_value": [{"inspection_id": "x"}]})]
        rows = bq_load.fetch_since(dt.date(2026, 10, 19), session=session)
        self.assertEqual(len(rows), bq_load.BATCH_SIZE + 1)
        params = session.get.call_args_list[1].kwargs["params"]
        self.assertEqual(params["$where"], "inspection_date >= '2026-10-19T00:00:00'")
        self.assertEqual(params["$offset"], bq_load.BATCH_SIZE)

    def test_max_rows_cap(self):
        session = Mock()
        session.get.return_value.json.return_value = [{"inspection_id": "1"}] * bq_load.BATCH_SIZE
        rows = bq_load.fetch_since(dt.date(2026, 1, 1), session=session, max_rows=1500)
        self.assertEqual(len(rows), 1500)


class PrepareTests(unittest.TestCase):
    def test_dedupes_and_serializes_dates(self):
        raw = [{"inspection_id": "1", "results": "Fail", "inspection_date": "2026-10-01T00:00:00"},
               {"inspection_id": "1", "results": "Pass", "inspection_date": "2026-10-01T00:00:00"},
               {"inspection_id": "", "results": "Pass"}]
        rows, skipped = bq_load.prepare_rows(raw)
        self.assertEqual(skipped, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["results"], "Pass")
        self.assertEqual(rows[0]["inspection_date"], "2026-10-01")


class MergeSqlTests(unittest.TestCase):
    def test_updates_every_column_and_inserts_all(self):
        sql = bq_load.merge_sql("`p.d.inspections`", "`p.d.staging`")
        names = [n for n, _ in bq_load.COLUMNS]
        update_block = sql.split("WHEN MATCHED THEN UPDATE SET")[1].split("WHEN NOT MATCHED")[0]
        for name in names:
            if name != "inspection_id":
                self.assertIn(f"{name} = S.{name}", update_block)
        self.assertIn("ON T.inspection_id = S.inspection_id", sql)
        self.assertNotIn("inspection_id = S.inspection_id,", update_block)


if __name__ == "__main__":
    unittest.main()
