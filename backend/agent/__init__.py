"""Inspection analyst agent: tools + retrieval + guardrails + model loop."""

import time

_cache = {"agent": None, "built": 0.0}
REFRESH_SECONDS = 600


def build_agent():
    """Wire the production agent (BigQuery + Vertex AI). Cached for 10 minutes
    so the 'data through' date in the prompt follows daily refreshes."""
    if _cache["agent"] and time.time() - _cache["built"] < REFRESH_SECONDS:
        return _cache["agent"]

    from backend.bigquery_store import BigQueryWarehouse, table
    from backend.agent.loop import Agent
    from backend.agent.model import GeminiModel
    from backend.agent.retrieval import BigQueryRetriever, VertexEmbedder
    from backend.agent.tools import DATA_TOOLS, search_tool

    db = BigQueryWarehouse()
    rows = db.run(f"SELECT FORMAT_DATE('%Y-%m-%d', MAX(inspection_date)) AS d "
                  f"FROM {table('inspections')}")
    data_through = (rows[0]["d"] if rows else None) or "unknown"
    retriever = BigQueryRetriever(db, VertexEmbedder())
    agent = Agent(GeminiModel(), DATA_TOOLS + [search_tool(retriever)], db, data_through)
    _cache.update(agent=agent, built=time.time())
    return agent
