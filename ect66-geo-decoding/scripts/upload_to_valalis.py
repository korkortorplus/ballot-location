"""
Upload geocoded voting units to Valalis API.

This script reads the final validated voting station data and uploads it
to the Valalis i-bitz.world election monitoring platform as GeoJSON features.

The upload process:
1. Delete all existing units from the collection (fresh start)
2. Read final parquet file with Tier A+/D quality ratings
3. Upload in batches (default: 200 units/batch) with async concurrency
4. Save API response mapping to outputs/

Usage:
    uv run python scripts/upload_to_valalis.py --batch-size 200
    uv run python scripts/upload_to_valalis.py --batch-size 100  # Smaller batches

Requirements:
    - VA_DB_API_KEY environment variable set in .env file
    - outputs/ect66_geocoded_validated.parquet exists

Output:
    - outputs/valalis_upload_response.parquet (API response mapping)
"""

import asyncio
import argparse
import os
import sys
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from tqdm import tqdm

# Add parent directory to path to import lib modules
sys.path.append(str(Path(__file__).parent.parent))
from lib.valalis_client import VA_Elect_API
from lib.models import UnitData, create_google_url


async def main(batch_size: int):
    """
    Upload voting units to Valalis API in batches.

    Args:
        batch_size: Number of units to upload per API request (default: 200)
    """
    # Load environment variables
    load_dotenv()
    api_key = os.getenv("VA_DB_API_KEY")

    if not api_key:
        print("ERROR: VA_DB_API_KEY not found in environment variables")
        print("Please set it in your .env file")
        sys.exit(1)

    # Read final validated data
    data_path = Path("outputs/ect66_geocoded_validated.parquet")
    if not data_path.exists():
        print(f"ERROR: {data_path} not found")
        print("Please run the geocoding and validation pipeline first")
        sys.exit(1)

    print(f"Loading data from {data_path}...")
    df = pd.read_parquet(data_path)
    print(f"Loaded {len(df):,} voting units")

    # Initialize API client
    api_client = VA_Elect_API(api_key)

    # Delete all existing units (fresh start)
    print("Deleting all existing units from Valalis...")
    await api_client.delete_all()
    print("Deletion complete")

    # Prepare for batch upload
    units = []
    count = 0
    tasks = []
    semaphore = asyncio.Semaphore(4)  # Limit concurrent requests

    async def create_units(units_batch):
        """Upload a batch of units with semaphore control."""
        async with semaphore:
            return await api_client.create(units_batch)

    # Process each unit
    print(f"Uploading {len(df):,} units in batches of {batch_size}...")
    for i, row in tqdm(df.iterrows(), total=df.shape[0], desc="Processing units"):
        r = row.to_dict()

        # Create UnitData instance
        u = UnitData(
            unit_id=r["UnitId"],
            unit_name=r["UnitName"],
            province_name=r["ProvinceName"],
            division_number=r["DivisionNumber"],
            district_name=r["DistrictName"],
            sub_district_name=r["SubDistrictName"],
            unit_number=r["UnitNumber"],
            latitude=r["Lat"],
            longitude=r["Lng"],
            google_map_url=create_google_url(
                (r["Lat"], r["Lng"]), placeId=r.get("PlaceId", "")
            ),
            tier_location=r["TierLocation"],
        )
        units.append(u)

        # If batch is full, upload it
        if len(units) == batch_size:
            count += len(units)
            tasks.append(create_units(units))
            units = []

    # Upload any remaining units
    if units:
        count += len(units)
        tasks.append(create_units(units))

    # Wait for all uploads to complete
    print(f"Uploading {count:,} total units across {len(tasks)} batches...")
    result = await asyncio.gather(*tasks)
    print("Upload complete!")

    # Save API response mapping
    print("Saving API response mapping...")
    output_path = Path("outputs/valalis_upload_response.parquet")

    # Parse result (list of API responses)
    response_data = []
    for batch_result in result:
        if "features" in batch_result:
            for feature in batch_result["features"]:
                response_data.append(
                    {
                        "object_id": feature["properties"].get("_id", ""),
                        "unit_id": feature["properties"].get("unit_id", ""),
                        "province_name": feature["properties"].get("province_name", ""),
                    }
                )

    if response_data:
        response_df = pd.DataFrame(response_data)
        response_df.to_parquet(output_path)
        print(f"Saved {len(response_df):,} response records to {output_path}")
    else:
        print("WARNING: No response data to save")

    print("\nUpload summary:")
    print(f"  Total units uploaded: {count:,}")
    print(f"  Batch size: {batch_size}")
    print(f"  Number of batches: {len(tasks)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Upload voting units to Valalis API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python scripts/upload_to_valalis.py --batch-size 200
  uv run python scripts/upload_to_valalis.py --batch-size 100
        """,
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Number of units to upload per API request (default: 200)",
    )
    args = parser.parse_args()

    # Run async main function
    asyncio.run(main(batch_size=args.batch_size))
