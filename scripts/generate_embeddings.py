"""Phase 1 step 2: embed every support_kb row and store the vectors in
PostgreSQL, plus a local parquet copy for reference. Rebuilds the HNSW
index afterward for fast lookups.

Usage:
    uv run python scripts/generate_embeddings.py
"""

import sys
from pathlib import Path

import pandas as pd
import psycopg
from pgvector.psycopg import register_vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from voicedesk_retrieval.config import DATABASE_URL  # noqa: E402
from voicedesk_retrieval.embedder import embed_texts  # noqa: E402

EMBEDDINGS_PARQUET = ROOT / "data" / "embeddings" / "support_kb_embeddings.parquet"
BATCH_SIZE = 256


def fetch_rows(conn: psycopg.Connection) -> list[tuple[int, str, str]]:
    return conn.execute(
        "SELECT id, instruction, response FROM support_kb ORDER BY id"
    ).fetchall()


def main() -> None:
    with psycopg.connect(DATABASE_URL) as conn:
        register_vector(conn)
        rows = fetch_rows(conn)
        print(f"Embedding {len(rows)} support_kb rows")

        records = []
        with conn.cursor() as cur:
            for start in range(0, len(rows), BATCH_SIZE):
                batch = rows[start : start + BATCH_SIZE]
                texts = [f"{instruction}\n{response}" for _, instruction, response in batch]
                vectors = embed_texts(texts)

                for (row_id, instruction, response), vector in zip(batch, vectors):
                    cur.execute(
                        "UPDATE support_kb SET embedding = %s WHERE id = %s",
                        (vector, row_id),
                    )
                    records.append({"id": row_id, "embedding": vector})

                print(f"  embedded rows {start + 1}-{start + len(batch)}")

        conn.commit()

        print("Rebuilding HNSW index")
        with conn.cursor() as cur:
            cur.execute("DROP INDEX IF EXISTS support_kb_embedding_hnsw_idx")
            cur.execute(
                "CREATE INDEX support_kb_embedding_hnsw_idx "
                "ON support_kb USING hnsw (embedding vector_cosine_ops)"
            )
        conn.commit()

    EMBEDDINGS_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame.from_records(records).to_parquet(EMBEDDINGS_PARQUET, index=False)
    print(f"Saved embeddings reference copy to {EMBEDDINGS_PARQUET}")


if __name__ == "__main__":
    main()
