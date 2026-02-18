"""Geocode voting station locations using GISTDA Sphere API.

Recreated from the Google Apps Script version. Uses the GISTDA Sphere search
endpoint (https://api.sphere.gistda.or.th/services/search/search) to look up
Thai POIs by name, then filters results by matching province/district/subdistrict
in the returned address.

Hit rate: ~14% on sample data. Works well for named POIs (temples, schools) but
fails for generic location types (ศาลาประชาคม, ศาลาอเนกประสงค์) that are not
indexed as distinct POIs in GISTDA.

Limitations:
- API has no province/district filter param (tested, ignored by server)
- Maximum 20 results per query, ranked by text relevance
- Generic community buildings rarely appear in POI database
- Address format varies: sometimes codes, sometimes abbreviated (ต./อ./จ.)

Usage:
    uv run python ect69-geo-decoding/scripts/gistda_geocode.py <input.parquet> [output.parquet] [batch_size]
"""

import httpx
import pandas as pd
from pathlib import Path

GISTDA_API_KEY = "E96744B749134F46AAA3FDF85BE3415B"
GISTDA_SEARCH_URL = "https://api.sphere.gistda.or.th/services/search/search"

PREFIXES_TO_REMOVE = [
    "เต็นท์",
    "โดม",
    "ปะรำ",
    "โบสถ์",
    "ภาย",
    "นอก",
    "ใน",
    "บริเวณ",
    "ที่ว่าง",
    "ใน",
    "ด้าน",
    "หน้า",
    "หลัง",
    "ท้าย",
    "อาคาร",
    "ลานจอดรถ",
    "ณ",
]


def remove_prefixes(s: str, prefixes: list[str]) -> str:
    """Remove leading prefixes repeatedly until none match."""
    changed = True
    while changed:
        changed = False
        s = s.strip()
        for prefix in prefixes:
            if s.startswith(prefix):
                s = s[len(prefix) :]
                changed = True
    return s


def clean_location_name(raw: str) -> str:
    """Clean location name: remove prefixes, take first word."""
    cleaned = remove_prefixes(raw.strip(), PREFIXES_TO_REMOVE)
    return cleaned.strip().split(" ")[0].split("\u3000")[0]


def clean_province(province: str) -> str:
    """Remove 'จังหวัด' prefix."""
    return province.replace("จังหวัด", "").strip()


def address_contains(address: str, name: str) -> bool:
    """Check if an address contains a name, handling Thai abbreviated prefixes.

    GISTDA addresses use abbreviations like ต., อ., จ., แขวง, เขต
    while our data uses full names without prefixes.
    """
    if name in address:
        return True
    # Check with common prefixes that GISTDA uses
    prefixes = ["ต.", "อ.", "จ.", "แขวง", "เขต", "ตำบล", "อำเภอ", "จังหวัด"]
    for prefix in prefixes:
        if f"{prefix}{name}" in address:
            return True
    return False


def _search_and_match(
    keyword: str,
    province: str,
    district: str,
    sub_district: str,
    client: httpx.Client,
) -> dict | None:
    """Single GISTDA search call with address matching."""
    params = {
        "keyword": keyword,
        "limit": 20,
        "key": GISTDA_API_KEY,
    }
    try:
        resp = client.get(GISTDA_SEARCH_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json().get("data", [])
    except Exception as e:
        print(f"    API error for '{keyword}': {e}")
        return None

    for item in data:
        address = item.get("address", "")
        if (
            address_contains(address, province)
            and address_contains(address, district)
            and address_contains(address, sub_district)
        ):
            return {
                "name": item.get("name"),
                "lat": item.get("lat"),
                "lon": item.get("lon"),
                "address": address,
            }
    return None


def search_gistda(
    location_raw: str,
    location_cleaned: str,
    province: str,
    district: str,
    sub_district: str,
    client: httpx.Client,
) -> dict | None:
    """Search GISTDA with multiple strategies, return first match."""
    # Strategy 1: Full raw location name (without ณ prefix only)
    raw_trimmed = location_raw.strip().lstrip("ณ").strip()
    strategies = [
        raw_trimmed,
        location_cleaned,
        f"{location_cleaned} {sub_district}",
        f"{location_cleaned} {district}",
    ]
    # Deduplicate while preserving order
    seen = set()
    unique_strategies = []
    for s in strategies:
        if s not in seen:
            seen.add(s)
            unique_strategies.append(s)

    for keyword in unique_strategies:
        print(f"    trying: '{keyword}'")
        result = _search_and_match(keyword, province, district, sub_district, client)
        if result:
            return result
    return None


def geocode_parquet(
    input_path: str, output_path: str | None = None, batch_size: int = 300
):
    """Geocode locations from a parquet file using GISTDA Sphere API."""
    df = pd.read_parquet(input_path)
    print(f"Loaded {len(df)} rows from {input_path}")

    # Add result columns if not present
    for col in ["gistda_lat", "gistda_lon", "gistda_latlng", "gistda_address"]:
        if col not in df.columns:
            df[col] = None

    processed = 0
    with httpx.Client() as client:
        for idx, row in df.iterrows():
            if pd.notna(df.at[idx, "gistda_latlng"]):
                continue

            province = clean_province(row["จังหวัด"])
            district = row["อำเภอ"]
            sub_district = row["ตำบล"]
            location_raw = row["สถานที่เลือกตั้ง"]
            location_name = clean_location_name(location_raw)

            print(
                f"[{idx}] Searching: '{location_raw}' -> cleaned: '{location_name}' in {province}/{district}/{sub_district}"
            )

            result = search_gistda(
                location_raw, location_name, province, district, sub_district, client
            )

            if result:
                df.at[idx, "gistda_lat"] = result["lat"]
                df.at[idx, "gistda_lon"] = result["lon"]
                df.at[idx, "gistda_latlng"] = f"{result['lat']},{result['lon']}"
                df.at[idx, "gistda_address"] = result["address"]
                print(
                    f"  -> Found: {result['lat']},{result['lon']} | {result['address']}"
                )
            else:
                df.at[idx, "gistda_latlng"] = "FAILED"
                print("  -> FAILED")

            processed += 1
            if processed >= batch_size:
                print(f"Batch limit ({batch_size}) reached at row {idx}")
                break

    if output_path is None:
        output_path = str(Path(input_path).with_suffix("")) + "_gistda.parquet"

    df.to_parquet(output_path, index=False)
    print(f"\nSaved to {output_path}")

    # Summary
    total = len(df)
    found = df["gistda_latlng"].notna() & (df["gistda_latlng"] != "FAILED")
    failed = df["gistda_latlng"] == "FAILED"
    pending = df["gistda_latlng"].isna()
    print(
        f"Found: {found.sum()}/{total}, Failed: {failed.sum()}/{total}, Pending: {pending.sum()}/{total}"
    )


if __name__ == "__main__":
    import sys

    input_file = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "ect69-geo-decoding/outputs/sample_300_locations.parquet"
    )
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    batch = int(sys.argv[3]) if len(sys.argv) > 3 else 300

    geocode_parquet(input_file, output_file, batch_size=batch)
