"""Build the food-code search index in BigQuery.

Downloads the Chicago Food Code Rules PDF (or reads a local copy), splits it
into one chunk per code section, embeds each chunk with Vertex AI, and replaces
the `food_code_chunks` table.

    GCP_PROJECT=my-project python scripts/ingest_food_code.py
    GCP_PROJECT=my-project python scripts/ingest_food_code.py --pdf ./food-code.pdf
    python scripts/ingest_food_code.py --pdf ./food-code.pdf --dry-run   # no GCP needed

Run it once, and again only when the city publishes new rules.
"""

import argparse
import io
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from backend.agent.retrieval import chunk_food_code, VertexEmbedder  # noqa: E402

SOURCE_URL = ("https://www.chicago.gov/content/dam/city/depts/dol/rulesandregs/"
              "CDPH-Food-Code-Rules-02-01-2019.pdf")


def read_pdf(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", help="local PDF instead of downloading")
    parser.add_argument("--dry-run", action="store_true", help="chunk only; print stats")
    args = parser.parse_args(argv)

    if args.pdf:
        data = pathlib.Path(args.pdf).read_bytes()
    else:
        import requests
        print(f"Downloading {SOURCE_URL}")
        response = requests.get(SOURCE_URL, timeout=60)
        if response.status_code == 403:
            raise SystemExit("chicago.gov blocks script downloads. Open the URL above in a browser, "
                             "save the PDF, then run again with --pdf <path>.")
        response.raise_for_status()
        data = response.content

    chunks = chunk_food_code(read_pdf(data))
    sections = {c.section for c in chunks}
    print(f"{len(chunks)} chunks from {len(sections)} sections")
    if not chunks:
        raise SystemExit("No sections found; check that the PDF has a text layer.")
    for c in chunks[:3]:
        print(f"  {c.chunk_id}: {c.text[:90]}...")
    if args.dry_run:
        return 0

    embedder = VertexEmbedder()
    rows = []
    for i, chunk in enumerate(chunks, 1):
        vector = embedder.embed([chunk.text], "RETRIEVAL_DOCUMENT")[0]
        rows.append({"chunk_id": chunk.chunk_id, "section": chunk.section,
                     "title": chunk.title, "text": chunk.text,
                     "source": SOURCE_URL, "embedding": vector})
        if i % 50 == 0:
            print(f"  embedded {i}/{len(chunks)}")

    from google.cloud import bigquery
    from backend import bigquery_store as bq
    schema = [
        bigquery.SchemaField("chunk_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("section", "STRING"),
        bigquery.SchemaField("title", "STRING"),
        bigquery.SchemaField("text", "STRING"),
        bigquery.SchemaField("source", "STRING"),
        bigquery.SchemaField("embedding", "FLOAT64", mode="REPEATED"),
    ]
    job = bq.client().load_table_from_json(
        rows, bq.table_id("food_code_chunks"),
        job_config=bigquery.LoadJobConfig(
            schema=schema, write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE))
    job.result()
    print(f"Loaded {len(rows)} chunks into {bq.table_id('food_code_chunks')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
