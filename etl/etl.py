"""
ETL Pipeline: Chicago Food Inspections
Source: Chicago Data Portal (Socrata API)
Target: PostgreSQL

Run:
    pip install requests psycopg2-binary python-dotenv
    python etl.py
"""

import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import psycopg2
from psycopg2.extras import execute_batch
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

SOCRATA_URL = "https://data.cityofchicago.org/resource/4ijn-s7e5.json"
BATCH_SIZE  = 1000
LIMIT       = int(os.getenv("ETL_LIMIT", "50000"))  # newest records; adjustable

DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", "5432")),
    "dbname":   os.getenv("DB_NAME",     "food_inspections"),
    "user":     os.getenv("DB_USER",     "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def make_session():
    """Retry temporary server errors and throttling; always use request timeouts."""
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET"], respect_retry_after_header=True)
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fetch_records(limit: int, session=None) -> list[dict]:
    """Fetch records from Socrata API with pagination."""
    if limit < 0:
        raise ValueError("limit must be nonnegative")
    records = []
    offset  = 0
    session = session or make_session()

    print(f"Fetching up to {limit:,} records from Chicago Data Portal...")

    while offset < limit:
        batch_size = min(BATCH_SIZE, limit - offset)
        params = {
            "$limit":  batch_size,
            "$offset": offset,
            "$order":  "inspection_date DESC, inspection_id DESC",
        }
        response = session.get(SOCRATA_URL, params=params, timeout=(10, 30))
        response.raise_for_status()

        batch = response.json()
        if not isinstance(batch, list):
            raise ValueError("Unexpected Socrata response: expected a list")
        if not batch:
            break

        records.extend(batch)
        offset += len(batch)
        print(f"  Fetched {len(records):,} records so far...")

        if len(batch) < batch_size:
            break

    print(f"Total records fetched: {len(records):,}")
    return records


def clean_record(row: dict) -> dict:
    """Normalize and clean a single record."""

    def parse_date(val):
        if not val:
            return None
        try:
            return datetime.fromisoformat(val[:10]).date()
        except Exception:
            return None

    def clean_str(val):
        if not val:
            return None
        return str(val).strip() or None

    def clean_risk(val):
        if not val:
            return None
        # "Risk 1 (High)" → "High"
        mapping = {"risk 1 (high)": "High", "risk 2 (medium)": "Medium", "risk 3 (low)": "Low"}
        return mapping.get(str(val).strip().lower(), str(val).strip())

    def parse_float(value):
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    return {
        "inspection_id":    clean_str(row.get("inspection_id")),
        "dba_name":         clean_str(row.get("dba_name")),
        "aka_name":         clean_str(row.get("aka_name")),
        "license_num":      clean_str(row.get("license_")),
        "facility_type":    clean_str(row.get("facility_type")),
        "risk":             clean_risk(row.get("risk")),
        "address":          clean_str(row.get("address")),
        "city":             clean_str(row.get("city")) or "Chicago",
        "state":            clean_str(row.get("state"))  or "IL",
        "zip":              clean_str(row.get("zip")),
        "inspection_date":  parse_date(row.get("inspection_date")),
        "inspection_type":  clean_str(row.get("inspection_type")),
        "results":          clean_str(row.get("results")),
        "violations":       clean_str(row.get("violations")),
        "latitude":         parse_float(row.get("latitude")),
        "longitude":        parse_float(row.get("longitude")),
    }


# ── Database ──────────────────────────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS inspections (
    inspection_id   TEXT PRIMARY KEY,
    dba_name        TEXT,
    aka_name        TEXT,
    license_num     TEXT,
    facility_type   TEXT,
    risk            TEXT,
    address         TEXT,
    city            TEXT,
    state           TEXT,
    zip             TEXT,
    inspection_date DATE,
    inspection_type TEXT,
    results         TEXT,
    violations      TEXT,
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_inspection_date ON inspections (inspection_date);
CREATE INDEX IF NOT EXISTS idx_results         ON inspections (results);
CREATE INDEX IF NOT EXISTS idx_zip             ON inspections (zip);
CREATE INDEX IF NOT EXISTS idx_facility_type   ON inspections (facility_type);
"""

INSERT_SQL = """
INSERT INTO inspections (
    inspection_id, dba_name, aka_name, license_num, facility_type,
    risk, address, city, state, zip, inspection_date, inspection_type,
    results, violations, latitude, longitude
)
VALUES (
    %(inspection_id)s, %(dba_name)s, %(aka_name)s, %(license_num)s, %(facility_type)s,
    %(risk)s, %(address)s, %(city)s, %(state)s, %(zip)s, %(inspection_date)s,
    %(inspection_type)s, %(results)s, %(violations)s, %(latitude)s, %(longitude)s
)
ON CONFLICT (inspection_id) DO UPDATE SET
    dba_name        = EXCLUDED.dba_name,
    aka_name        = EXCLUDED.aka_name,
    license_num     = EXCLUDED.license_num,
    facility_type   = EXCLUDED.facility_type,
    risk            = EXCLUDED.risk,
    address         = EXCLUDED.address,
    city            = EXCLUDED.city,
    state           = EXCLUDED.state,
    zip             = EXCLUDED.zip,
    inspection_date = EXCLUDED.inspection_date,
    inspection_type = EXCLUDED.inspection_type,
    results         = EXCLUDED.results,
    violations      = EXCLUDED.violations,
    latitude        = EXCLUDED.latitude,
    longitude       = EXCLUDED.longitude;
"""


def get_connection():
    database_url = os.getenv("DATABASE_URL", "").strip()

    if database_url:
        return psycopg2.connect(database_url)

    return psycopg2.connect(**DB_CONFIG)


def create_tables(conn):
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()
    print("Tables created (or already exist).")


def load_records(conn, records: list[dict]):
    cleaned = []
    skipped = 0

    for row in records:
        c = clean_record(row)
        if not c["inspection_id"]:
            skipped += 1
            continue
        cleaned.append(c)

    print(f"Loading {len(cleaned):,} records ({skipped} skipped — missing ID)...")

    try:
        with conn.cursor() as cur:
            execute_batch(cur, INSERT_SQL, cleaned, page_size=500)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    print(f"Done. {len(cleaned):,} records upserted.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    records = fetch_records(LIMIT)

    conn = get_connection()
    try:
        create_tables(conn)
        load_records(conn, records)
    finally:
        conn.close()

    print("ETL complete.")


if __name__ == "__main__":
    main()
