import unittest
from unittest.mock import Mock, patch
from etl import etl


class FetchTests(unittest.TestCase):
    def test_pages_until_limit(self):
        session = Mock()
        first = [{"inspection_id": str(i)} for i in range(1000)]
        second = [{"inspection_id": "1000"}, {"inspection_id": "1001"}]
        session.get.side_effect = [Mock(**{"json.return_value": first}), Mock(**{"json.return_value": second})]
        rows = etl.fetch_records(1002, session=session)
        self.assertEqual(len(rows), 1002)
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(session.get.call_args_list[1].kwargs["params"]["$offset"], 1000)
        self.assertEqual(session.get.call_args_list[1].kwargs["params"]["$limit"], 2)
        self.assertEqual(session.get.call_args_list[0].kwargs["timeout"], (10, 30))

    def test_bad_response_rejected(self):
        session = Mock()
        session.get.return_value.json.return_value = {"error": "bad request"}
        with self.assertRaises(ValueError):
            etl.fetch_records(10, session=session)

    def test_request_error_propagates(self):
        session = Mock()
        session.get.return_value.raise_for_status.side_effect = RuntimeError("unavailable")
        with self.assertRaises(RuntimeError):
            etl.fetch_records(10, session=session)

    def test_invalid_limit(self):
        with self.assertRaises(ValueError):
            etl.fetch_records(-1, session=Mock())

    def test_bad_coordinates_are_optional(self):
        result = etl.clean_record({"inspection_id": "5", "latitude": "bad", "longitude": "-87.6"})
        self.assertIsNone(result["latitude"])
        self.assertEqual(result["longitude"], -87.6)

    def test_full_upsert_updates_all_non_key_columns(self):
        columns = etl.INSERT_SQL.split("ON CONFLICT")[0].split("INSERT INTO inspections (")[1].split(")")[0]
        names = [x.strip() for x in columns.split(",")]
        updates = etl.INSERT_SQL.split("DO UPDATE SET")[1]
        for column in names:
            if column != "inspection_id":
                self.assertIn(f"{column}", updates)
                self.assertIn(f"EXCLUDED.{column}", updates)

    @patch.object(etl, "execute_batch")
    def test_load_rolls_back_if_upsert_fails(self, execute_batch):
        execute_batch.side_effect = ValueError("write failed")
        conn = Mock()
        conn.cursor.return_value.__enter__ = Mock(return_value=Mock())
        conn.cursor.return_value.__exit__ = Mock(return_value=None)
        with self.assertRaises(ValueError):
            etl.load_records(conn, [{"inspection_id": "100"}])
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
