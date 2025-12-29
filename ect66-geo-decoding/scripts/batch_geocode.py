"""
Batch geocode ECT voting units using Google Maps API.

This script processes ECT voting station data in 3 batches to manage API quotas
and avoid rate limiting. Each batch geocodes Thai addresses using Google Maps
Geocoding API with component filtering.

Batches:
  - Batch 1: First 1,000 units (for testing)
  - Batch 2: Units 1,000-10,000 (medium volume)
  - Batch 3: Units 10,000+ (remaining ~85,249 units)

Features:
  - Joblib caching to avoid redundant API calls
  - Component filtering (province, tambon) for better Thai address accuracy
  - Manual confirmation between batches to monitor progress
  - Saves to Parquet format only

Requirements:
  - GMAP_API_KEY environment variable set in .env file
  - intermediate/ect_cleaned.parquet exists

Output:
  - intermediate/ect_batch_1.parquet
  - intermediate/ect_batch_2.parquet
  - intermediate/ect_batch_3.parquet

Usage:
    # Run each batch sequentially (manual confirmation between batches)
    uv run python scripts/batch_geocode.py --batch 1
    # Press Enter to confirm...
    uv run python scripts/batch_geocode.py --batch 2
    # Press Enter to confirm...
    uv run python scripts/batch_geocode.py --batch 3
"""

import pandas as pd
import os
import googlemaps
from tqdm import tqdm
from dotenv import load_dotenv
import joblib
import argparse
import sys
from pathlib import Path

# Load environment variables
load_dotenv()
tqdm.pandas(desc="Geocoding")

# Configure API - will be initialized in main()
apikey = None
gmaps = None

# Configure cache
CACHE_DIR = Path(".cache")
CACHE_DIR.mkdir(exist_ok=True)
cache = joblib.Memory(CACHE_DIR, verbose=0)


@cache.cache
def geocode(street_address, subdistrict, district=None, province=None, country="TH"):
    """
    Geocode Thai address with component filtering.

    Args:
        street_address: Unit name/location (e.g., "โรงเรียนวัดมหาธาตุ ถนนพระจันทร์")
        subdistrict: Tambon/sub-district name
        district: Optional amphoe/district name
        province: Optional province name
        country: Country code (default: "TH" for Thailand)

    Returns:
        List of geocoding results from Google Maps API (may be empty)
    """
    components = {"sublocality_level_2": subdistrict, "country": country}

    if district is not None:
        components["sublocality_level_1"] = district
    if province is not None:
        components["administrative_area_level_1"] = province

    return gmaps.geocode(street_address, language="th", components=components)


def run_batch(df, batch_num, start_idx, end_idx=None):
    """
    Run geocoding for a specific batch.

    Args:
        df: DataFrame with ECT data
        batch_num: Batch number (1, 2, or 3)
        start_idx: Starting row index
        end_idx: Ending row index (None = to end)

    Returns:
        DataFrame with geocoding results
    """
    if end_idx is None:
        batch_df = df.iloc[start_idx:]
        batch_size = len(df) - start_idx
    else:
        batch_df = df.iloc[start_idx:end_idx]
        batch_size = end_idx - start_idx

    print(f"\n{'=' * 60}")
    print(
        f"Batch {batch_num}: Geocoding {batch_size:,} units (rows {start_idx:,} to {end_idx if end_idx else len(df):,})"
    )
    print(f"{'=' * 60}\n")

    # Apply geocoding
    df.loc[df.index[start_idx:end_idx], "GMap"] = batch_df.progress_apply(
        lambda x: geocode(
            street_address=x["UnitName"],
            subdistrict=x["SubDistrictName"],
            province=x["ProvinceName"],
        ),
        axis=1,
    )

    # Save to parquet
    output_path = f"intermediate/ect_batch_{batch_num}.parquet"
    df.to_parquet(output_path)
    print(f"\nSaved batch {batch_num} to {output_path}")

    return df


def main():
    """Main function to orchestrate batch geocoding."""
    global apikey, gmaps

    # Initialize API client
    apikey = os.getenv("GMAP_API_KEY")
    if not apikey:
        print("ERROR: GMAP_API_KEY not found in environment variables")
        print("Please set it in your .env file")
        sys.exit(1)

    gmaps = googlemaps.Client(key=apikey)

    parser = argparse.ArgumentParser(
        description="Batch geocode ECT voting units with Google Maps API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run batch 1 (first 1,000 units)
  uv run python scripts/batch_geocode.py --batch 1

  # Run batch 2 (units 1,000-10,000)
  uv run python scripts/batch_geocode.py --batch 2

  # Run batch 3 (remaining units)
  uv run python scripts/batch_geocode.py --batch 3

Note: Run batches sequentially and confirm between each batch.
      """,
    )
    parser.add_argument(
        "--batch",
        type=int,
        choices=[1, 2, 3],
        required=True,
        help="Which batch to run (1, 2, or 3)",
    )
    args = parser.parse_args()

    # Check input file exists
    input_path = Path("intermediate/ect_cleaned.parquet")
    if not input_path.exists():
        print(f"ERROR: {input_path} not found")
        print("Please run 01_transform_raw_ect.ipynb first")
        sys.exit(1)

    # Load data
    print(f"Loading data from {input_path}...")
    df = pd.read_parquet(input_path)
    print(f"Loaded {len(df):,} voting units")

    # Initialize GMap column if needed
    if "GMap" not in df.columns:
        df["GMap"] = None

    # Run the requested batch
    if args.batch == 1:
        df = run_batch(df, batch_num=1, start_idx=0, end_idx=1000)
        print("\n⚠️  Batch 1 complete. Press Enter to continue to Batch 2...")
        input()

    elif args.batch == 2:
        df = run_batch(df, batch_num=2, start_idx=1000, end_idx=10000)
        print("\n⚠️  Batch 2 complete. Press Enter to continue to Batch 3...")
        input()

    elif args.batch == 3:
        df = run_batch(df, batch_num=3, start_idx=10000, end_idx=None)
        print("\n✅ All batches complete!")

    print(f"\nGeocoding cache location: {CACHE_DIR.absolute()}")
    print("Cache will speed up re-runs for the same addresses")


if __name__ == "__main__":
    main()
