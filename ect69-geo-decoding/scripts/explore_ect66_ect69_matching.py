#!/usr/bin/env python
"""Explore matching between ECT66 and ECT69 voting unit datasets.

Compares the two election datasets to understand:
- How many locations carry over between elections
- Matching rates by province, district, subdistrict
- Name similarity distribution for location fuzzy matching
- Which ECT66 geocoded coords can be reused for ECT69
"""

from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent.parent

# --- Load datasets ---
print("=" * 60)
print("Loading datasets...")
print("=" * 60)

ect66 = pd.read_parquet(
    BASE_DIR
    / "outputs"
    / ".."
    / ".."
    / "ect66-geo-decoding"
    / "outputs"
    / "ect66_geocoded_validated.parquet"
)
ect69_cleaned = pd.read_parquet(
    BASE_DIR / "intermediate" / "ect69_voting_units_cleaned.parquet"
)
ect69_raw = pd.read_csv(BASE_DIR / "inputs" / "ect69-voting-units-20260121.csv")

print(f"ECT66: {len(ect66):,} rows, columns: {list(ect66.columns)}")
print(
    f"ECT69 cleaned: {len(ect69_cleaned):,} rows, columns: {list(ect69_cleaned.columns)}"
)
print(f"ECT69 raw: {len(ect69_raw):,} rows, columns: {list(ect69_raw.columns)}")

# --- Basic stats ---
print("\n" + "=" * 60)
print("Basic Statistics")
print("=" * 60)

print(f"\nECT66 provinces: {ect66['ProvinceName'].nunique()}")
print(f"ECT69 provinces: {ect69_cleaned['จังหวัด'].nunique()}")

print(f"\nECT66 subdistricts: {ect66['SubDistrictName'].nunique()}")
print(f"ECT69 subdistricts: {ect69_cleaned['ตำบล'].nunique()}")

print(f"\nECT66 unique DisplayUnitName: {ect66['DisplayUnitName'].nunique()}")
print(f"ECT69 unique location_main: {ect69_cleaned['location_main'].nunique()}")

# --- Normalize names for comparison ---
print("\n" + "=" * 60)
print("Province-level matching")
print("=" * 60)

ect66_provinces = set(ect66["ProvinceName"].str.strip().unique())
ect69_provinces = set(ect69_cleaned["จังหวัด"].str.strip().unique())

common_provinces = ect66_provinces & ect69_provinces
only_66 = ect66_provinces - ect69_provinces
only_69 = ect69_provinces - ect66_provinces

print(f"Common provinces: {len(common_provinces)}")
print(f"Only in ECT66: {len(only_66)} → {sorted(only_66)[:10]}")
print(f"Only in ECT69: {len(only_69)} → {sorted(only_69)[:10]}")

# --- Subdistrict-level matching ---
print("\n" + "=" * 60)
print("Subdistrict-level matching (province + tambon)")
print("=" * 60)

ect66["_key_prov_tambon"] = (
    ect66["ProvinceName"].str.strip() + "|" + ect66["SubDistrictName"].str.strip()
)
ect69_cleaned["_key_prov_tambon"] = (
    ect69_cleaned["จังหวัด"].str.strip() + "|" + ect69_cleaned["ตำบล"].str.strip()
)

ect66_tambons = set(ect66["_key_prov_tambon"].unique())
ect69_tambons = set(ect69_cleaned["_key_prov_tambon"].unique())

common_tambons = ect66_tambons & ect69_tambons
only_66_tambons = ect66_tambons - ect69_tambons
only_69_tambons = ect69_tambons - ect66_tambons

print(f"Common province|tambon pairs: {len(common_tambons)}")
print(f"Only in ECT66: {len(only_66_tambons)}")
print(f"Only in ECT69: {len(only_69_tambons)}")

if only_69_tambons:
    print("\nSample ECT69-only tambons (first 15):")
    for t in sorted(only_69_tambons)[:15]:
        print(f"  {t}")

if only_66_tambons:
    print("\nSample ECT66-only tambons (first 15):")
    for t in sorted(only_66_tambons)[:15]:
        print(f"  {t}")

# --- District-level matching (province + amphoe) ---
print("\n" + "=" * 60)
print("District-level matching (province + amphoe)")
print("=" * 60)

ect66["_key_prov_amphoe"] = (
    ect66["ProvinceName"].str.strip() + "|" + ect66["DistrictName"].str.strip()
)
ect69_cleaned["_key_prov_amphoe"] = (
    ect69_cleaned["จังหวัด"].str.strip() + "|" + ect69_cleaned["อำเภอ"].str.strip()
)

ect66_amphoes = set(ect66["_key_prov_amphoe"].unique())
ect69_amphoes = set(ect69_cleaned["_key_prov_amphoe"].unique())

common_amphoes = ect66_amphoes & ect69_amphoes
print(f"Common province|amphoe pairs: {len(common_amphoes)}")
print(f"Only in ECT66: {len(ect66_amphoes - ect69_amphoes)}")
print(f"Only in ECT69: {len(ect69_amphoes - ect66_amphoes)}")

# --- Unit count comparison per tambon ---
print("\n" + "=" * 60)
print("Unit count changes per tambon")
print("=" * 60)

ect66_tambon_counts = ect66.groupby("_key_prov_tambon").size().rename("ect66_units")
ect69_tambon_counts = (
    ect69_cleaned.groupby("_key_prov_tambon").size().rename("ect69_units")
)

tambon_compare = (
    pd.concat([ect66_tambon_counts, ect69_tambon_counts], axis=1).fillna(0).astype(int)
)
tambon_compare["diff"] = tambon_compare["ect69_units"] - tambon_compare["ect66_units"]

print(f"Tambons with more units in ECT69: {(tambon_compare['diff'] > 0).sum()}")
print(f"Tambons with same units: {(tambon_compare['diff'] == 0).sum()}")
print(f"Tambons with fewer units in ECT69: {(tambon_compare['diff'] < 0).sum()}")
print("\nUnit diff distribution:")
print(tambon_compare["diff"].describe())

# --- Location name matching within same tambon ---
print("\n" + "=" * 60)
print("Location name matching (same tambon, exact match)")
print("=" * 60)

# Build lookup: for each tambon, the set of location names in ECT66
# ECT66 DisplayUnitName has format "11 - เต็นท์บริเวณ..." or just the name — strip the prefix
ect66["_loc_name"] = (
    ect66["DisplayUnitName"].str.replace(r"^\d+\s*-\s*", "", regex=True).str.strip()
)
# Also try UnitName which may be cleaner
ect66["_loc_name_alt"] = ect66["UnitName"].str.strip()
ect69_cleaned["_loc_name"] = ect69_cleaned["location_main"].str.strip()

ect66_tambon_locs = ect66.groupby("_key_prov_tambon")["_loc_name"].apply(set).to_dict()
ect69_tambon_locs = (
    ect69_cleaned.groupby("_key_prov_tambon")["_loc_name"].apply(set).to_dict()
)

exact_match_count = 0
no_match_count = 0
partial_match_count = 0
total_69_locs = 0

for tambon, locs69 in ect69_tambon_locs.items():
    locs66 = ect66_tambon_locs.get(tambon, set())
    for loc in locs69:
        total_69_locs += 1
        if loc in locs66:
            exact_match_count += 1
        elif any(loc in l66 or l66 in loc for l66 in locs66 if len(l66) > 3):
            partial_match_count += 1
        else:
            no_match_count += 1

print(f"Total unique ECT69 locations (per tambon): {total_69_locs}")
print(
    f"Exact name match in ECT66: {exact_match_count} ({exact_match_count / total_69_locs * 100:.1f}%)"
)
print(
    f"Substring match: {partial_match_count} ({partial_match_count / total_69_locs * 100:.1f}%)"
)
print(f"No match: {no_match_count} ({no_match_count / total_69_locs * 100:.1f}%)")

# --- Fuzzy matching sample using trigram-like similarity ---
print("\n" + "=" * 60)
print("Fuzzy matching sample (first 20 non-exact matches in กรุงเทพมหานคร)")
print("=" * 60)


def trigram_similarity(s1: str, s2: str) -> float:
    """Simple trigram similarity (Jaccard of character trigrams)."""
    if not s1 or not s2:
        return 0.0
    t1 = {s1[i : i + 3] for i in range(len(s1) - 2)}
    t2 = {s2[i : i + 3] for i in range(len(s2) - 2)}
    if not t1 or not t2:
        return 0.0
    return len(t1 & t2) / len(t1 | t2)


bkk_tambons = [t for t in ect69_tambon_locs if t.startswith("กรุงเทพมหานคร")]
sample_count = 0

for tambon in sorted(bkk_tambons)[:5]:
    locs69 = ect69_tambon_locs[tambon]
    locs66 = ect66_tambon_locs.get(tambon, set())
    if not locs66:
        continue

    for loc69 in sorted(locs69):
        if loc69 in locs66:
            continue  # skip exact matches
        # find best fuzzy match
        best_sim = 0.0
        best_match = ""
        for loc66 in locs66:
            sim = trigram_similarity(loc69, loc66)
            if sim > best_sim:
                best_sim = sim
                best_match = loc66
        if best_match and sample_count < 20:
            print(f"  [{tambon.split('|')[1]}] ECT69: {loc69}")
            print(f"    → ECT66: {best_match} (sim={best_sim:.3f})")
            print()
            sample_count += 1

# --- ECT66 tier distribution for matchable locations ---
print("\n" + "=" * 60)
print("ECT66 tier distribution (what quality coords are available)")
print("=" * 60)

print(ect66["TierLocation"].value_counts().to_string())

# --- Reusability estimate ---
print("\n" + "=" * 60)
print("Reusability estimate: ECT66 Tier A+ coords for ECT69")
print("=" * 60)

ect66_aplus = ect66[ect66["TierLocation"] == "A+"].copy()
ect66_aplus_tambon_locs = (
    ect66_aplus.groupby("_key_prov_tambon")["_loc_name"].apply(set).to_dict()
)

reusable_exact = 0
reusable_fuzzy = 0
total_unique_69 = 0

for tambon, locs69 in ect69_tambon_locs.items():
    locs66_aplus = ect66_aplus_tambon_locs.get(tambon, set())
    for loc in locs69:
        total_unique_69 += 1
        if loc in locs66_aplus:
            reusable_exact += 1
        elif locs66_aplus:
            best_sim = max(trigram_similarity(loc, l66) for l66 in locs66_aplus)
            if best_sim >= 0.6:
                reusable_fuzzy += 1

print(f"Total unique ECT69 locations: {total_unique_69}")
print(
    f"Exact match to ECT66 A+ location: {reusable_exact} ({reusable_exact / total_unique_69 * 100:.1f}%)"
)
print(
    f"Fuzzy match (sim>=0.6) to ECT66 A+: {reusable_fuzzy} ({reusable_fuzzy / total_unique_69 * 100:.1f}%)"
)
print(
    f"Combined reusable: {reusable_exact + reusable_fuzzy} ({(reusable_exact + reusable_fuzzy) / total_unique_69 * 100:.1f}%)"
)
print(
    f"Needs new geocoding: {total_unique_69 - reusable_exact - reusable_fuzzy} ({(total_unique_69 - reusable_exact - reusable_fuzzy) / total_unique_69 * 100:.1f}%)"
)

# --- Electoral district changes ---
print("\n" + "=" * 60)
print("Electoral district comparison")
print("=" * 60)

ect66_divisions = (
    ect66.groupby("ProvinceName")["DivisionNumber"].nunique().rename("ect66_divisions")
)
ect69_divisions = (
    ect69_cleaned.groupby("จังหวัด")["เขตเลือกตั้ง"].nunique().rename("ect69_divisions")
)

div_compare = pd.concat([ect66_divisions, ect69_divisions], axis=1).dropna()
div_compare["diff"] = div_compare["ect69_divisions"] - div_compare["ect66_divisions"]
changed = div_compare[div_compare["diff"] != 0]

print(
    f"Provinces with same # of electoral districts: {(div_compare['diff'] == 0).sum()}"
)
print(f"Provinces with changed # of electoral districts: {len(changed)}")
if len(changed) > 0:
    print("\nChanged provinces:")
    print(changed.to_string())

# --- station66 comparison (heypoom data) ---
print("\n" + "=" * 60)
print("Station66 (heypoom) data comparison")
print("=" * 60)

station66_path = BASE_DIR / "outputs" / "station66_with_source_manual.parquet"
if station66_path.exists():
    station66 = pd.read_parquet(station66_path)
    print(f"Station66 rows: {len(station66):,}")
    print(
        f"With coordinates: {station66['has_coords'].sum():,} ({station66['has_coords'].mean() * 100:.1f}%)"
    )
    print(f"Columns: {list(station66.columns)}")
    print("\nSource classification:")
    print(station66["source_classification"].value_counts().to_string())
else:
    station66_path2 = BASE_DIR / "outputs" / "station66_with_source.parquet"
    if station66_path2.exists():
        station66 = pd.read_parquet(station66_path2)
        print(f"Station66 rows: {len(station66):,}")
        print(
            f"With coordinates: {station66['has_coords'].sum():,} ({station66['has_coords'].mean() * 100:.1f}%)"
        )
        print(f"Columns: {list(station66.columns)}")
    else:
        print("No station66 file found")

print("\n" + "=" * 60)
print("Summary")
print("=" * 60)
print(f"""
ECT66: {len(ect66):,} voting units across {ect66["ProvinceName"].nunique()} provinces
ECT69: {len(ect69_cleaned):,} voting units across {ect69_cleaned["จังหวัด"].nunique()} provinces
Net change: {len(ect69_cleaned) - len(ect66):+,} units

Location matching (same tambon):
  Exact: {exact_match_count}/{total_69_locs} ({exact_match_count / total_69_locs * 100:.1f}%)
  Substring: {partial_match_count}/{total_69_locs} ({partial_match_count / total_69_locs * 100:.1f}%)
  No match: {no_match_count}/{total_69_locs} ({no_match_count / total_69_locs * 100:.1f}%)

ECT66 A+ reusable for ECT69:
  Exact: {reusable_exact} ({reusable_exact / total_unique_69 * 100:.1f}%)
  Fuzzy (sim>=0.6): {reusable_fuzzy} ({reusable_fuzzy / total_unique_69 * 100:.1f}%)
  Needs new geocoding: {total_unique_69 - reusable_exact - reusable_fuzzy} ({(total_unique_69 - reusable_exact - reusable_fuzzy) / total_unique_69 * 100:.1f}%)
""")
