"""
Geocode early voting locations using Google Maps API.

This script processes early voting location data for Thailand's 2569 election,
geocoding addresses using the Google Maps Geocoding API with component filtering.

Features:
  - Joblib caching to avoid redundant API calls
  - Component filtering (subdistrict, district) for better Thai address accuracy
  - Progress bar with tqdm

Requirements:
  - GMAP_API_KEY environment variable set in .env file
  - inputs/vote69_early_voting_entities.csv exists

Output:
  - intermediate/early_voting_geocoded_raw.parquet

Usage:
    uv run python ect69-geo-decoding/scripts/geocode_early_voting.py
"""

import os
import sys
from pathlib import Path

import googlemaps
import joblib
import pandas as pd
from dotenv import load_dotenv
from tqdm import tqdm

# Change to script directory for relative paths
SCRIPT_DIR = Path(__file__).parent.parent
os.chdir(SCRIPT_DIR)

# Load environment variables
load_dotenv()
tqdm.pandas(desc="Geocoding")

# Configure cache
CACHE_DIR = Path(".cache")
CACHE_DIR.mkdir(exist_ok=True)
cache = joblib.Memory(CACHE_DIR, verbose=0)

# Configure API - will be initialized in main()
gmaps = None


@cache.cache
def geocode(
    street_address: str,
    subdistrict: str | None = None,
    district: str | None = None,
    country: str = "TH",
) -> list:
    """
    Geocode Thai address with component filtering.

    Args:
        street_address: Location name/query (e.g., "สำนักงานเขตพระนคร")
        subdistrict: Tambon/sub-district name (แขวง)
        district: Amphoe/district name (เขต)
        country: Country code (default: "TH" for Thailand)

    Returns:
        List of geocoding results from Google Maps API (may be empty)
    """
    components = {"country": country}

    if subdistrict:
        components["sublocality_level_2"] = subdistrict
    if district:
        components["sublocality_level_1"] = district

    return gmaps.geocode(street_address, language="th", components=components)


def main():
    """Main function to geocode early voting locations."""
    global gmaps

    # Initialize API client
    apikey = os.getenv("GMAP_API_KEY")
    if not apikey:
        print("ERROR: GMAP_API_KEY not found in environment variables")
        print("Please set it in your .env file")
        sys.exit(1)

    gmaps = googlemaps.Client(key=apikey)

    # Check input file exists
    input_path = Path("inputs/vote69_early_voting_entities.csv")
    if not input_path.exists():
        print(f"ERROR: {input_path} not found")
        sys.exit(1)

    # Create intermediate directory
    Path("intermediate").mkdir(exist_ok=True)

    # Load data
    print(f"Loading data from {input_path}...")
    df = pd.read_csv(input_path)
    print(f"Loaded {len(df):,} early voting locations")

    # Show sample
    print("\nSample data:")
    print(df[["location_name", "geocode_query", "subdistrict", "district"]].head())

    # Geocode
    print(f"\n{'=' * 60}")
    print(f"Geocoding {len(df):,} locations...")
    print(f"{'=' * 60}\n")

    df["GMap"] = df.progress_apply(
        lambda x: geocode(
            street_address=x["geocode_query"],
            subdistrict=x["subdistrict"] if pd.notna(x["subdistrict"]) else None,
            district=x["district"] if pd.notna(x["district"]) else None,
        ),
        axis=1,
    )

    # Count results
    df["GMapLen"] = df["GMap"].apply(len)
    print("\nGeocoding results summary:")
    print(df["GMapLen"].value_counts().sort_index())

    no_results = (df["GMapLen"] == 0).sum()
    print(f"\nLocations with no results: {no_results}")

    # Save to parquet
    output_path = Path("intermediate/early_voting_geocoded_raw.parquet")
    df.to_parquet(output_path)
    print(f"\nSaved to {output_path}")

    print(f"\nGeocoding cache location: {CACHE_DIR.absolute()}")
    print("Cache will speed up re-runs for the same addresses")


if __name__ == "__main__":
    main()
