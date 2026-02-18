"""Load ECT66 geocoded data + raw responses into PostGIS.

Tables populated:
  - ref.ect66_geocoded       (from ect66_geocoded_validated.parquet)
  - ref.ect66_raw_responses  (from ect_batch_[1-3].parquet GMap column)

Usage:
  fnox exec -- uv run python ect69-geo-decoding/scripts/load_ect66_to_postgis.py
"""

import json
import os
from pathlib import Path

import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from sqlalchemy import create_engine, text

PASSWORD = os.environ["POSTGIS_PASSWORD"]
ENGINE = create_engine(f"postgresql://postgres:{PASSWORD}@localhost:5433/postgres")

BASE = Path("/home/ben/ddd/ninyawee/ballot-location")
ECT66_PARQUET = BASE / "ect66-geo-decoding/outputs/ect66_geocoded_validated.parquet"
BATCH_DIR = BASE / "ect66-geo-decoding/intermediate"


def load_ect66_geocoded():
    print("Loading ECT66 geocoded data...")
    df = pd.read_parquet(ECT66_PARQUET)
    print(f"  {len(df)} rows, columns: {df.columns.tolist()}")

    # Build geometry from Lat/Lng
    geometry = [
        Point(row["Lng"], row["Lat"])
        if pd.notna(row["Lat"]) and pd.notna(row["Lng"])
        else None
        for _, row in df.iterrows()
    ]
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")

    # Map to schema columns
    out = gpd.GeoDataFrame(
        {
            "unit_id": gdf["UnitId"],
            "province_name": gdf["ProvinceName"],
            "district_name": gdf["DistrictName"],
            "sub_district_name": gdf["SubDistrictName"],
            "unit_number": gdf["UnitNumber"],
            "unit_name": gdf["UnitName"],
            "lat": gdf["Lat"],
            "lng": gdf["Lng"],
            "formatted_address": gdf.get("Formatted_Address"),
            "place_id": gdf.get("PlaceId"),
            "tier_location": gdf.get("TierLocation"),
            "correction_source": gdf.get("CorrectionSource"),
        },
        geometry=gdf.geometry,
        crs="EPSG:4326",
    )
    out = out.rename_geometry("geom")

    out.to_postgis(
        "ect66_geocoded", ENGINE, schema="ref", if_exists="replace", index=False
    )
    print(f"  Loaded {len(out)} rows into ref.ect66_geocoded")


def load_ect66_raw_responses():
    print("Loading ECT66 raw responses...")
    batch_files = sorted(BATCH_DIR.glob("ect_batch_*.parquet"))
    if not batch_files:
        print("  No batch files found, skipping.")
        return

    dfs = []
    for f in batch_files:
        print(f"  Reading {f.name}...")
        df = pd.read_parquet(f)
        if "GMap" in df.columns and "UnitId" in df.columns:
            dfs.append(df[["UnitId", "GMap"]])

    if not dfs:
        print("  No GMap column found in batch files, skipping.")
        return

    combined = pd.concat(dfs, ignore_index=True)
    combined = combined.dropna(subset=["GMap"])
    combined = combined.drop_duplicates(subset=["UnitId"])

    # Convert GMap to JSON string for JSONB column
    def to_json(val):
        if isinstance(val, str):
            return val
        try:
            return json.dumps(val, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return None

    combined["raw_response"] = combined["GMap"].apply(to_json)
    combined = combined.dropna(subset=["raw_response"])

    # Use psycopg2 directly for JSONB insertion
    import psycopg2
    from psycopg2.extras import execute_values

    conn = psycopg2.connect(
        host="localhost",
        port=5433,
        dbname="postgres",
        user="postgres",
        password=PASSWORD,
    )
    conn.autocommit = False
    cur = conn.cursor()

    # Truncate and reload
    cur.execute("TRUNCATE ref.ect66_raw_responses")

    rows = [(int(r["UnitId"]), r["raw_response"]) for _, r in combined.iterrows()]
    execute_values(
        cur,
        "INSERT INTO ref.ect66_raw_responses (unit_id, raw_response) VALUES %s",
        rows,
        template="(%s, %s::jsonb)",
        page_size=1000,
    )
    conn.commit()
    cur.close()
    conn.close()
    print(f"  Loaded {len(rows)} raw responses into ref.ect66_raw_responses")


if __name__ == "__main__":
    with ENGINE.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("Connected to PostGIS")

    load_ect66_geocoded()
    load_ect66_raw_responses()
    print("Done.")
