"""Dashboard metric queries in two SQL dialects.

The API can run on PostgreSQL (local / Railway) or BigQuery (GCP). Each metric
has one query per dialect so the endpoints stay identical across backends.

Shared definitions (the agent's tools use the same ones):
- Only real outcomes count: Pass, Pass w/ Conditions, Fail. Records such as
  "Out of Business", "No Entry" or "Not Ready" are not inspections of food safety.
- "Recent" means the 12 months up to the newest inspection loaded, so a stale
  snapshot still shows a full year instead of an empty window.
- Violation titles come from each "NN. TITLE - Comments: ..." item in the
  violations text, split on "|".
"""

import os

OUTCOMES = "('Pass', 'Pass w/ Conditions', 'Fail')"

POSTGRES = {
    "pass_fail_trend": f"""
        SELECT
            TO_CHAR(DATE_TRUNC('month', inspection_date), 'YYYY-MM') AS month,
            COUNT(*)                                               AS inspections,
            COUNT(*) FILTER (WHERE results = 'Pass')               AS pass,
            COUNT(*) FILTER (WHERE results = 'Pass w/ Conditions') AS pass_conditions,
            COUNT(*) FILTER (WHERE results = 'Fail')               AS fail,
            ROUND(100.0 * COUNT(*) FILTER (WHERE results = 'Fail') / NULLIF(COUNT(*), 0), 1)
                                                                   AS fail_rate_pct
        FROM inspections
        WHERE results IN {OUTCOMES}
          AND inspection_date >= DATE_TRUNC('month',
                (SELECT MAX(inspection_date) FROM inspections) - INTERVAL '23 months')
        GROUP BY 1
        ORDER BY 1;
    """,
    "risk_distribution": f"""
        SELECT
            risk,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE results = 'Fail') AS failed,
            ROUND(100.0 * COUNT(*) FILTER (WHERE results = 'Fail') / NULLIF(COUNT(*), 0), 1)
                AS fail_rate_pct
        FROM inspections
        WHERE risk IN ('High', 'Medium', 'Low') AND results IN {OUTCOMES}
          AND inspection_date > (SELECT MAX(inspection_date) FROM inspections) - INTERVAL '12 months'
        GROUP BY risk
        ORDER BY CASE risk WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END;
    """,
    "top_facility_types": f"""
        SELECT
            facility_type,
            COUNT(*)                                               AS total_inspections,
            COUNT(*) FILTER (WHERE results = 'Fail')               AS failed,
            ROUND(100.0 * COUNT(*) FILTER (WHERE results = 'Fail') / NULLIF(COUNT(*), 0), 1)
                                                                   AS fail_rate_pct
        FROM inspections
        WHERE facility_type IS NOT NULL AND results IN {OUTCOMES}
          AND inspection_date > (SELECT MAX(inspection_date) FROM inspections) - INTERVAL '12 months'
        GROUP BY facility_type
        ORDER BY total_inspections DESC
        LIMIT 10;
    """,
    "zip_fail_rates": f"""
        SELECT
            zip,
            COUNT(*)                                               AS total_inspections,
            COUNT(*) FILTER (WHERE results = 'Fail')               AS failed,
            ROUND(100.0 * COUNT(*) FILTER (WHERE results = 'Fail') / NULLIF(COUNT(*), 0), 1)
                                                                   AS fail_rate_pct
        FROM inspections
        WHERE zip IS NOT NULL AND results IN {OUTCOMES}
          AND inspection_date > (SELECT MAX(inspection_date) FROM inspections) - INTERVAL '12 months'
        GROUP BY zip
        HAVING COUNT(*) >= 100
        ORDER BY fail_rate_pct DESC, total_inspections DESC
        LIMIT 200;
    """,
    "top_violations": f"""
        WITH recent AS (
            SELECT inspection_id, violations
            FROM inspections
            WHERE results IN {OUTCOMES}
              AND inspection_date > (SELECT MAX(inspection_date) FROM inspections) - INTERVAL '12 months'
        ),
        items AS (
            SELECT inspection_id, trim(item) AS item
            FROM recent, regexp_split_to_table(violations, '\\|') AS item
            WHERE violations IS NOT NULL
        )
        SELECT
            CAST(substring(item from '^([0-9]+)\\.') AS INTEGER)   AS violation_number,
            MIN(trim(regexp_replace(split_part(item, ' - Comments', 1), '^[0-9]+\\.\\s*', '')))
                                                                   AS title,
            COUNT(DISTINCT inspection_id)                          AS inspections_cited,
            ROUND(100.0 * COUNT(DISTINCT inspection_id) / (SELECT COUNT(*) FROM recent), 1)
                                                                   AS share_pct
        FROM items
        WHERE substring(item from '^([0-9]+)\\.') IS NOT NULL
        GROUP BY 1
        ORDER BY inspections_cited DESC
        LIMIT 10;
    """,
    "kpi_summary": f"""
        WITH bounds AS (SELECT MAX(inspection_date) AS latest FROM inspections),
        recent AS (
            SELECT results, zip FROM inspections, bounds
            WHERE results IN {OUTCOMES} AND inspection_date > latest - INTERVAL '12 months'
        ),
        prior AS (
            SELECT results FROM inspections, bounds
            WHERE results IN {OUTCOMES}
              AND inspection_date >  latest - INTERVAL '24 months'
              AND inspection_date <= latest - INTERVAL '12 months'
        )
        SELECT
            (SELECT COUNT(*) FROM recent)                                         AS total_inspections,
            (SELECT COUNT(*) FROM recent WHERE results = 'Pass')                  AS total_passed,
            (SELECT COUNT(*) FROM recent WHERE results = 'Pass w/ Conditions')    AS total_passed_conditions,
            (SELECT COUNT(*) FROM recent WHERE results = 'Fail')                  AS total_failed,
            (SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE results = 'Pass') / NULLIF(COUNT(*), 0), 1)
               FROM recent)                                                       AS overall_pass_rate,
            (SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE results = 'Pass w/ Conditions')
                    / NULLIF(COUNT(*), 0), 1) FROM recent)                        AS conditions_rate,
            (SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE results = 'Fail') / NULLIF(COUNT(*), 0), 1)
               FROM recent)                                                       AS fail_rate,
            (SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE results = 'Fail') / NULLIF(COUNT(*), 0), 1)
               FROM prior)                                                        AS prior_fail_rate,
            (SELECT COUNT(DISTINCT zip) FROM recent)                              AS zip_codes_covered;
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
_BQ_LATEST = "(SELECT MAX(inspection_date) FROM {t})"

BIGQUERY = {
    "pass_fail_trend": f"""
        SELECT
            FORMAT_DATE('%Y-%m', DATE_TRUNC(inspection_date, MONTH)) AS month,
            COUNT(*)                                AS inspections,
            COUNTIF(results = 'Pass')               AS pass,
            COUNTIF(results = 'Pass w/ Conditions') AS pass_conditions,
            COUNTIF(results = 'Fail')               AS fail,
            ROUND(100 * SAFE_DIVIDE(COUNTIF(results = 'Fail'), COUNT(*)), 1) AS fail_rate_pct
        FROM {{t}}
        WHERE results IN {OUTCOMES}
          AND inspection_date >= DATE_TRUNC(DATE_SUB({_BQ_LATEST}, INTERVAL 23 MONTH), MONTH)
        GROUP BY 1
        ORDER BY 1
    """,
    "risk_distribution": f"""
        SELECT
            risk,
            COUNT(*)                  AS total,
            COUNTIF(results = 'Fail') AS failed,
            ROUND(100 * SAFE_DIVIDE(COUNTIF(results = 'Fail'), COUNT(*)), 1) AS fail_rate_pct
        FROM {{t}}
        WHERE risk IN ('High', 'Medium', 'Low') AND results IN {OUTCOMES}
          AND inspection_date > DATE_SUB({_BQ_LATEST}, INTERVAL 12 MONTH)
        GROUP BY risk
        ORDER BY CASE risk WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END
    """,
    "top_facility_types": f"""
        SELECT
            facility_type,
            COUNT(*)                  AS total_inspections,
            COUNTIF(results = 'Fail') AS failed,
            ROUND(100 * SAFE_DIVIDE(COUNTIF(results = 'Fail'), COUNT(*)), 1) AS fail_rate_pct
        FROM {{t}}
        WHERE facility_type IS NOT NULL AND results IN {OUTCOMES}
          AND inspection_date > DATE_SUB({_BQ_LATEST}, INTERVAL 12 MONTH)
        GROUP BY facility_type
        ORDER BY total_inspections DESC
        LIMIT 10
    """,
    "zip_fail_rates": f"""
        SELECT
            zip,
            COUNT(*)                  AS total_inspections,
            COUNTIF(results = 'Fail') AS failed,
            ROUND(100 * SAFE_DIVIDE(COUNTIF(results = 'Fail'), COUNT(*)), 1) AS fail_rate_pct
        FROM {{t}}
        WHERE zip IS NOT NULL AND results IN {OUTCOMES}
          AND inspection_date > DATE_SUB({_BQ_LATEST}, INTERVAL 12 MONTH)
        GROUP BY zip
        HAVING COUNT(*) >= 100
        ORDER BY fail_rate_pct DESC, total_inspections DESC
        LIMIT 200
    """,
    "top_violations": f"""
        WITH recent AS (
            SELECT inspection_id, violations
            FROM {{t}}
            WHERE results IN {OUTCOMES}
              AND inspection_date > DATE_SUB({_BQ_LATEST}, INTERVAL 12 MONTH)
        ),
        items AS (
            SELECT inspection_id, TRIM(item) AS item
            FROM recent, UNNEST(SPLIT(violations, '|')) AS item
            WHERE violations IS NOT NULL
        )
        SELECT
            SAFE_CAST(REGEXP_EXTRACT(item, r'^(\\d+)\\.') AS INT64) AS violation_number,
            MIN(TRIM(REGEXP_REPLACE(SPLIT(item, ' - Comments')[OFFSET(0)], r'^\\d+\\.\\s*', '')))
                                                                 AS title,
            COUNT(DISTINCT inspection_id)                        AS inspections_cited,
            ROUND(100 * COUNT(DISTINCT inspection_id) / (SELECT COUNT(*) FROM recent), 1)
                                                                 AS share_pct
        FROM items
        WHERE REGEXP_CONTAINS(item, r'^\\d+\\.')
        GROUP BY 1
        ORDER BY inspections_cited DESC
        LIMIT 10
    """,
    "kpi_summary": f"""
        WITH recent AS (
            SELECT results, zip FROM {{t}}
            WHERE results IN {OUTCOMES}
              AND inspection_date > DATE_SUB({_BQ_LATEST}, INTERVAL 12 MONTH)
        ),
        prior AS (
            SELECT results FROM {{t}}
            WHERE results IN {OUTCOMES}
              AND inspection_date >  DATE_SUB({_BQ_LATEST}, INTERVAL 24 MONTH)
              AND inspection_date <= DATE_SUB({_BQ_LATEST}, INTERVAL 12 MONTH)
        )
        SELECT
            (SELECT COUNT(*) FROM recent)                                      AS total_inspections,
            (SELECT COUNTIF(results = 'Pass') FROM recent)                     AS total_passed,
            (SELECT COUNTIF(results = 'Pass w/ Conditions') FROM recent)       AS total_passed_conditions,
            (SELECT COUNTIF(results = 'Fail') FROM recent)                     AS total_failed,
            (SELECT ROUND(100 * SAFE_DIVIDE(COUNTIF(results = 'Pass'), COUNT(*)), 1)
               FROM recent)                                                    AS overall_pass_rate,
            (SELECT ROUND(100 * SAFE_DIVIDE(COUNTIF(results = 'Pass w/ Conditions'), COUNT(*)), 1)
               FROM recent)                                                    AS conditions_rate,
            (SELECT ROUND(100 * SAFE_DIVIDE(COUNTIF(results = 'Fail'), COUNT(*)), 1)
               FROM recent)                                                    AS fail_rate,
            (SELECT ROUND(100 * SAFE_DIVIDE(COUNTIF(results = 'Fail'), COUNT(*)), 1)
               FROM prior)                                                     AS prior_fail_rate,
            (SELECT COUNT(DISTINCT zip) FROM recent)                           AS zip_codes_covered
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
