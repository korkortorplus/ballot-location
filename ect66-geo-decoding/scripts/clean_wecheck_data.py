#!/usr/bin/env python3
"""
Clean WeCheck voting station corrections CSV.

This script removes PII (phone numbers) from the WeCheck correction data
and renames the file from Thai to English for better compatibility.

Usage:
    uv run python scripts/clean_wecheck_data.py
"""

import pandas as pd
from pathlib import Path
import sys


def clean_wecheck_csv():
    """
    Remove PII column and rename WeCheck CSV file.

    Returns:
        pd.DataFrame: Cleaned DataFrame
    """
    input_path = Path("inputs/WeCheck รายงานหน่วยเลือกตั้งที่ไม่ถูก.csv")
    output_path = Path("inputs/wecheck_corrections.csv")

    print("=" * 80)
    print("WeCheck Data Cleaning".center(80))
    print("=" * 80)
    print()

    # Check if input exists
    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}")
        print()
        print("Please ensure the WeCheck CSV file exists in the inputs/ directory")
        sys.exit(1)

    # Read CSV
    print(f"Reading: {input_path}")
    df = pd.read_csv(input_path)
    print(f"  Rows: {len(df):,}")
    print(f"  Columns: {len(df.columns)}")
    print()

    # Check for PII column
    pii_column = "เบอร์โทรติดต่อกลับ"
    if pii_column in df.columns:
        print(f"Removing PII column: {pii_column}")
        df = df.drop(columns=[pii_column])
        print("  ✓ PII column removed")
    else:
        print(f"  No PII column found ('{pii_column}' not in columns)")
    print()

    # Save with English filename
    print(f"Saving to: {output_path}")
    df.to_csv(output_path, index=False)
    print("  ✓ Saved successfully")
    print(f"  Final rows: {len(df):,}")
    print(f"  Final columns: {len(df.columns)}")
    print()

    # Summary statistics
    print("Data Summary:")
    print("-" * 80)

    # Count corrections by type
    if "Edited" in df.columns:
        edited_count = (
            df["Edited"].sum()
            if df["Edited"].dtype == bool
            else (df["Edited"]).sum()
        )
        print(f"  Validated corrections (Edited=TRUE): {edited_count}")

    if "UnitId" in df.columns:
        unit_id_count = df["UnitId"].notna().sum()
        print(f"  Corrections with UnitId: {unit_id_count}")

    if "ชื่อหน่วยเลือกตั้งที่ถูกต้อง" in df.columns:
        name_count = df["ชื่อหน่วยเลือกตั้งที่ถูกต้อง"].notna().sum()
        print(f"  Corrections with updated names: {name_count}")

    if "Latitude" in df.columns and "Longitude" in df.columns:
        coord_count = (df["Latitude"].notna() & df["Longitude"].notna()).sum()
        print(f"  Corrections with coordinates: {coord_count}")

    print()
    print("=" * 80)
    print("✓ Cleaning complete!")
    print("=" * 80)

    return df


if __name__ == "__main__":
    clean_wecheck_csv()
