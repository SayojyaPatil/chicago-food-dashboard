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
import psycopg2
from psycopg2.extras import execute_batch
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

SOCRATA_URL = "https://data.cityofchicago.org/resource/4ijn-s7e5.json"
BATCH_SIZE  = 1000
LIMIT       = 50000   # ~50k most recent records; raise to pull full dataset

DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", "5432")),
    "dbname":   os.getenv("DB_NAME",     "food_inspections"),
    "user":     os.getenv("DB_USER",     "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def fetch_records(limit: int) -> list[dict]:
    """Fetch records from Socrata API with pagination."""
    records = []
    offset  = 0

    print(f"Fetching up to {limit:,} records from Chicago Data Portal...")

    while offset < limit:
        batch_size = min(BATCH_SIZE, limit - offset)
        params = {
            "$limit":  batch_size,
            "$offset": offset,
            "$order":  "inspection_date DESC",
        }
        response = requests.get(SOCRATA_URL, params=params, timeout=30)
        response.raise_for_status()

        batch = response.json()
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
        "latitude":         float(row["latitude"])  if row.get("latitude")  else None,
        "longitude":        float(row["longitude"]) if row.get("longitude") else None,
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
    results         = EXCLUDED.results,
    violations      = EXCLUDED.violations,
    inspection_date = EXCLUDED.inspection_date;
"""


def get_connection():
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

    with conn.cursor() as cur:
        execute_batch(cur, INSERT_SQL, cleaned, page_size=500)
    conn.commit()

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
