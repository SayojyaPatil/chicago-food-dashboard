"""Incremental ETL: City of Chicago Socrata API -> BigQuery.

Each run:
  1. reads the newest inspection_date already in BigQuery (the watermark),
  2. fetches every record on or after watermark minus a lookback window
     (the city sometimes corrects recent records),
  3. cleans them with the same rules as the PostgreSQL ETL,
  4. loads them into a staging table and MERGEs them into `inspections`,
  5. writes one row to `etl_runs` so the API can show when data last refreshed.

Re-running is safe: MERGE is keyed on inspection_id, so repeated records update
in place instead of duplicating.

Run locally (needs `gcloud auth application-default login`):
    GCP_PROJECT=my-project python -m etl.bq_load --dry-run
    GCP_PROJECT=my-project python -m etl.bq_load
"""

import argparse
import datetime as dt
import os
import uuid

from etl.etl import SOCRATA_URL, BATCH_SIZE, clean_record, make_session

LOOKBACK_DAYS = int(os.getenv("ETL_LOOKBACK_DAYS", "14"))
BACKFILL_SINCE = os.getenv("ETL_BACKFILL_SINCE", "2022-01-01")
MAX_ROWS = int(os.getenv("ETL_MAX_ROWS", "400000"))

COLUMNS = [
    ("inspection_id", "STRING"), ("dba_name", "STRING"), ("aka_name", "STRING"),
    ("license_num", "STRING"), ("facility_type", "STRING"), ("risk", "STRING"),
    ("address", "STRING"), ("city", "STRING"), ("state", "STRING"), ("zip", "STRING"),
    ("inspection_date", "DATE"), ("inspection_type", "STRING"), ("results", "STRING"),
    ("violations", "STRING"), ("latitude", "FLOAT64"), ("longitude", "FLOAT64"),
]


def start_date(watermark: dt.date | None, lookback_days: int = LOOKBACK_DAYS,
               backfill_since: str = BACKFILL_SINCE) -> dt.date:
    """First inspection_date to request from the city."""
    if watermark is None:
        return dt.date.fromisoformat(backfill_since)
    return watermark - dt.timedelta(days=lookback_days)


def fetch_since(since: dt.date, session=None, max_rows: int = MAX_ROWS) -> list[dict]:
    """Page through every record with inspection_date >= since (oldest first)."""
    session = session or make_session()
    headers = {}
    if os.getenv("SOCRATA_APP_TOKEN"):
        headers["X-App-Token"] = os.environ["SOCRATA_APP_TOKEN"]

    records, offset = [], 0
    while offset < max_rows:
        params = {
            "$where": f"inspection_date >= '{since.isoformat()}T00:00:00'",
            "$order": "inspection_date ASC, inspection_id ASC",
            "$limit": BATCH_SIZE,
            "$offset": offset,
        }
        response = session.get(SOCRATA_URL, params=params, headers=headers, timeout=(10, 60))
        response.raise_for_status()
        batch = response.json()
        if not isinstance(batch, list):
            raise ValueError("Unexpected Socrata response: expected a list")
        records.extend(batch)
        offset += len(batch)
        if len(batch) < BATCH_SIZE:
            break
    return records[:max_rows]


def prepare_rows(raw: list[dict]) -> tuple[list[dict], int]:
    """Clean, drop rows without an ID, and keep one row per inspection_id."""
    by_id, skipped = {}, 0
    for row in raw:
        clean = clean_record(row)
        if not clean["inspection_id"]:
            skipped += 1
            continue
        if clean["inspection_date"] is not None:
            clean["inspection_date"] = clean["inspection_date"].isoformat()
        by_id[clean["inspection_id"]] = clean  # later rows win
    return list(by_id.values()), skipped


def merge_sql(target: str, staging: str) -> str:
    names = [name for name, _ in COLUMNS]
    updates = ",\n        ".join(f"{n} = S.{n}" for n in names if n != "inspection_id")
    cols = ", ".join(names)
    values = ", ".join(f"S.{n}" for n in names)
    return f"""
MERGE {target} T
USING {staging} S
ON T.inspection_id = S.inspection_id
WHEN MATCHED THEN UPDATE SET
        {updates}
WHEN NOT MATCHED THEN INSERT ({cols}) VALUES ({values})
"""


def _watermark(store) -> dt.date | None:
    rows = store.run(f"SELECT MAX(inspection_date) AS d FROM {store.table('inspections')}")
    value = rows[0]["d"] if rows else None
    return dt.date.fromisoformat(value) if value else None


def _log_run(store, run: dict):
    store.run(
        f"""INSERT INTO {store.table('etl_runs')}
            (run_id, started_at, finished_at, since_date, rows_fetched, rows_merged, status, error)
            VALUES (@run_id, TIMESTAMP(@started_at), CURRENT_TIMESTAMP(), DATE(@since_date),
                    @rows_fetched, @rows_merged, @status, @error)""",
        run,
    )


def load(rows: list[dict]) -> int:
    """Load rows to staging and MERGE into inspections. Returns rows affected."""
    from google.cloud import bigquery
    from backend import bigquery_store as bq

    client = bq.client()
    staging = bq.table_id("_inspections_staging")
    schema = [bigquery.SchemaField(n, t) for n, t in COLUMNS]
    job = client.load_table_from_json(
        rows, staging,
        job_config=bigquery.LoadJobConfig(
            schema=schema, write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE),
    )
    job.result()
    merge = client.query(merge_sql(bq.table("inspections"), bq.table("_inspections_staging")))
    merge.result()
    return int(merge.num_dml_affected_rows or 0)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Incremental Socrata -> BigQuery load")
    parser.add_argument("--since", help="override start date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="fetch and clean only")
    args = parser.parse_args(argv)

    from backend.bigquery_store import BigQueryWarehouse
    store = BigQueryWarehouse()
    run = {"run_id": uuid.uuid4().hex[:12],
           "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
           "rows_fetched": 0, "rows_merged": 0, "status": "ok", "error": None}

    since = dt.date.fromisoformat(args.since) if args.since else start_date(_watermark(store))
    run["since_date"] = since.isoformat()
    print(f"[etl] run {run['run_id']}: fetching inspections on or after {since}")

    try:
        raw = fetch_since(since)
        rows, skipped = prepare_rows(raw)
        run["rows_fetched"] = len(raw)
        print(f"[etl] fetched {len(raw):,} records, {len(rows):,} unique, {skipped} without ID")
        if args.dry_run:
            print("[etl] dry run: nothing written")
            return 0
        if rows:
            run["rows_merged"] = load(rows)
        print(f"[etl] merged {run['rows_merged']:,} rows")
    except Exception as exc:  # record the failure, then fail the job so Cloud Run retries
        run["status"], run["error"] = "error", f"{type(exc).__name__}: {exc}"[:500]
        _log_run(store, run)
        raise
    _log_run(store, run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
