"""Dashboard metric queries in two SQL dialects.

The API can run on PostgreSQL (local / Railway) or BigQuery (GCP). Each metric
has one query per dialect so the endpoints stay identical across backends.
"""

import os

POSTGRES = {
    "pass_fail_trend": """
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
    """,
    "risk_distribution": """
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
    """,
    "top_facility_types": """
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
    """,
    "zip_fail_rates": """
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
    """,
    "kpi_summary": """
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
    """,
    "freshness": """
        SELECT
            TO_CHAR(MAX(inspection_date), 'YYYY-MM-DD') AS latest_inspection_date,
            TO_CHAR(MIN(inspection_date), 'YYYY-MM-DD') AS earliest_inspection_date,
            NULL::TEXT                                  AS last_refresh_at,
            NULL::BIGINT                                AS rows_merged_last_run
        FROM inspections;
    """,
}

# BigQuery versions. {t} is the fully qualified inspections table and
# {runs} the ETL run log, e.g. `my-project.food_safety.inspections`.
BIGQUERY = {
    "pass_fail_trend": """
        SELECT
            FORMAT_DATE('%Y-%m', DATE_TRUNC(inspection_date, MONTH)) AS month,
            COUNTIF(results = 'Pass')               AS pass,
            COUNTIF(results = 'Fail')               AS fail,
            COUNTIF(results = 'Pass w/ Conditions') AS pass_conditions
        FROM {t}
        WHERE inspection_date >= DATE_SUB(CURRENT_DATE('America/Chicago'), INTERVAL 24 MONTH)
          AND results IN ('Pass', 'Fail', 'Pass w/ Conditions')
        GROUP BY 1
        ORDER BY 1
    """,
    "risk_distribution": """
        SELECT
            risk,
            COUNT(*)                  AS total,
            COUNTIF(results = 'Fail') AS failed,
            ROUND(100 * SAFE_DIVIDE(COUNTIF(results = 'Fail'), COUNT(*)), 1) AS fail_rate_pct
        FROM {t}
        WHERE risk IS NOT NULL
        GROUP BY risk
        ORDER BY CASE risk WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 WHEN 'Low' THEN 3 ELSE 4 END
    """,
    "top_facility_types": """
        SELECT
            facility_type,
            COUNT(*)                  AS total_inspections,
            COUNTIF(results = 'Pass') AS passed,
            COUNTIF(results = 'Fail') AS failed,
            ROUND(100 * SAFE_DIVIDE(COUNTIF(results = 'Pass'), COUNT(*)), 1) AS pass_rate_pct
        FROM {t}
        WHERE facility_type IS NOT NULL
        GROUP BY facility_type
        ORDER BY total_inspections DESC
        LIMIT 10
    """,
    "zip_fail_rates": """
        SELECT
            zip,
            COUNT(*)                  AS total_inspections,
            COUNTIF(results = 'Fail') AS failed,
            ROUND(100 * SAFE_DIVIDE(COUNTIF(results = 'Fail'), COUNT(*)), 1) AS fail_rate_pct
        FROM {t}
        WHERE zip IS NOT NULL
        GROUP BY zip
        HAVING COUNT(*) >= 20
        ORDER BY failed DESC
        LIMIT 15
    """,
    "kpi_summary": """
        SELECT
            COUNT(*)                  AS total_inspections,
            COUNTIF(results = 'Pass') AS total_passed,
            COUNTIF(results = 'Fail') AS total_failed,
            ROUND(100 * SAFE_DIVIDE(COUNTIF(results = 'Pass'), COUNT(*)), 1) AS overall_pass_rate,
            COUNTIF(risk = 'High' AND results = 'Fail') AS high_risk_failures,
            ROUND(100 * SAFE_DIVIDE(COUNTIF(risk = 'High' AND results = 'Fail'),
                                    COUNTIF(risk = 'High')), 1) AS high_risk_fail_rate,
            COUNT(DISTINCT zip)       AS zip_codes_covered
        FROM {t}
    """,
    "freshness": """
        SELECT
            (SELECT FORMAT_DATE('%Y-%m-%d', MAX(inspection_date)) FROM {t}) AS latest_inspection_date,
            (SELECT FORMAT_DATE('%Y-%m-%d', MIN(inspection_date)) FROM {t}) AS earliest_inspection_date,
            (SELECT FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%SZ', MAX(finished_at))
               FROM {runs} WHERE status = 'ok')                             AS last_refresh_at,
            (SELECT ARRAY_AGG(rows_merged ORDER BY finished_at DESC LIMIT 1)[SAFE_OFFSET(0)]
               FROM {runs} WHERE status = 'ok')                             AS rows_merged_last_run
    """,
}


def backend_name() -> str:
    return os.getenv("DATA_BACKEND", "postgres").strip().lower()


def metric_sql(name: str) -> str:
    """Return the query for a metric in the active backend's dialect."""
    if backend_name() == "bigquery":
        from backend import bigquery_store
        return BIGQUERY[name].format(t=bigquery_store.table("inspections"),
                                     runs=bigquery_store.table("etl_runs"))
    return POSTGRES[name]
