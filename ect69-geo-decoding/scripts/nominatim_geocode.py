"""Geocode voting station locations using self-hosted Nominatim (OSM data).

Uses a local Nominatim instance (docker-compose.yml: mediagis/nominatim:4.5)
loaded with Thailand OSM data from Geofabrik.

Search strategies (tried in order):
1. Free-form query with just the location name
2. Location name + subdistrict name
3. Location name + district name

Results are filtered by checking the returned address components against
the expected province/district/subdistrict from the input data.

Nominatim address fields for Thai admin boundaries:
- state       -> จังหวัด (province)
- county      -> อำเภอ (district), includes "อำเภอ" prefix
- suburb/village -> ตำบล (subdistrict), may include "ตำบล" or use village name

Limitations:
- Structured search (amenity + state) often returns 0 results for Thai POIs
- Free-form search with too many terms also returns 0 (over-constraining)
- Generic locations (ศาลาประชาคม) are rarely in OSM data
- Village-level detail varies by OSM contributor coverage

Usage:
    uv run python ect69-geo-decoding/scripts/nominatim_geocode.py <input.parquet> [output.parquet] [batch_size]
"""

import httpx
import pandas as pd
from pathlib import Path

NOMINATIM_URL = "http://localhost:8080/search"

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


def address_matches(
    display_name: str,
    address: dict,
    province: str,
    district: str,
    sub_district: str,
) -> bool:
    """Check if Nominatim result matches expected province/district/subdistrict.

    Nominatim returns address components with Thai admin prefixes (อำเภอ, จังหวัด).
    We check both the structured address fields and the display_name string.
    """
    # Check display_name as fallback (contains full Thai address)
    display = display_name or ""

    # Province check: address.state or in display_name
    state = address.get("state", "")
    prov_match = province in state or province in display

    # District check: address.county or in display_name
    county = address.get("county", "")
    dist_match = district in county or district in display

    # Subdistrict check: address.suburb, village, or in display_name
    suburb = address.get("suburb", "")
    village = address.get("village", "")
    sub_match = (
        sub_district in suburb or sub_district in village or sub_district in display
    )

    return prov_match and dist_match and sub_match


def _search_nominatim(
    query: str,
    province: str,
    district: str,
    sub_district: str,
    client: httpx.Client,
) -> dict | None:
    """Single Nominatim free-form search with address matching."""
    params = {
        "q": query,
        "format": "json",
        "limit": 10,
        "addressdetails": 1,
        "countrycodes": "th",
    }
    try:
        resp = client.get(NOMINATIM_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "error" in data:
            print(f"    API error for '{query}': {data['error']}")
            return None
    except Exception as e:
        print(f"    API error for '{query}': {e}")
        return None

    for item in data:
        display_name = item.get("display_name", "")
        address = item.get("address", {})
        if address_matches(display_name, address, province, district, sub_district):
            return {
                "name": item.get("name") or item.get("display_name", "")[:50],
                "lat": float(item["lat"]),
                "lon": float(item["lon"]),
                "display_name": display_name,
                "osm_type": item.get("osm_type"),
                "osm_id": item.get("osm_id"),
                "class": item.get("class"),
                "type": item.get("type"),
            }
    return None


def search_nominatim(
    location_raw: str,
    location_cleaned: str,
    province: str,
    district: str,
    sub_district: str,
    client: httpx.Client,
) -> dict | None:
    """Search Nominatim with multiple strategies, return first match."""
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

    for query in unique_strategies:
        print(f"    trying: '{query}'")
        result = _search_nominatim(query, province, district, sub_district, client)
        if result:
            return result
    return None


def geocode_parquet(
    input_path: str, output_path: str | None = None, batch_size: int = 300
):
    """Geocode locations from a parquet file using local Nominatim."""
    df = pd.read_parquet(input_path)
    print(f"Loaded {len(df)} rows from {input_path}")

    # Add result columns if not present
    for col in [
        "nominatim_lat",
        "nominatim_lon",
        "nominatim_latlng",
        "nominatim_display_name",
        "nominatim_osm_type",
        "nominatim_osm_id",
    ]:
        if col not in df.columns:
            df[col] = None

    processed = 0
    with httpx.Client() as client:
        for idx, row in df.iterrows():
            if pd.notna(df.at[idx, "nominatim_latlng"]):
                continue

            province = clean_province(row["จังหวัด"])
            district = row["อำเภอ"]
            sub_district = row["ตำบล"]
            location_raw = row["สถานที่เลือกตั้ง"]
            location_name = clean_location_name(location_raw)

            print(
                f"[{idx}] Searching: '{location_raw}' -> cleaned: '{location_name}' in {province}/{district}/{sub_district}"
            )

            result = search_nominatim(
                location_raw, location_name, province, district, sub_district, client
            )

            if result:
                df.at[idx, "nominatim_lat"] = result["lat"]
                df.at[idx, "nominatim_lon"] = result["lon"]
                df.at[idx, "nominatim_latlng"] = f"{result['lat']},{result['lon']}"
                df.at[idx, "nominatim_display_name"] = result["display_name"]
                df.at[idx, "nominatim_osm_type"] = result["osm_type"]
                df.at[idx, "nominatim_osm_id"] = result["osm_id"]
                print(
                    f"  -> Found: {result['lat']},{result['lon']} | {result['display_name'][:80]}"
                )
            else:
                df.at[idx, "nominatim_latlng"] = "FAILED"
                print("  -> FAILED")

            processed += 1
            if processed >= batch_size:
                print(f"Batch limit ({batch_size}) reached at row {idx}")
                break

    if output_path is None:
        output_path = str(Path(input_path).with_suffix("")) + "_nominatim.parquet"

    df.to_parquet(output_path, index=False)
    print(f"\nSaved to {output_path}")

    # Summary
    total = len(df)
    found = df["nominatim_latlng"].notna() & (df["nominatim_latlng"] != "FAILED")
    failed = df["nominatim_latlng"] == "FAILED"
    pending = df["nominatim_latlng"].isna()
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
