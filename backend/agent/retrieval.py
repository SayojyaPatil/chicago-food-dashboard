"""Document search over the Chicago Food Code Rules.

Ingestion (scripts/ingest_food_code.py) splits the PDF into one chunk per code
section, embeds each chunk with Vertex AI, and stores the vectors in BigQuery.
At question time the query is embedded the same way and BigQuery's
VECTOR_SEARCH returns the closest sections by cosine distance.
"""

import math
import os
import re
from dataclasses import dataclass

EMBED_MODEL = os.getenv("EMBED_MODEL", "gemini-embedding-001")
EMBED_DIM = int(os.getenv("EMBED_DIM", "768"))
MAX_CHUNK_CHARS = 1800
OVERLAP_CHARS = 200

# Section headings look like "3-501.16 Time/Temperature Control for Safety Food..."
_SECTION = re.compile(r"(?m)^\s*(\d-\d{3}\.\d{2,3})\s+([^\n]{3,160})$")


@dataclass
class Chunk:
    chunk_id: str
    section: str
    title: str
    text: str
    score: float = 0.0


def _windows(text: str, size=MAX_CHUNK_CHARS, overlap=OVERLAP_CHARS):
    if len(text) <= size:
        return [text]
    out, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):  # break at a sentence or line end when possible
            cut = max(text.rfind(". ", start, end), text.rfind("\n", start, end))
            if cut > start + size // 2:
                end = cut + 1
        out.append(text[start:end].strip())
        if end >= len(text):
            break
        start = end - overlap
    return out


def chunk_food_code(text: str) -> list[Chunk]:
    """Split code text into section-sized chunks.

    The table of contents repeats every heading with no body, so a heading is
    kept only when real text follows it; the longest body per section wins.
    """
    text = text.replace("\r", "")
    matches = list(_SECTION.finditer(text))
    bodies: dict[str, tuple[str, str]] = {}
    for i, match in enumerate(matches):
        section, title = match.group(1), match.group(2).strip().rstrip(".")
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[match.end():end].strip()
        body = re.sub(r"[ \t]+", " ", body)
        body = re.sub(r"\n{3,}", "\n\n", body)
        if len(body) < 60:
            continue
        if section not in bodies or len(body) > len(bodies[section][1]):
            bodies[section] = (title, body)

    chunks = []
    for section, (title, body) in bodies.items():
        for n, window in enumerate(_windows(body)):
            chunks.append(Chunk(f"{section}#{n}", section, title, f"{section} {title}. {window}"))
    return chunks


class VertexEmbedder:
    """Embeds text with a Vertex AI embedding model."""

    def __init__(self, client=None, model=EMBED_MODEL, dim=EMBED_DIM):
        self.model, self.dim = model, dim
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(
                vertexai=True,
                project=os.environ.get("GCP_PROJECT"),
                location=os.getenv("VERTEX_LOCATION", "global"),
            )
        return self._client

    def embed(self, texts: list[str], task: str) -> list[list[float]]:
        from google.genai import types
        vectors = []
        for text in texts:  # one per request keeps us inside per-request limits
            result = self.client.models.embed_content(
                model=self.model, contents=text,
                config=types.EmbedContentConfig(task_type=task, output_dimensionality=self.dim),
            )
            vectors.append([float(x) for x in result.embeddings[0].values])
        return vectors


class BigQueryRetriever:
    def __init__(self, warehouse, embedder):
        self.db, self.embedder = warehouse, embedder

    def search(self, query: str, k: int = 4) -> list[Chunk]:
        vector = self.embedder.embed([query], "RETRIEVAL_QUERY")[0]
        rows = self.db.run(f"""
            SELECT base.chunk_id, base.section, base.title, base.text, distance
            FROM VECTOR_SEARCH(
                TABLE {self.db.table('food_code_chunks')}, 'embedding',
                (SELECT @vector AS embedding),
                top_k => @k, distance_type => 'COSINE')
            ORDER BY distance
        """, {"vector": vector, "k": k})
        return [Chunk(r["chunk_id"], r["section"], r["title"], r["text"],
                      1.0 - float(r["distance"])) for r in rows]


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class InMemoryRetriever:
    """Same interface as BigQueryRetriever; used in tests and local dev."""

    def __init__(self, chunks: list[Chunk], embedder):
        self.embedder = embedder
        self.chunks = chunks
        self.vectors = embedder.embed([c.text for c in chunks], "RETRIEVAL_DOCUMENT")

    def search(self, query: str, k: int = 4) -> list[Chunk]:
        q = self.embedder.embed([query], "RETRIEVAL_QUERY")[0]
        scored = sorted(((cosine(q, v), c) for v, c in zip(self.vectors, self.chunks)),
                        key=lambda pair: pair[0], reverse=True)
        return [Chunk(c.chunk_id, c.section, c.title, c.text, s) for s, c in scored[:k]]
