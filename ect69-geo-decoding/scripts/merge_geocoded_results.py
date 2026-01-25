"""
Merge geocoded results back to source CSV files.

This script joins the validated geocoding results back to the original
source files, adding Latitude, Longitude, PlaceId, FormattedAddress,
and TierLocation columns.

Requirements:
  - intermediate/early_voting_validated.parquet exists

Output:
  - outputs/vote69_early_voting_ประชามตินอกเขต_geo_decoded.csv
  - outputs/vote69_early_voting_เลือกตั้งล่วงหน้า_geo_decoded.csv

Usage:
    uv run python ect69-geo-decoding/scripts/merge_geocoded_results.py
"""

import os
from pathlib import Path

import pandas as pd

# Change to script directory for relative paths
SCRIPT_DIR = Path(__file__).parent.parent
os.chdir(SCRIPT_DIR)


def main():
    """Main function to merge geocoded results."""

    # Create outputs directory
    Path("outputs").mkdir(exist_ok=True)

    # Load validated results
    validated_path = Path("intermediate/early_voting_validated.parquet")
    if not validated_path.exists():
        print(f"ERROR: {validated_path} not found")
        print("Please run the spatial validation notebook first.")
        return

    print(f"Loading validated results from {validated_path}...")
    validated = pd.read_parquet(validated_path)
    print(f"Loaded {len(validated):,} validated locations")

    # Create lookup for geocoded data
    geo_cols = [
        "original",
        "Lat",
        "Lng",
        "PlaceId",
        "FormattedAddress",
        "geocoded",
        "within_boundary",
    ]
    geo_lookup = validated[geo_cols].copy()
    geo_lookup.columns = [
        "สถานที่เลือกตั้งกลาง",
        "Latitude",
        "Longitude",
        "PlaceId",
        "FormattedAddress",
        "geocoded",
        "within_boundary",
    ]

    # Process each source file
    source_files = [
        (
            "inputs/vote69_early_voting_เลือกตั้งล่วงหน้า.csv",
            "outputs/vote69_early_voting_เลือกตั้งล่วงหน้า_geo_decoded.csv",
        ),
        (
            "inputs/vote69_early_voting_ประชามตินอกเขต.csv",
            "outputs/vote69_early_voting_ประชามตินอกเขต_geo_decoded.csv",
        ),
    ]

    for input_path, output_path in source_files:
        input_path = Path(input_path)
        output_path = Path(output_path)

        if not input_path.exists():
            print(f"WARNING: {input_path} not found, skipping")
            continue

        print(f"\nProcessing {input_path.name}...")
        source_df = pd.read_csv(input_path)
        print(f"  Source rows: {len(source_df):,}")

        # Drop existing geo columns that would conflict
        conflict_cols = [
            "Latitude",
            "Longtitude",
            "Longitude",
            "PlaceId",
            "FormattedAddress",
            "geocoded",
            "within_boundary",
        ]
        source_df = source_df.drop(
            columns=[c for c in conflict_cols if c in source_df.columns]
        )

        # Merge with geocoded data
        merged = source_df.merge(
            geo_lookup,
            on="สถานที่เลือกตั้งกลาง",
            how="left",
        )

        # Report merge results
        matched = merged["Latitude"].notna().sum()
        print(f"  Matched: {matched:,}/{len(merged):,}")

        # Show flag distribution
        if "geocoded" in merged.columns:
            geocoded_count = merged["geocoded"].sum()
            within_count = merged["within_boundary"].sum()
            print(f"  geocoded=True: {geocoded_count}")
            print(f"  within_boundary=True: {within_count}")

        # Save output
        merged.to_csv(output_path, index=False)
        print(f"  Saved to {output_path}")

    print("\nDone!")


if __name__ == "__main__":
    main()
