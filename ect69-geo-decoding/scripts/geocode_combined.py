"""Geocode voting station locations using GISTDA + Nominatim (fallback chain).

Tries GISTDA Sphere API first (higher hit rate for Thai POIs at ~14%), then
falls back to self-hosted Nominatim/OSM (~5%). Combined hit rate ~17% on
sample data since the two services have mostly non-overlapping coverage.

Search order per row:
1. GISTDA Sphere API (keyword search with address matching)
2. Nominatim/OSM (free-form search with address component matching)

Each service tries multiple query strategies:
- geocode_query (pre-built with district/province context, from cleaned data)
- location_main (cleaned location name)
- Cleaned name (prefixes stripped, first word only)
- Cleaned name + subdistrict / district

Supports two input formats:
- Cleaned parquet (from clean_main_voting_units.py): deduplicates by location_id,
  uses geocode_query and location_main columns, joins results back to all rows.
- Sample/raw parquet: processes each row individually using สถานที่เลือกตั้ง column.

Usage:
    uv run python ect69-geo-decoding/scripts/geocode_combined.py <input.parquet> [output.parquet] [batch_size]
"""

import os
import time

import httpx
import pandas as pd
from pathlib import Path

REQUEST_DELAY = float(os.environ.get("REQUEST_DELAY", "0.3"))

# --- Config ---


def _read_secret(env_var: str, secret_path: str) -> str:
    """Read from env var, Docker secret file path env, or Docker secret file."""
    val = os.environ.get(env_var, "").strip()
    if val:
        return val
    file_env = os.environ.get(f"{env_var}_FILE", "").strip()
    if file_env and os.path.isfile(file_env):
        return Path(file_env).read_text().strip()
    if os.path.isfile(secret_path):
        return Path(secret_path).read_text().strip()
    return ""


GISTDA_API_KEY = _read_secret("GISTDA_API_KEY", "/run/secrets/gistda_api_key")
GISTDA_SEARCH_URL = "https://api.sphere.gistda.or.th/services/search/search"
NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "http://localhost:8080/search")

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

# --- Text cleaning ---


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


def build_strategies(
    location_raw: str,
    location_cleaned: str,
    sub_district: str,
    district: str,
    geocode_query: str | None = None,
    location_main: str | None = None,
) -> list[str]:
    """Build deduplicated list of search queries to try."""
    raw_trimmed = location_raw.strip().lstrip("ณ").strip()
    candidates = []
    # Best: pre-built geocode_query with full context
    if geocode_query:
        candidates.append(geocode_query.rstrip("#").strip())
    # Next: cleaned location_main from data cleaning pipeline
    if location_main:
        candidates.append(location_main.rstrip("#").strip())
    candidates.extend(
        [
            raw_trimmed.rstrip("#").strip(),
            location_cleaned,
            f"{location_cleaned} {sub_district}",
            f"{location_cleaned} {district}",
        ]
    )
    seen = set()
    unique = []
    for s in candidates:
        s = s.strip()
        if s and s not in seen:
            seen.add(s)
            unique.append(s)
    return unique


# --- GISTDA ---


def _gistda_address_contains(address: str, name: str) -> bool:
    """Check if GISTDA address contains a name, handling Thai abbreviated prefixes."""
    if name in address:
        return True
    for prefix in ["ต.", "อ.", "จ.", "แขวง", "เขต", "ตำบล", "อำเภอ", "จังหวัด"]:
        if f"{prefix}{name}" in address:
            return True
    return False


def _search_gistda_single(
    keyword: str,
    province: str,
    district: str,
    sub_district: str,
    client: httpx.Client,
) -> dict | None:
    """Single GISTDA search call with address matching and retry on failure."""
    params = {"keyword": keyword, "limit": 20, "key": GISTDA_API_KEY}
    data = []
    for attempt in range(3):
        try:
            time.sleep(REQUEST_DELAY)
            resp = client.get(GISTDA_SEARCH_URL, params=params, timeout=15)
            resp.raise_for_status()
            body = resp.json()
            if isinstance(body, dict):
                data = body.get("data", [])
            else:
                # API returns non-JSON (e.g. "throw 'Search Service API Key Error'")
                print("      gistda: unexpected response")
                return None
            break
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))  # 2s, 4s backoff
                continue
            print(f"      gistda error: {e}")
            return None

    for item in data:
        address = item.get("address", "")
        if (
            _gistda_address_contains(address, province)
            and _gistda_address_contains(address, district)
            and _gistda_address_contains(address, sub_district)
        ):
            return {
                "lat": item.get("lat"),
                "lon": item.get("lon"),
                "source": "gistda",
                "address": address,
                "name": item.get("name"),
            }
    return None


_gistda_consecutive_failures = 0
_gistda_disabled = False


def search_gistda(
    strategies: list[str],
    province: str,
    district: str,
    sub_district: str,
    client: httpx.Client,
) -> dict | None:
    """Try all strategies against GISTDA. Auto-disables after 10 consecutive failures."""
    global _gistda_consecutive_failures, _gistda_disabled
    if _gistda_disabled:
        return None
    for keyword in strategies:
        print(f"    [gistda] '{keyword}'")
        result = _search_gistda_single(
            keyword, province, district, sub_district, client
        )
        if result:
            _gistda_consecutive_failures = 0
            return result
    _gistda_consecutive_failures += 1
    if _gistda_consecutive_failures >= 10:
        _gistda_disabled = True
        print(
            "    [gistda] DISABLED - too many consecutive failures (API key may be blocked)"
        )
    return None


# --- Nominatim ---


def _nominatim_address_matches(
    display_name: str,
    address: dict,
    province: str,
    district: str,
    sub_district: str,
) -> bool:
    """Check if Nominatim result matches expected province/district/subdistrict."""
    display = display_name or ""
    state = address.get("state", "")
    county = address.get("county", "")
    suburb = address.get("suburb", "")
    village = address.get("village", "")

    prov_match = province in state or province in display
    dist_match = district in county or district in display
    sub_match = (
        sub_district in suburb or sub_district in village or sub_district in display
    )

    return prov_match and dist_match and sub_match


def _search_nominatim_single(
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
        time.sleep(REQUEST_DELAY)
        resp = client.get(NOMINATIM_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "error" in data:
            print(f"      nominatim error: {data['error']}")
            return None
    except Exception as e:
        print(f"      nominatim error: {e}")
        return None

    for item in data:
        display_name = item.get("display_name", "")
        address = item.get("address", {})
        if _nominatim_address_matches(
            display_name, address, province, district, sub_district
        ):
            return {
                "lat": float(item["lat"]),
                "lon": float(item["lon"]),
                "source": "nominatim",
                "address": display_name,
                "name": item.get("name") or display_name[:50],
            }
    return None


def search_nominatim(
    strategies: list[str],
    province: str,
    district: str,
    sub_district: str,
    client: httpx.Client,
) -> dict | None:
    """Try all strategies against Nominatim."""
    for query in strategies:
        print(f"    [nominatim] '{query}'")
        result = _search_nominatim_single(
            query, province, district, sub_district, client
        )
        if result:
            return result
    return None


# --- Main pipeline ---

GEO_COLS = ["geo_lat", "geo_lon", "geo_latlng", "geo_source", "geo_address"]


def _detect_format(df: pd.DataFrame) -> str:
    """Detect if this is the cleaned parquet or sample/raw format."""
    if "location_id" in df.columns and "geocode_query" in df.columns:
        return "cleaned"
    return "raw"


def _geocode_row(
    row: pd.Series,
    fmt: str,
    client: httpx.Client,
) -> dict | None:
    """Geocode a single row, return result dict or None."""
    province = clean_province(row["จังหวัด"])
    district = row["อำเภอ"]
    sub_district = row["ตำบล"]

    if fmt == "cleaned":
        location_raw = row["สถานที่เลือกตั้ง_raw"]
        geocode_query = row.get("geocode_query")
        location_main = row.get("location_main")
    else:
        location_raw = row["สถานที่เลือกตั้ง"]
        geocode_query = None
        location_main = None

    location_cleaned = clean_location_name(location_raw)

    strategies = build_strategies(
        location_raw,
        location_cleaned,
        sub_district,
        district,
        geocode_query=geocode_query,
        location_main=location_main,
    )

    result = search_gistda(strategies, province, district, sub_district, client)
    if not result:
        result = search_nominatim(strategies, province, district, sub_district, client)
    return result


def geocode_parquet(
    input_path: str, output_path: str | None = None, batch_size: int = 0
):
    """Geocode locations trying GISTDA first, then Nominatim as fallback.

    For cleaned data with location_id, deduplicates first (80k unique vs 100k rows),
    geocodes unique locations, then joins results back to all rows.

    Args:
        batch_size: Max unique locations to process. 0 = unlimited.
    """
    df = pd.read_parquet(input_path)
    fmt = _detect_format(df)
    print(f"Loaded {len(df)} rows from {input_path} (format: {fmt})")

    if fmt == "cleaned":
        # Deduplicate: geocode unique locations only
        dedup = df.drop_duplicates(subset=["location_id"]).copy()
        print(f"Deduplicated to {len(dedup)} unique locations")
    else:
        dedup = df.copy()

    for col in GEO_COLS:
        if col not in dedup.columns:
            dedup[col] = None

    # Load existing results if output exists (resume support)
    if output_path and Path(output_path).exists():
        existing = pd.read_parquet(output_path)
        if (
            "geo_latlng" in existing.columns
            and fmt == "cleaned"
            and "location_id" in existing.columns
        ):
            done = existing[existing["geo_latlng"].notna()][["location_id"] + GEO_COLS]
            done_ids = set(done["location_id"])
            for idx in dedup.index:
                lid = dedup.at[idx, "location_id"]
                if lid in done_ids:
                    match = done[done["location_id"] == lid].iloc[0]
                    for col in GEO_COLS:
                        dedup.at[idx, col] = match[col]
            already = dedup["geo_latlng"].notna().sum()
            print(f"Resumed {already} locations from existing output")

    processed = 0
    stats = {"gistda": 0, "nominatim": 0, "failed": 0}
    limit = batch_size if batch_size > 0 else len(dedup)

    with httpx.Client() as client:
        for idx, row in dedup.iterrows():
            if pd.notna(dedup.at[idx, "geo_latlng"]):
                continue

            province = clean_province(row["จังหวัด"])
            district = row["อำเภอ"]
            sub_district = row["ตำบล"]
            loc_display = row.get("location_main") or row.get("สถานที่เลือกตั้ง", "?")
            print(
                f"[{processed + 1}/{limit}] '{loc_display}' | {province}/{district}/{sub_district}"
            )

            result = _geocode_row(row, fmt, client)

            if result:
                dedup.at[idx, "geo_lat"] = result["lat"]
                dedup.at[idx, "geo_lon"] = result["lon"]
                dedup.at[idx, "geo_latlng"] = f"{result['lat']},{result['lon']}"
                dedup.at[idx, "geo_source"] = result["source"]
                dedup.at[idx, "geo_address"] = result["address"]
                stats[result["source"]] += 1
                print(
                    f"  -> [{result['source']}] {result['lat']},{result['lon']} | {result['address'][:80]}"
                )
            else:
                dedup.at[idx, "geo_latlng"] = "FAILED"
                stats["failed"] += 1
                print("  -> FAILED")

            processed += 1
            if processed >= limit:
                print(f"\nBatch limit ({limit}) reached")
                break

            # Periodic save every 500 rows
            if processed % 500 == 0:
                _save_results(dedup, df, fmt, output_path, input_path)
                print(f"  [checkpoint saved at {processed} processed]")

    out = _save_results(dedup, df, fmt, output_path, input_path)
    _print_summary(out, stats)
    return out


def _save_results(
    dedup: pd.DataFrame,
    df: pd.DataFrame,
    fmt: str,
    output_path: str | None,
    input_path: str,
) -> str:
    """Join geocode results back to full dataframe and save."""
    if fmt == "cleaned":
        # Join dedup results back to full df by location_id
        geo_results = dedup[dedup["geo_latlng"].notna()][
            ["location_id"] + GEO_COLS
        ].drop_duplicates("location_id")
        out_df = df.merge(geo_results, on="location_id", how="left")
    else:
        out_df = dedup

    if output_path is None:
        output_path = str(Path(input_path).with_suffix("")) + "_geocoded.parquet"

    out_df.to_parquet(output_path, index=False)
    print(f"\nSaved to {output_path} ({len(out_df)} rows)")
    return output_path


def _print_summary(output_path: str, stats: dict):
    """Print summary statistics."""
    df = pd.read_parquet(output_path)
    total = len(df)
    found = df["geo_latlng"].notna() & (df["geo_latlng"] != "FAILED")
    failed = df["geo_latlng"] == "FAILED"
    pending = df["geo_latlng"].isna()

    # Count unique locations
    if "location_id" in df.columns:
        unique_total = df["location_id"].nunique()
        unique_found = df[found]["location_id"].nunique() if found.any() else 0
        unique_failed = df[failed]["location_id"].nunique() if failed.any() else 0
        unique_pending = df[pending]["location_id"].nunique() if pending.any() else 0
        print("\n=== Summary (unique locations) ===")
        print(
            f"Found:   {unique_found}/{unique_total} ({unique_found / unique_total * 100:.1f}%)"
        )
        print(f"  GISTDA:    {stats['gistda']}")
        print(f"  Nominatim: {stats['nominatim']}")
        print(f"Failed:  {unique_failed}/{unique_total}")
        print(f"Pending: {unique_pending}/{unique_total}")
        print("\n=== Summary (all rows) ===")

    print(f"Found:   {found.sum()}/{total} ({found.sum() / total * 100:.1f}%)")
    print(f"Failed:  {failed.sum()}/{total}")
    print(f"Pending: {pending.sum()}/{total}")

    if "geo_source" in df.columns:
        print("\nBy source:")
        print(df["geo_source"].value_counts().to_string())


if __name__ == "__main__":
    import sys

    input_file = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "ect69-geo-decoding/outputs/sample_300_locations.parquet"
    )
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    batch = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    geocode_parquet(input_file, output_file, batch_size=batch)
