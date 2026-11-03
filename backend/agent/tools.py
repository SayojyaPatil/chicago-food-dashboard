"""Tools the inspection agent can call.

The model never writes SQL. It picks one of these functions and fills in
arguments; each argument is validated here, then bound as a BigQuery query
parameter. That keeps every query read-only, predictable and testable.
"""

import datetime as dt
import re
from dataclasses import dataclass
from typing import Callable

MIN_YEAR = 2010
MAX_ROWS = 15
_ZIP = re.compile(r"^60\d{3}$")

# Inspections whose result is a real outcome (excludes "Out of Business",
# "No Entry", "Not Ready", "Business Not Located").
OUTCOMES = "('Pass', 'Pass w/ Conditions', 'Fail')"


class ToolArgumentError(ValueError):
    pass


def _year(value, name="year") -> int:
    try:
        year = int(value)
    except (TypeError, ValueError):
        raise ToolArgumentError(f"{name} must be a year like 2025")
    this_year = dt.date.today().year
    if not MIN_YEAR <= year <= this_year:
        raise ToolArgumentError(f"{name} must be between {MIN_YEAR} and {this_year}")
    return year


def _limit(value, default=10) -> int:
    if value is None:
        return default
    try:
        return max(1, min(MAX_ROWS, int(value)))
    except (TypeError, ValueError):
        raise ToolArgumentError("limit must be a whole number")


def _zip(value) -> str:
    text = str(value or "").strip()[:5]
    if not _ZIP.match(text):
        raise ToolArgumentError("zip must be a 5-digit Chicago ZIP code such as 60614")
    return text


def _text(value, name, max_len=80) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        raise ToolArgumentError(f"{name} is required")
    if len(text) > max_len:
        raise ToolArgumentError(f"{name} must be under {max_len} characters")
    return text


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ── Tool implementations ─────────────────────────────────────────────────────

def citywide_summary(db, year):
    year = _year(year)
    rows = db.run(f"""
        SELECT
            @year AS year,
            COUNT(*) AS inspections,
            COUNTIF(results = 'Pass') AS passed,
            COUNTIF(results = 'Pass w/ Conditions') AS passed_with_conditions,
            COUNTIF(results = 'Fail') AS failed,
            ROUND(100 * SAFE_DIVIDE(COUNTIF(results = 'Pass'), COUNT(*)), 1) AS pass_rate_pct,
            ROUND(100 * SAFE_DIVIDE(COUNTIF(results = 'Pass w/ Conditions'), COUNT(*)), 1)
                AS pass_with_conditions_rate_pct,
            ROUND(100 * SAFE_DIVIDE(COUNTIF(results IN ('Pass', 'Pass w/ Conditions')), COUNT(*)), 1)
                AS passed_any_rate_pct,
            ROUND(100 * SAFE_DIVIDE(COUNTIF(results = 'Fail'), COUNT(*)), 1) AS fail_rate_pct,
            ROUND(100 * SAFE_DIVIDE(COUNTIF(risk = 'High' AND results = 'Fail'),
                                    COUNTIF(risk = 'High')), 1) AS high_risk_fail_rate_pct,
            FORMAT_DATE('%Y-%m-%d', MAX(inspection_date)) AS data_through
        FROM {db.table('inspections')}
        WHERE EXTRACT(YEAR FROM inspection_date) = @year
          AND results IN {OUTCOMES}
    """, {"year": year})
    return {"rows": rows,
            "note": ("Rates use Pass, Pass w/ Conditions and Fail outcomes only. "
                     "passed_any_rate_pct counts both kinds of pass.")}


def zip_fail_rates(db, year, order="highest", min_inspections=20, limit=10):
    year = _year(year)
    direction = "ASC" if str(order).lower() == "lowest" else "DESC"
    minimum = max(5, min(500, int(min_inspections or 20)))
    rows = db.run(f"""
        SELECT zip,
               COUNT(*) AS inspections,
               COUNTIF(results = 'Fail') AS failed,
               ROUND(100 * SAFE_DIVIDE(COUNTIF(results = 'Fail'), COUNT(*)), 1) AS fail_rate_pct
        FROM {db.table('inspections')}
        WHERE EXTRACT(YEAR FROM inspection_date) = @year
          AND results IN {OUTCOMES} AND zip IS NOT NULL
        GROUP BY zip
        HAVING COUNT(*) >= @minimum
        ORDER BY fail_rate_pct {direction}, inspections DESC
        LIMIT @limit
    """, {"year": year, "minimum": minimum, "limit": _limit(limit)})
    return {"rows": rows, "note": f"ZIP codes with at least {minimum} inspections in {year}."}


def compare_zip_fail_rates(db, year_a, year_b, limit=10):
    year_a, year_b = _year(year_a, "year_a"), _year(year_b, "year_b")
    if year_a == year_b:
        raise ToolArgumentError("year_a and year_b must differ")
    rows = db.run(f"""
        WITH by_year AS (
            SELECT zip, EXTRACT(YEAR FROM inspection_date) AS year,
                   COUNT(*) AS inspections,
                   100 * SAFE_DIVIDE(COUNTIF(results = 'Fail'), COUNT(*)) AS fail_rate
            FROM {db.table('inspections')}
            WHERE EXTRACT(YEAR FROM inspection_date) IN (@year_a, @year_b)
              AND results IN {OUTCOMES} AND zip IS NOT NULL
            GROUP BY zip, year
            HAVING COUNT(*) >= 20
        )
        SELECT a.zip,
               a.inspections AS inspections_a, ROUND(a.fail_rate, 1) AS fail_rate_a_pct,
               b.inspections AS inspections_b, ROUND(b.fail_rate, 1) AS fail_rate_b_pct,
               ROUND(b.fail_rate - a.fail_rate, 1) AS change_pts
        FROM by_year a JOIN by_year b USING (zip)
        WHERE a.year = @year_a AND b.year = @year_b
        ORDER BY change_pts DESC
        LIMIT @limit
    """, {"year_a": year_a, "year_b": year_b, "limit": _limit(limit)})
    return {"rows": rows,
            "note": (f"Positive change_pts = fail rate rose from {year_a} to {year_b}. "
                     "Only ZIPs with 20+ inspections in both years. The current year "
                     "may be partial.")}


def top_violations(db, year, zip=None, facility_type=None, limit=10):
    params = {"year": _year(year), "limit": _limit(limit)}
    filters = ""
    if zip:
        params["zip"] = _zip(zip)
        filters += " AND zip = @zip"
    if facility_type:
        params["facility_type"] = _text(facility_type, "facility_type", 60)
        filters += " AND LOWER(facility_type) = LOWER(@facility_type)"
    rows = db.run(f"""
        WITH scope AS (
            SELECT inspection_id, violations
            FROM {db.table('inspections')}
            WHERE EXTRACT(YEAR FROM inspection_date) = @year
              AND results IN {OUTCOMES} {filters}
        ),
        items AS (
            SELECT inspection_id,
                   SAFE_CAST(REGEXP_EXTRACT(TRIM(item), r'^(\\d+)\\.') AS INT64) AS number,
                   TRIM(REGEXP_REPLACE(SPLIT(TRIM(item), ' - Comments')[OFFSET(0)],
                                       r'^\\d+\\.\\s*', '')) AS title
            FROM scope, UNNEST(SPLIT(violations, '|')) AS item
            WHERE violations IS NOT NULL
        )
        SELECT number AS violation_number,
               ANY_VALUE(title) AS title,
               COUNT(DISTINCT inspection_id) AS inspections_cited,
               ROUND(100 * COUNT(DISTINCT inspection_id) /
                     (SELECT COUNT(*) FROM scope), 1) AS share_of_inspections_pct
        FROM items
        WHERE number IS NOT NULL
        GROUP BY number
        ORDER BY inspections_cited DESC
        LIMIT @limit
    """, params)
    return {"rows": rows,
            "note": "Violation numbers follow the Chicago inspection report checklist."}


def facility_lookup(db, name, limit=5):
    name = _text(name, "name")
    rows = db.run(f"""
        SELECT dba_name, address, zip, facility_type, risk,
               FORMAT_DATE('%Y-%m-%d', inspection_date) AS inspection_date,
               inspection_type, results,
               ARRAY_LENGTH(SPLIT(IFNULL(violations, ''), '|'))
                 - IF(violations IS NULL, 1, 0) AS violation_count
        FROM {db.table('inspections')}
        WHERE LOWER(dba_name) LIKE CONCAT('%', LOWER(@name), '%')
        ORDER BY inspection_date DESC
        LIMIT @limit
    """, {"name": _like_escape(name), "limit": _limit(limit, 5)})
    return {"rows": rows, "note": "Most recent inspections first; names can match several locations."}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    run: Callable


def _schema(properties: dict, required: list) -> dict:
    return {"type": "object", "properties": properties, "required": required}


YEAR = {"type": "integer", "description": "Calendar year, e.g. 2025"}
LIMIT = {"type": "integer", "description": f"Rows to return, 1-{MAX_ROWS}"}

DATA_TOOLS = [
    Tool("citywide_summary",
         "Citywide inspection counts and pass/fail rates for one calendar year.",
         _schema({"year": YEAR}, ["year"]), citywide_summary),
    Tool("zip_fail_rates",
         "Fail rate by ZIP code for one year, ranked highest or lowest.",
         _schema({"year": YEAR,
                  "order": {"type": "string", "enum": ["highest", "lowest"]},
                  "min_inspections": {"type": "integer",
                                      "description": "Minimum inspections per ZIP (default 20)"},
                  "limit": LIMIT}, ["year"]), zip_fail_rates),
    Tool("compare_zip_fail_rates",
         "Change in ZIP-code fail rates between two years, largest increase first.",
         _schema({"year_a": YEAR, "year_b": YEAR, "limit": LIMIT},
                 ["year_a", "year_b"]), compare_zip_fail_rates),
    Tool("top_violations",
         "Most frequently cited violations in a year, optionally for one ZIP code "
         "or facility type (e.g. Restaurant, Grocery Store, School).",
         _schema({"year": YEAR,
                  "zip": {"type": "string", "description": "5-digit Chicago ZIP code"},
                  "facility_type": {"type": "string"},
                  "limit": LIMIT}, ["year"]), top_violations),
    Tool("facility_lookup",
         "Recent inspections for businesses whose name contains the given text.",
         _schema({"name": {"type": "string"}, "limit": LIMIT}, ["name"]), facility_lookup),
]


def search_tool(retriever) -> Tool:
    def search_food_code(_db, query, k=4):
        query = _text(query, "query", 200)
        k = max(1, min(6, int(k or 4)))
        hits = retriever.search(query, k)
        return {"passages": [
            {"section": h.section, "title": h.title, "text": h.text[:1500],
             "score": round(h.score, 3)} for h in hits],
            "note": "Excerpts from the Chicago Food Code Rules (CDPH)."}

    return Tool(
        "search_food_code",
        "Search the Chicago Food Code Rules for the requirement behind a violation "
        "or a food-safety question. Returns passages with section numbers.",
        _schema({"query": {"type": "string"},
                 "k": {"type": "integer", "description": "Passages to return, 1-6"}},
                ["query"]),
        search_food_code,
    )
