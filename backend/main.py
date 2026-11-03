"""
Chicago Food Inspections — FastAPI backend.

DATA_BACKEND=postgres (default) runs the original PostgreSQL setup.
DATA_BACKEND=bigquery reads from BigQuery and enables the /agent/ask endpoint.
When STATIC_DIR points at the built React app, the same service serves it.
"""

import json
import os
import queue
import threading
import time
from collections import defaultdict, deque

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.sql import backend_name, metric_sql

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv(
    "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",") if origin.strip()]


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


def _pg_query(sql, params=None):
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def query(sql: str, params=None):
    if backend_name() == "bigquery":
        from backend import bigquery_store
        return bigquery_store.run(sql, params)
    return _pg_query(sql, params)


def query_one(sql: str, params=None):
    rows = query(sql, params)
    return rows[0] if rows else {}


app = FastAPI(
    title="Chicago Food Inspections API",
    description="Inspection metrics and an inspection-analyst agent.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/db")
def database_health():
    """Readiness check: 503 when the database is unreachable."""
    if backend_name() == "bigquery":
        try:
            query("SELECT 1 AS ok")
        except Exception:
            raise HTTPException(status_code=503, detail="Database unavailable")
        return {"status": "ok", "database": "bigquery"}
    try:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        finally:
            conn.close()
    except psycopg2.Error:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"status": "ok", "database": "connected"}


@app.get("/metrics/pass-fail-trend")
def pass_fail_trend():
    """Monthly pass vs fail counts for the last 24 months."""
    return query(metric_sql("pass_fail_trend"))


@app.get("/metrics/risk-distribution")
def risk_distribution():
    """Failure rate by risk level."""
    return query(metric_sql("risk_distribution"))


@app.get("/metrics/top-facility-types")
def top_facility_types():
    """Top 10 facility types by inspection volume."""
    return query(metric_sql("top_facility_types"))


@app.get("/metrics/zip-fail-rates")
def zip_fail_rates():
    """Top 15 ZIP codes by failure count."""
    return query(metric_sql("zip_fail_rates"))


@app.get("/metrics/kpi-summary")
def kpi_summary():
    """Top-level KPIs."""
    return query_one(metric_sql("kpi_summary"))


@app.get("/metrics/freshness")
def freshness():
    """Newest inspection loaded and when the ETL last succeeded."""
    return query_one(metric_sql("freshness"))


# ── Agent ────────────────────────────────────────────────────────────────────

ASK_LIMIT = int(os.getenv("ASK_RATE_LIMIT", "12"))       # questions ...
ASK_WINDOW = int(os.getenv("ASK_RATE_WINDOW", "600"))    # ... per 10 minutes per client
_recent = defaultdict(deque)
_recent_lock = threading.Lock()


def _allow(client_id: str) -> bool:
    now = time.time()
    with _recent_lock:
        hits = _recent[client_id]
        while hits and now - hits[0] > ASK_WINDOW:
            hits.popleft()
        if len(hits) >= ASK_LIMIT:
            return False
        hits.append(now)
        return True


class Question(BaseModel):
    question: str


def get_agent():
    from backend.agent import build_agent
    return build_agent()


@app.post("/agent/ask")
def ask(body: Question, request: Request):
    """Stream the agent's work as newline-delimited JSON events:
    tool_start, tool_end, then one final 'answer' (or 'error')."""
    if backend_name() != "bigquery" and not os.getenv("AGENT_ALLOW_ANY_BACKEND"):
        raise HTTPException(status_code=503, detail="The agent runs on the BigQuery backend.")
    forwarded = request.headers.get("x-forwarded-for", "")
    client_id = forwarded.split(",")[0].strip() or (request.client.host if request.client else "?")
    if not _allow(client_id):
        raise HTTPException(status_code=429, detail="Too many questions. Try again in a few minutes.")

    try:
        agent = get_agent()
    except Exception as exc:
        print(f"[agent] could not start: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=503, detail="The agent is not available right now.")
    events: queue.Queue = queue.Queue()

    def work():
        try:
            result = agent.ask(body.question, on_event=lambda k, d: events.put({"type": k, **d}))
            events.put({"type": "answer", **result.public()})
        except Exception as exc:
            print(f"[agent] error: {type(exc).__name__}: {exc}")
            events.put({"type": "error", "detail": "The agent hit an error. Please try again."})
        events.put(None)

    threading.Thread(target=work, daemon=True).start()

    def stream():
        while (event := events.get()) is not None:
            yield json.dumps(event, default=str) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


# ── Static frontend (single-service deploys) ────────────────────────────────

STATIC_DIR = os.getenv("STATIC_DIR", "")
if STATIC_DIR and os.path.isdir(STATIC_DIR):
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")
