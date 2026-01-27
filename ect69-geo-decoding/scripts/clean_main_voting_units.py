#!/usr/bin/env python
"""Clean ECT69 main election day voting units data.

This script processes the raw ECT69 voting units CSV and produces a cleaned
Parquet file with parsed location fields ready for geocoding.
"""

import hashlib
import re
from pathlib import Path

import pandas as pd

# --- Constants ---
BASE_DIR = Path(__file__).parent.parent
INPUT_PATH = BASE_DIR / "inputs/ect69-voting-units-20260121.csv"
OUTPUT_PATH = BASE_DIR / "intermediate/ect69_voting_units_cleaned.parquet"

# Location type prefixes (order matters - longer matches first)
PREFIX_TYPES = {
    "เต็นท์บริเวณ": "tent_area",
    "เต็นท์ลานจอดรถ": "tent_parking",
    "เต็นท์ลาน": "tent_area",
    "เต็นท์หน้า": "tent_front",
    "เต็นท์ข้าง": "tent_side",
    "เต็นท์": "tent",
    "ศาลาหน้า": "pavilion_front",
    "ศาลาข้าง": "pavilion_side",
    "ศาลาประชาคม": "community_pavilion",
    "ศาลาอเนกประสงค์": "multipurpose_pavilion",
    "ศาลาเอนกประสงค์": "multipurpose_pavilion",  # alternate spelling
    "ศาลาวัด": "temple_pavilion",
    "ศาลา": "pavilion",
    "อาคารเอนกประสงค์": "multipurpose_building",
    "อาคารอเนกประสงค์": "multipurpose_building",  # alternate spelling
    "อาคารหอประชุม": "assembly_building",
    "อาคาร": "building",
    "หอประชุม": "assembly_hall",
    "โดมเอนกประสงค์": "multipurpose_dome",
    "โดมอเนกประสงค์": "multipurpose_dome",  # alternate spelling
    "โดม": "dome",
    "ลานเอนกประสงค์": "multipurpose_area",
    "ลานอเนกประสงค์": "multipurpose_area",  # alternate spelling
    "ลานจอดรถ": "parking",
    "ลาน": "area",
    "บริเวณ": "area",
    "ใต้ถุน": "under_building",
    "โรงเรียน": "school",
    "วัด": "temple",
    "มัสยิด": "mosque",
    "โบสถ์": "church",
    "สำนักงาน": "office",
    "ที่ทำการ": "office",
}

# Parenthetical patterns with classifications
PAREN_PATTERNS = {
    # Unit sequence: (1), (2), etc.
    "unit_sequence": re.compile(r"^\((\d+)\)$"),
    # Relocation notes
    "relocation_note": re.compile(r"^\(ย้าย(?:มาจาก)?(.+)\)$"),
    # Direction/side indicators
    "direction": re.compile(r"^\((ฝั่ง.+|ด้าน.+|ข้าง.+|หน้า.+|หลัง.+|ตรงข้าม.+|ใกล้.+)\)$"),
    # Access info (soi, road references)
    "access_info": re.compile(r"^\((ซอย.+|ถนน.+|ซ\..+)\)$"),
    # Sublocation within venue
    "sublocation": re.compile(r"^\((ศาลา\s*\d+|เต็นท์\s*\d+|ห้อง\s*\d+|ชั้น\s*\d+)\)$"),
    # Construction/building type
    "construction_type": re.compile(r"^\((หลังใหม่|หลังเก่า|เต็นท์|ชั่วคราว|ถาวร)\)$"),
    # Building codes
    "building_code": re.compile(r"^\(([A-Z]{2,5})\)$"),
}


def clean_text(text: str | None) -> str:
    """Basic text cleaning: strip whitespace, fix corrupted chars."""
    if pd.isna(text) or text is None:
        return ""
    text = str(text).strip()
    # Fix corrupted character pattern #ุ -> #
    text = text.replace("#ุ", "#")
    # Fix corrupted pattern with # inside relocation notes: (ย้าย#มาจาก -> (ย้ายมาจาก
    text = re.sub(r"\(ย้าย#มาจาก", "(ย้ายมาจาก", text)
    # Normalize multiple spaces
    text = re.sub(r"\s+", " ", text)
    return text


def clean_hash_delimiter(text: str) -> tuple[str, str | None]:
    """Split on # delimiter, return (main, extra).

    Rules:
    - If ends with #, remove trailing #
    - If # in middle, split into main and extra
    """
    if not text:
        return "", None

    # Handle trailing # (most common case: ~97%)
    if text.endswith("#"):
        return text.rstrip("#").strip(), None

    # Handle # in middle (extra info follows)
    if "#" in text:
        parts = text.split("#", 1)
        main = parts[0].strip()
        extra = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
        return main, extra

    # No # at all (shouldn't happen based on EDA, but handle gracefully)
    return text, None


def extract_parentheticals(text: str) -> dict:
    """Extract and classify (...) content from location text.

    Returns dict with:
    - cleaned_text: text with parentheticals removed
    - unit_sequence: int if (1), (2) etc found
    - relocation_note: str if ย้ายมาจาก found
    - direction: str if direction indicator found
    - access_info: str if ซอย/ถนน reference found
    - sublocation: str if ศาลา 1, etc found
    - construction_type: str if หลังใหม่/เก่า found
    - building_code: str if (SML) etc found
    - other_parens: list of unclassified parentheticals
    """
    result = {
        "cleaned_text": text,
        "unit_sequence": None,
        "relocation_note": None,
        "direction": None,
        "access_info": None,
        "sublocation": None,
        "construction_type": None,
        "building_code": None,
        "other_parens": [],
    }

    if not text or "(" not in text:
        return result

    # Find all parenthetical content
    paren_pattern = re.compile(r"\([^)]+\)")
    matches = paren_pattern.findall(text)

    if not matches:
        return result

    cleaned = text
    for match in matches:
        classified = False

        # Try to classify each parenthetical
        for field, pattern in PAREN_PATTERNS.items():
            m = pattern.match(match)
            if m:
                if field == "unit_sequence":
                    result["unit_sequence"] = int(m.group(1))
                elif field == "relocation_note":
                    result["relocation_note"] = m.group(1).strip()
                else:
                    # For other fields, store the matched content (without parens)
                    inner = match[1:-1]  # Remove ( and )
                    if result[field] is None:
                        result[field] = inner
                    else:
                        # Multiple matches of same type - append
                        result[field] = f"{result[field]}; {inner}"
                classified = True
                break

        if not classified:
            # Store unclassified parentheticals
            result["other_parens"].append(match[1:-1])  # Remove parens

        # Remove from cleaned text
        cleaned = cleaned.replace(match, "").strip()

    # Clean up extra spaces
    result["cleaned_text"] = re.sub(r"\s+", " ", cleaned).strip()
    return result


def classify_prefix(text: str) -> str | None:
    """Identify location type from leading prefix."""
    if not text:
        return None

    for prefix, loc_type in PREFIX_TYPES.items():
        if text.startswith(prefix):
            return loc_type

    return None


def normalize_for_grouping(text: str) -> str:
    """Normalize location text for grouping/deduplication.

    Removes:
    - Sequence numbers (1), (2)
    - Extra whitespace
    - Trailing punctuation
    """
    if not text:
        return ""

    normalized = text

    # Remove sequence numbers like (1), (2)
    normalized = re.sub(r"\s*\(\d+\)\s*", " ", normalized)

    # Remove common noise patterns
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = normalized.strip()

    # Remove trailing punctuation
    normalized = normalized.rstrip("#.,;:")

    return normalized


def generate_location_id(
    province: str, district: str, tambon: str, normalized_location: str
) -> str:
    """Generate unique location ID for geocoding deduplication.

    Uses MD5 hash of (province, district, tambon, normalized_location).
    """
    key = f"{province}|{district}|{tambon}|{normalized_location}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:16]


def generate_geocode_query(row: pd.Series) -> str:
    """Build optimal search string for geocoding.

    Strategy:
    - Use location_main as base
    - Add tambon, district, province for context
    - For BKK, use district (เขต) instead of ตำบล
    """
    parts = []

    # Main location
    location = row.get("location_main", "")
    if location:
        parts.append(location)

    # Add geographic context
    tambon = row.get("ตำบล", "")
    district = row.get("อำเภอ", "")
    province = row.get("จังหวัด", "")

    # For Bangkok, skip tambon (แขวง) - district (เขต) is more useful
    if province == "กรุงเทพมหานคร":
        if district:
            parts.append(district)
    else:
        if tambon:
            parts.append(tambon)
        if district:
            parts.append(district)

    if province:
        parts.append(province)

    return " ".join(parts)


def main():
    """Main cleaning pipeline."""
    print(f"Reading input: {INPUT_PATH}")
    df = pd.read_csv(INPUT_PATH)
    print(f"Input rows: {len(df):,}")

    # ========================================
    # Step 1: Basic Cleaning
    # ========================================
    print("\n[1/6] Basic cleaning...")

    # Strip whitespace from all string columns
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].apply(clean_text)

    # Convert float columns to int (เขตเลือกตั้ง, หน่วยเลือกตั้ง)
    df["เขตเลือกตั้ง"] = df["เขตเลือกตั้ง"].astype(int)
    df["หน่วยเลือกตั้ง"] = df["หน่วยเลือกตั้ง"].astype(int)

    # Rename original location column
    df = df.rename(columns={"สถานที่เลือกตั้ง": "สถานที่เลือกตั้ง_raw"})

    # ========================================
    # Step 2: Hash Delimiter Processing
    # ========================================
    print("[2/6] Processing # delimiter...")

    hash_results = df["สถานที่เลือกตั้ง_raw"].apply(clean_hash_delimiter)
    df["location_main"] = hash_results.apply(lambda x: x[0])
    df["location_extra"] = hash_results.apply(lambda x: x[1])

    # ========================================
    # Step 3: Parenthetical Extraction
    # ========================================
    print("[3/6] Extracting parentheticals...")

    paren_results = df["location_main"].apply(extract_parentheticals)

    df["location_main"] = paren_results.apply(lambda x: x["cleaned_text"])
    df["unit_sequence"] = paren_results.apply(lambda x: x["unit_sequence"])
    df["sublocation"] = paren_results.apply(lambda x: x["sublocation"])
    df["relocation_note"] = paren_results.apply(lambda x: x["relocation_note"])
    df["direction"] = paren_results.apply(lambda x: x["direction"])

    # Also extract relocation notes from location_extra (they often appear after #)
    def extract_relocation_from_extra(extra: str | None) -> str | None:
        if pd.isna(extra) or not extra:
            return None
        # Pattern: (ย้ายมาจาก...) anywhere in the extra text
        match = re.search(r"\(ย้าย(?:มาจาก)?\s*(.+?)\)", extra)
        if match:
            return match.group(1).strip()
        return None

    extra_reloc = df["location_extra"].apply(extract_relocation_from_extra)
    # Merge: prefer main if exists, otherwise use extra
    df["relocation_note"] = df["relocation_note"].combine_first(extra_reloc)

    # Clean location_extra by removing relocation notes
    def clean_extra_relocation(extra: str | None) -> str | None:
        if pd.isna(extra) or not extra:
            return None
        cleaned = re.sub(r"\(ย้าย(?:มาจาก)?\s*.+?\)", "", extra).strip()
        return cleaned if cleaned else None

    df["location_extra"] = df["location_extra"].apply(clean_extra_relocation)

    # ========================================
    # Step 4: Prefix Classification
    # ========================================
    print("[4/6] Classifying location types...")

    df["location_type"] = df["location_main"].apply(classify_prefix)

    # ========================================
    # Step 5: Location Grouping
    # ========================================
    print("[5/6] Generating location groups...")

    df["location_normalized"] = df["location_main"].apply(normalize_for_grouping)

    df["location_id"] = df.apply(
        lambda row: generate_location_id(
            row["จังหวัด"], row["อำเภอ"], row["ตำบล"], row["location_normalized"]
        ),
        axis=1,
    )

    # ========================================
    # Step 6: Generate Geocode Query
    # ========================================
    print("[6/6] Generating geocode queries...")

    df["geocode_query"] = df.apply(generate_geocode_query, axis=1)

    # ========================================
    # Quality Report
    # ========================================
    print("\n" + "=" * 50)
    print("QUALITY REPORT")
    print("=" * 50)

    print(f"\nTotal rows: {len(df):,}")
    print(f"Rows with location_main: {(df['location_main'] != '').sum():,}")
    print(f"Rows with location_extra: {df['location_extra'].notna().sum():,}")
    print(f"Rows with unit_sequence: {df['unit_sequence'].notna().sum():,}")
    print(f"Rows with sublocation: {df['sublocation'].notna().sum():,}")
    print(f"Rows with relocation_note: {df['relocation_note'].notna().sum():,}")
    print(f"Rows with direction: {df['direction'].notna().sum():,}")

    print(f"\nUnique locations (location_id): {df['location_id'].nunique():,}")

    print("\nLocation types:")
    type_counts = df["location_type"].value_counts(dropna=False)
    for loc_type, count in type_counts.head(15).items():
        pct = count / len(df) * 100
        type_name = loc_type if loc_type else "(none)"
        print(f"  {type_name}: {count:,} ({pct:.1f}%)")

    # ========================================
    # Select and Order Columns
    # ========================================
    output_columns = [
        # Original columns
        "จังหวัด",
        "เขตเลือกตั้ง",
        "อำเภอ",
        "สำนักทะเบียน",
        "ตำบล",
        "หน่วยเลือกตั้ง",
        # Raw location
        "สถานที่เลือกตั้ง_raw",
        # Cleaned/parsed fields
        "location_main",
        "location_extra",
        "location_type",
        "unit_sequence",
        "sublocation",
        "relocation_note",
        "direction",
        # For geocoding
        "location_id",
        "geocode_query",
    ]

    df_out = df[output_columns]

    # ========================================
    # Export
    # ========================================
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_parquet(OUTPUT_PATH, index=False)
    print(f"\nOutput written to: {OUTPUT_PATH}")
    print(f"Output rows: {len(df_out):,}")

    # Verification checks
    print("\n" + "=" * 50)
    print("VERIFICATION")
    print("=" * 50)
    assert len(df_out) == 99954, f"Expected 99954 rows, got {len(df_out)}"
    assert (df_out["location_main"] != "").all(), "Some rows have empty location_main"
    print("All verifications passed!")


if __name__ == "__main__":
    main()
