from dataclasses import dataclass

import psycopg
from pgvector.psycopg import register_vector

from .config import DATABASE_URL
from .embedder import embed_query


@dataclass(frozen=True)
class SupportKBHit:
    id: int
    intent: str
    instruction: str
    response: str
    similarity: float


def _connect() -> psycopg.Connection:
    conn = psycopg.connect(DATABASE_URL)
    register_vector(conn)
    return conn


def search(query: str, top_k: int = 3) -> list[SupportKBHit]:
    """Embed a text query and return the top-k most similar support_kb entries.

    Similarity is cosine similarity in [0, 1], computed from pgvector's
    cosine distance operator (1 - distance) since embeddings are
    normalized at ingestion and query time.
    """
    query_embedding = embed_query(query)

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, intent, instruction, response,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM support_kb
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (query_embedding, query_embedding, top_k),
        ).fetchall()

    return [
        SupportKBHit(
            id=row[0],
            intent=row[1],
            instruction=row[2],
            response=row[3],
            similarity=float(row[4]),
        )
        for row in rows
    ]
