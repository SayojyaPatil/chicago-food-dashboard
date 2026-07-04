"""
Chicago Food Inspections — FastAPI Backend
Uses psycopg2 (sync) to avoid asyncpg Python 3.13 compile issues.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
import psycopg2.extras
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")

# Parse DATABASE_URL or fall back to individual vars
def get_conn():
    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL)
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "food_inspections"),
        user=os.getenv("DB_USER", os.getenv("USER", "postgres")),
        password=os.getenv("DB_PASSWORD", ""),
    )

def query(sql: str, params=None):
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

def query_one(sql: str, params=None):
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else {}
    finally:
        conn.close()


app = FastAPI(
    title="Chicago Food Inspections API",
    description="Aggregated BI metrics from Chicago Dept of Public Health inspection data.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics/pass-fail-trend")
def pass_fail_trend():
    """Monthly pass vs fail counts for the last 24 months."""
    return query("""
        SELECT
            TO_CHAR(DATE_TRUNC('month', inspection_date), 'YYYY-MM') AS month,
            COUNT(*) FILTER (WHERE results = 'Pass')               AS pass,
            COUNT(*) FILTER (WHERE results = 'Fail')               AS fail,
            COUNT(*) FILTER (WHERE results = 'Pass w/ Conditions') AS pass_conditions
        FROM inspections
        WHERE inspection_date >= NOW() - INTERVAL '24 months'
          AND results IN ('Pass', 'Fail', 'Pass w/ Conditions')
        GROUP BY 1
        ORDER BY 1;
    """)


@app.get("/metrics/risk-distribution")
def risk_distribution():
    """Count of inspections by risk level."""
    return query("""
        SELECT
            risk,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE results = 'Fail')  AS failed,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE results = 'Fail') / NULLIF(COUNT(*), 0), 1
            ) AS fail_rate_pct
        FROM inspections
        WHERE risk IS NOT NULL
        GROUP BY risk
        ORDER BY
            CASE risk
                WHEN 'High'   THEN 1
                WHEN 'Medium' THEN 2
                WHEN 'Low'    THEN 3
                ELSE 4
            END;
    """)


@app.get("/metrics/top-facility-types")
def top_facility_types():
    """Top 10 facility types by inspection volume."""
    return query("""
        SELECT
            facility_type,
            COUNT(*)                                               AS total_inspections,
            COUNT(*) FILTER (WHERE results = 'Pass')              AS passed,
            COUNT(*) FILTER (WHERE results = 'Fail')              AS failed,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE results = 'Pass') / NULLIF(COUNT(*), 0), 1
            ) AS pass_rate_pct
        FROM inspections
        WHERE facility_type IS NOT NULL
        GROUP BY facility_type
        ORDER BY total_inspections DESC
        LIMIT 10;
    """)


@app.get("/metrics/zip-fail-rates")
def zip_fail_rates():
    """Top 15 zip codes by failure count."""
    return query("""
        SELECT
            zip,
            COUNT(*)                                              AS total_inspections,
            COUNT(*) FILTER (WHERE results = 'Fail')             AS failed,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE results = 'Fail') / NULLIF(COUNT(*), 0), 1
            ) AS fail_rate_pct
        FROM inspections
        WHERE zip IS NOT NULL
        GROUP BY zip
        HAVING COUNT(*) >= 20
        ORDER BY failed DESC
        LIMIT 15;
    """)


@app.get("/metrics/kpi-summary")
def kpi_summary():
    """Top-level KPIs."""
    return query_one("""
        SELECT
            COUNT(*)                                                          AS total_inspections,
            COUNT(*) FILTER (WHERE results = 'Pass')                         AS total_passed,
            COUNT(*) FILTER (WHERE results = 'Fail')                         AS total_failed,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE results = 'Pass') / NULLIF(COUNT(*), 0), 1
            )                                                                 AS overall_pass_rate,
            COUNT(*) FILTER (WHERE risk = 'High' AND results = 'Fail')       AS high_risk_failures,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE risk = 'High' AND results = 'Fail')
                / NULLIF(COUNT(*) FILTER (WHERE risk = 'High'), 0), 1
            )                                                                 AS high_risk_fail_rate,
            COUNT(DISTINCT zip)                                               AS zip_codes_covered
        FROM inspections;
    """)
