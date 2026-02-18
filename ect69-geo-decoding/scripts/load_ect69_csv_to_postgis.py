"""Load ECT69 cleaned voting units into PostGIS as the work queue.

Table populated:
  - ect69.ballot_unit  (from ect69_voting_units_cleaned.parquet)

All rows are inserted with status='pending'.

Usage:
  fnox exec -- uv run python ect69-geo-decoding/scripts/load_ect69_csv_to_postgis.py
"""

import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

PASSWORD = os.environ["POSTGIS_PASSWORD"]
ENGINE = create_engine(f"postgresql://postgres:{PASSWORD}@localhost:5433/postgres")

PARQUET = Path(
    "/home/ben/ddd/ninyawee/ballot-location/ect69-geo-decoding/intermediate/ect69_voting_units_cleaned.parquet"
)


def load_ballot_units():
    print("Loading ECT69 ballot units...")
    df = pd.read_parquet(PARQUET)
    print(f"  {len(df)} rows, columns: {df.columns.tolist()}")

    # Map Thai columns to English schema
    col_map = {
        "จังหวัด": "province",
        "เขตเลือกตั้ง": "electoral_district",
        "อำเภอ": "amphoe",
        "สำนักทะเบียน": "registry",
        "ตำบล": "tambon",
        "หน่วยเลือกตั้ง": "unit_number",
        "สถานที่เลือกตั้ง_raw": "location_raw",
    }

    out = pd.DataFrame()
    for thai_col, eng_col in col_map.items():
        if thai_col in df.columns:
            out[eng_col] = df[thai_col]
        else:
            print(f"  Warning: column '{thai_col}' not found in parquet")
            out[eng_col] = None

    # Ensure types
    if "electoral_district" in out.columns:
        out["electoral_district"] = pd.to_numeric(
            out["electoral_district"], errors="coerce"
        ).astype("Int64")
    if "unit_number" in out.columns:
        out["unit_number"] = pd.to_numeric(out["unit_number"], errors="coerce").astype(
            "Int64"
        )

    out["status"] = "pending"

    # Write to PostGIS (plain table, no geometry)
    out.to_sql(
        "ballot_unit",
        ENGINE,
        schema="ect69",
        if_exists="append",
        index=False,
        method="multi",
        chunksize=5000,
    )
    print(f"  Loaded {len(out)} rows into ect69.ballot_unit")

    # Verify
    with ENGINE.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM ect69.ballot_unit")).scalar()
        print(f"  Verified: {count} rows in ect69.ballot_unit")


if __name__ == "__main__":
    with ENGINE.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("Connected to PostGIS")

    load_ballot_units()
    print("Done.")
