#!/usr/bin/env python
"""Export ECT66↔ECT69 matching results to Excel for geocoding teams.

Produces an Excel workbook with:
- Sheet 1: All ECT69 locations with best ECT66 match, similarity, coords, match tier
- Sheet 2: Summary stats per province
- Sheet 3: No-match locations (need fresh geocoding)

Output: ect69-geo-decoding/outputs/ect69_matching_for_geocoding.xlsx
"""

from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent.parent
OUTPUT_PATH = BASE_DIR / "outputs" / "ect69_matching_for_geocoding.xlsx"


def trigram_similarity(s1: str, s2: str) -> float:
    """Jaccard similarity of character trigrams."""
    if not s1 or not s2:
        return 0.0
    t1 = {s1[i : i + 3] for i in range(len(s1) - 2)}
    t2 = {s2[i : i + 3] for i in range(len(s2) - 2)}
    if not t1 or not t2:
        return 0.0
    return len(t1 & t2) / len(t1 | t2)


# --- Load ---
print("Loading datasets...")
ect66 = pd.read_parquet(
    BASE_DIR
    / ".."
    / "ect66-geo-decoding"
    / "outputs"
    / "ect66_geocoded_validated.parquet"
)
ect69 = pd.read_parquet(
    BASE_DIR / "intermediate" / "ect69_voting_units_cleaned.parquet"
)

# --- Normalize ECT66 location names (strip "11 - " prefix) ---
ect66["_loc_name"] = (
    ect66["DisplayUnitName"].str.replace(r"^\d+\s*-\s*", "", regex=True).str.strip()
)
ect66["_key_prov_tambon"] = (
    ect66["ProvinceName"].str.strip() + "|" + ect66["SubDistrictName"].str.strip()
)

# Build ECT66 lookup: tambon → list of {name, lat, lng, tier, address, place_id}
print("Building ECT66 lookup index...")
ect66_lookup: dict[str, list[dict]] = {}
for _, row in ect66.iterrows():
    key = row["_key_prov_tambon"]
    if key not in ect66_lookup:
        ect66_lookup[key] = []
    ect66_lookup[key].append(
        {
            "name": row["_loc_name"],
            "lat": row["Lat"],
            "lng": row["Lng"],
            "tier": row["TierLocation"],
            "address": row["Formatted_Address"],
            "place_id": row["PlaceId"],
        }
    )

# --- Prepare ECT69 unique locations ---
print("Preparing ECT69 unique locations...")
ect69["_loc_name"] = ect69["location_main"].str.strip()
ect69["_key_prov_tambon"] = (
    ect69.iloc[:, 0].str.strip() + "|" + ect69.iloc[:, 4].str.strip()
)

# Deduplicate at (tambon, location) level using drop_duplicates + merge back unit info
ect69_first = ect69.drop_duplicates(
    subset=["_key_prov_tambon", "_loc_name"], keep="first"
).copy()

# Aggregate unit numbers per location
unit_agg = (
    ect69.groupby(["_key_prov_tambon", "_loc_name"])
    .agg(
        unit_count=(ect69.columns[5], "size"),
        unit_numbers=(ect69.columns[5], lambda x: ", ".join(str(v) for v in sorted(x))),
    )
    .reset_index()
)

ect69_unique = ect69_first.merge(
    unit_agg, on=["_key_prov_tambon", "_loc_name"], how="left"
)

# --- Match each ECT69 location to best ECT66 ---
print(f"Matching {len(ect69_unique):,} ECT69 locations to ECT66...")

col_province = ect69.columns[0]  # จังหวัด
col_district_num = ect69.columns[1]  # เขตเลือกตั้ง
col_amphoe = ect69.columns[2]  # อำเภอ
col_tambon = ect69.columns[4]  # ตำบล

results = []
total = len(ect69_unique)

for idx, (_, row) in enumerate(ect69_unique.iterrows()):
    if idx % 5000 == 0:
        print(f"  {idx}/{total}...")

    tambon_key = row["_key_prov_tambon"]
    loc_name = row["_loc_name"]
    candidates = ect66_lookup.get(tambon_key, [])

    best_sim = 0.0
    best_match = None

    for cand in candidates:
        if loc_name == cand["name"]:
            best_sim = 1.0
            best_match = cand
            break
        sim = trigram_similarity(loc_name, cand["name"])
        if sim > best_sim:
            best_sim = sim
            best_match = cand

    # Classify match
    if best_sim >= 0.8:
        match_tier = "exact"
    elif best_sim >= 0.6:
        match_tier = "strong"
    elif best_sim >= 0.3:
        match_tier = "weak"
    else:
        match_tier = "no_match"

    # Determine action
    if best_match and best_match["tier"] == "A+" and best_sim >= 0.8:
        action = "reuse_coords"
    elif best_match and best_match["tier"] == "A+" and best_sim >= 0.6:
        action = "verify_then_reuse"
    elif best_match and best_sim >= 0.3:
        action = "use_as_reference"
    else:
        action = "geocode_fresh"

    results.append(
        {
            "จังหวัด": row[col_province],
            "เขตเลือกตั้ง": row[col_district_num],
            "อำเภอ": row[col_amphoe],
            "ตำบล": row[col_tambon],
            "ect69_location": loc_name,
            "ect69_location_extra": row["location_extra"],
            "ect69_location_type": row["location_type"],
            "ect69_geocode_query": row["geocode_query"],
            "ect69_unit_count": row["unit_count"],
            "ect69_unit_numbers": row["unit_numbers"],
            "ect69_location_id": row["location_id"],
            "ect66_location": best_match["name"] if best_match else None,
            "similarity": round(best_sim, 3),
            "match_tier": match_tier,
            "ect66_tier": best_match["tier"] if best_match else None,
            "ect66_lat": best_match["lat"] if best_match else None,
            "ect66_lng": best_match["lng"] if best_match else None,
            "ect66_address": best_match["address"] if best_match else None,
            "ect66_place_id": best_match["place_id"] if best_match else None,
            "action": action,
        }
    )

df_result = pd.DataFrame(results)

# Sort: geocode_fresh first (needs work), then by province/tambon
action_order = {
    "geocode_fresh": 0,
    "use_as_reference": 1,
    "verify_then_reuse": 2,
    "reuse_coords": 3,
}
df_result["_sort"] = df_result["action"].map(action_order)
df_result = df_result.sort_values(
    ["_sort", "จังหวัด", "อำเภอ", "ตำบล", "ect69_location"]
).drop(columns=["_sort"])

# --- Province summary ---
print("Building province summary...")
prov_summary = (
    df_result.groupby("จังหวัด")
    .agg(
        total_locations=("ect69_location", "size"),
        total_units=("ect69_unit_count", "sum"),
        reuse_coords=("action", lambda x: (x == "reuse_coords").sum()),
        verify_then_reuse=("action", lambda x: (x == "verify_then_reuse").sum()),
        use_as_reference=("action", lambda x: (x == "use_as_reference").sum()),
        geocode_fresh=("action", lambda x: (x == "geocode_fresh").sum()),
        avg_similarity=("similarity", "mean"),
    )
    .reset_index()
)
prov_summary["reuse_pct"] = (
    (prov_summary["reuse_coords"] + prov_summary["verify_then_reuse"])
    / prov_summary["total_locations"]
    * 100
).round(1)
prov_summary = prov_summary.sort_values("geocode_fresh", ascending=False)

# --- No-match sheet (subset for easy assignment) ---
df_no_match = df_result[df_result["action"] == "geocode_fresh"][
    [
        "จังหวัด",
        "เขตเลือกตั้ง",
        "อำเภอ",
        "ตำบล",
        "ect69_location",
        "ect69_location_extra",
        "ect69_location_type",
        "ect69_geocode_query",
        "ect69_unit_count",
        "ect69_unit_numbers",
    ]
].copy()

# --- Write Excel ---
print(f"Writing Excel to {OUTPUT_PATH}...")
with pd.ExcelWriter(OUTPUT_PATH, engine="openpyxl") as writer:
    df_result.to_excel(writer, sheet_name="all_matches", index=False)
    prov_summary.to_excel(writer, sheet_name="province_summary", index=False)
    df_no_match.to_excel(writer, sheet_name="needs_geocoding", index=False)

# --- Print summary ---
print("\n" + "=" * 60)
print("Export complete!")
print("=" * 60)
print(f"Output: {OUTPUT_PATH}")
print(f"Total unique locations: {len(df_result):,}")
print("\nAction breakdown:")
print(df_result["action"].value_counts().to_string())
print("\nMatch tier breakdown:")
print(df_result["match_tier"].value_counts().to_string())
print("\nSheets:")
print(
    f"  all_matches: {len(df_result):,} rows — every ECT69 location with best ECT66 match"
)
print(f"  province_summary: {len(prov_summary)} rows — stats per province")
print(
    f"  needs_geocoding: {len(df_no_match):,} rows — locations that need fresh geocoding"
)
