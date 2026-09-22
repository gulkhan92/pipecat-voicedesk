"""Phase 1 step 1: download the Bitext support dataset, clean it, and load
it into the support_kb table in PostgreSQL.

Usage:
    uv run python scripts/load_support_kb.py
"""

import sys
from pathlib import Path

import pandas as pd
import psycopg
from datasets import load_dataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from voicedesk_retrieval.config import DATABASE_URL  # noqa: E402

RAW_CSV = ROOT / "data" / "raw" / "support_kb.csv"
CLEANED_PARQUET = ROOT / "data" / "processed" / "support_kb_cleaned.parquet"
DATASET_NAME = "bitext/Bitext-customer-support-llm-chatbot-training-dataset"


def download() -> pd.DataFrame:
    RAW_CSV.parent.mkdir(parents=True, exist_ok=True)
    dataset = load_dataset(DATASET_NAME)
    df = dataset["train"].to_pandas()
    df.to_csv(RAW_CSV, index=False)
    print(f"Downloaded {len(df)} rows to {RAW_CSV}")
    return df


def clean(df: pd.DataFrame) -> pd.DataFrame:
    intent_column = "intent" if "intent" in df.columns else "category"
    cleaned = df[["instruction", "response", intent_column]].rename(
        columns={intent_column: "intent"}
    )
    cleaned["instruction"] = cleaned["instruction"].str.strip()
    cleaned["response"] = cleaned["response"].str.strip()
    cleaned["intent"] = cleaned["intent"].str.strip()
    cleaned = cleaned.dropna(subset=["instruction", "response", "intent"])
    cleaned = cleaned[
        (cleaned["instruction"] != "") & (cleaned["response"] != "")
    ]
    cleaned = cleaned.drop_duplicates(subset=["instruction", "response"])
    cleaned = cleaned.reset_index(drop=True)

    CLEANED_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    cleaned.to_parquet(CLEANED_PARQUET, index=False)
    print(f"Cleaned to {len(cleaned)} rows, saved to {CLEANED_PARQUET}")
    return cleaned


def load_into_postgres(df: pd.DataFrame) -> None:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE support_kb RESTART IDENTITY")
            with cur.copy(
                "COPY support_kb (intent, instruction, response) FROM STDIN"
            ) as copy:
                for row in df.itertuples(index=False):
                    copy.write_row((row.intent, row.instruction, row.response))
        conn.commit()
    print(f"Loaded {len(df)} rows into support_kb")


def main() -> None:
    if RAW_CSV.exists():
        print(f"Using existing download at {RAW_CSV}")
        df = pd.read_csv(RAW_CSV)
    else:
        df = download()

    cleaned = clean(df)
    load_into_postgres(cleaned)


if __name__ == "__main__":
    main()
