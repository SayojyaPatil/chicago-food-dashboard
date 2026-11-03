"""Small BigQuery helper shared by the API, the agent tools and the ETL.

Configuration comes from the environment:
    GCP_PROJECT   project that owns the dataset (and pays for queries)
    BQ_DATASET    dataset name, default food_safety
    BQ_LOCATION   dataset location, default US
"""

import datetime as dt
import decimal
import os
from functools import lru_cache

MAX_BYTES_BILLED = int(os.getenv("BQ_MAX_BYTES_BILLED", str(2 * 1024**3)))  # 2 GiB per query


def project() -> str:
    value = os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
    if not value:
        raise RuntimeError("Set GCP_PROJECT to the Google Cloud project ID")
    return value


def dataset() -> str:
    return os.getenv("BQ_DATASET", "food_safety")


def location() -> str:
    return os.getenv("BQ_LOCATION", "US")


def table(name: str) -> str:
    return f"`{project()}.{dataset()}.{name}`"


def table_id(name: str) -> str:
    """Unquoted ID for client APIs (load jobs, inserts)."""
    return f"{project()}.{dataset()}.{name}"


@lru_cache(maxsize=1)
def client():
    from google.cloud import bigquery
    return bigquery.Client(project=project(), location=location())


def _param(name, value):
    from google.cloud import bigquery
    if isinstance(value, bool):
        return bigquery.ScalarQueryParameter(name, "BOOL", value)
    if isinstance(value, int):
        return bigquery.ScalarQueryParameter(name, "INT64", value)
    if isinstance(value, float):
        return bigquery.ScalarQueryParameter(name, "FLOAT64", value)
    if isinstance(value, dt.date):
        return bigquery.ScalarQueryParameter(name, "DATE", value)
    if isinstance(value, (list, tuple)):
        kind = "FLOAT64" if value and isinstance(value[0], float) else "STRING"
        return bigquery.ArrayQueryParameter(name, kind, list(value))
    return bigquery.ScalarQueryParameter(name, "STRING", value)


def _plain(value):
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def run(sql: str, params: dict | None = None) -> list[dict]:
    """Run a parameterized query and return JSON-friendly rows."""
    from google.cloud import bigquery
    config = bigquery.QueryJobConfig(
        query_parameters=[_param(k, v) for k, v in (params or {}).items()],
        maximum_bytes_billed=MAX_BYTES_BILLED,
    )
    rows = client().query(sql, job_config=config).result()
    return [{k: _plain(v) for k, v in row.items()} for row in rows]


class BigQueryWarehouse:
    """Adapter the agent tools use, so tests can swap in a fake."""

    def run(self, sql: str, params: dict | None = None) -> list[dict]:
        return run(sql, params)

    def table(self, name: str) -> str:
        return table(name)
