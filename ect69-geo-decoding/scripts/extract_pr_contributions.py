#!/usr/bin/env python3
"""
Extract PR contributions from election-station-66 repository.

This ETL script:
1. Extracts commit history from a starting commit
2. Parses CSV changes to identify coordinate updates
3. Classifies each commit as manual or scripted
4. Builds a final dataset with source attribution

Usage:
    uv run python ect69-geo-decoding/scripts/extract_pr_contributions.py \
        --source-repo ~/ddd/ninyawee/election-station-66

Output:
    intermediate/commits_metadata.parquet
    intermediate/row_changes.parquet
    outputs/station66_with_source.parquet
"""

import argparse
import io
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from tqdm import tqdm

# Add parent dir to path for lib imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.git_utils import get_commit_list, get_commit_metadata, get_file_at_commit
from lib.models import CommitInfo, RowChange

# Constants
START_COMMIT = "1be4945dce44986c64a1b6ee2fb627b39104b2c0"
CSV_FILE = "station66_distinct_clean.csv"

# Classification thresholds
ROW_COUNT_SCRIPTED = 100  # >100 rows = scripted
ROW_COUNT_MANUAL = 50  # <=50 rows can be manual
TIME_GAP_SCRIPTED = 30  # <30s between commits = scripted
TIME_GAP_MANUAL = 300  # >5min gap supports manual classification

# Patterns
ROW_RANGE_PATTERN = re.compile(r"rows?\s+\d+[-–\s]+\d+", re.IGNORECASE)
BATCH_PATTERN = re.compile(r"Add latitude/longitude for rows", re.IGNORECASE)
THAI_LOCATION_INDICATORS = ["จังหวัด", "อำเภอ", "ตำบล", "บ้าน", "วัด", "โรงเรียน", "ศาลา"]

# CSV natural key columns
KEY_COLUMNS = [
    "provinceNumber",
    "registrar_code",
    "subdis_code",
    "electorate",
    "location",
]


def parse_csv_content(content: str) -> pd.DataFrame:
    """Parse CSV content string to DataFrame."""
    return pd.read_csv(
        io.StringIO(content),
        dtype={
            "provinceNumber": int,
            "registrar_code": int,
            "subdis_code": int,
            "electorate": int,
            "latitude": str,  # Read as string first to handle mixed types
            "longitude": str,
        },
        low_memory=False,
    )


def convert_coord_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Convert latitude/longitude from string to float, handling empty values."""
    df = df.copy()
    for col in ["latitude", "longitude"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def find_coordinate_changes(
    df_before: pd.DataFrame, df_after: pd.DataFrame
) -> list[dict]:
    """
    Find rows where coordinates changed between two states.

    Returns list of dicts with key columns and before/after coordinates.
    """
    changes = []

    # Create composite key for matching
    df_before = df_before.copy()
    df_after = df_after.copy()

    df_before["_key"] = df_before[KEY_COLUMNS].astype(str).agg("|".join, axis=1)
    df_after["_key"] = df_after[KEY_COLUMNS].astype(str).agg("|".join, axis=1)

    # Create lookup from before state
    before_coords = {}
    for _, row in df_before.iterrows():
        lat = row.get("latitude")
        lng = row.get("longitude")
        has_coords = pd.notna(lat) and pd.notna(lng)
        before_coords[row["_key"]] = (
            lat if has_coords else None,
            lng if has_coords else None,
        )

    # Check each row in after state
    for _, row in df_after.iterrows():
        key = row["_key"]
        lat_after = row.get("latitude")
        lng_after = row.get("longitude")
        after_has_coords = pd.notna(lat_after) and pd.notna(lng_after)

        if key in before_coords:
            lat_before, lng_before = before_coords[key]
            before_has_coords = lat_before is not None

            # Check if coordinates changed
            coords_added = not before_has_coords and after_has_coords
            coords_changed = (
                before_has_coords
                and after_has_coords
                and (lat_before != lat_after or lng_before != lng_after)
            )

            if coords_added or coords_changed:
                changes.append(
                    {
                        "provinceNumber": row["provinceNumber"],
                        "registrar_code": row["registrar_code"],
                        "subdis_code": row["subdis_code"],
                        "electorate": row["electorate"],
                        "location": row["location"],
                        "lat_before": lat_before,
                        "lng_before": lng_before,
                        "lat_after": lat_after if after_has_coords else None,
                        "lng_after": lng_after if after_has_coords else None,
                    }
                )

    return changes


def has_thai_location(message: str) -> bool:
    """Check if message contains Thai location indicators."""
    return any(ind in message for ind in THAI_LOCATION_INDICATORS)


def classify_commit(
    commit: CommitInfo,
    row_count: int,
    time_since_prev: int | None,
) -> tuple[str, str]:
    """
    Classify a commit as manual or scripted.

    Returns (classification, reason).
    """
    message = commit.message

    # Rule 1: Explicit batch pattern in message
    if BATCH_PATTERN.search(message):
        return "scripted", "message_batch_pattern"

    # Rule 2: Row range pattern in message
    if ROW_RANGE_PATTERN.search(message):
        return "scripted", "message_row_range_pattern"

    # Rule 3: Very large change
    if row_count > ROW_COUNT_SCRIPTED:
        return "scripted", f"high_volume ({row_count} rows)"

    # Rule 4: Large change in rapid succession
    if (
        row_count > ROW_COUNT_MANUAL
        and time_since_prev
        and time_since_prev < TIME_GAP_SCRIPTED
    ):
        return "scripted", f"rapid_burst ({row_count} rows, {time_since_prev}s)"

    # Rule 5: Small change with Thai location in message
    if row_count <= 20 and has_thai_location(message):
        return "manual", f"small_thai_location ({row_count} rows)"

    # Rule 6: Small/medium change with time gap
    if (
        row_count <= ROW_COUNT_MANUAL
        and time_since_prev
        and time_since_prev > TIME_GAP_MANUAL
    ):
        return "manual", f"medium_with_gap ({row_count} rows, {time_since_prev}s)"

    # Rule 7: Very small change (likely manual)
    if row_count <= 5:
        return "manual", f"very_small ({row_count} rows)"

    # Fallback
    return "uncertain", f"no_clear_signal ({row_count} rows)"


def phase_a_extract_commits(repo_path: Path, output_dir: Path) -> list[CommitInfo]:
    """Phase A: Extract commit metadata from repository."""
    print("\n=== Phase A: Extracting commit metadata ===")

    commit_hashes = get_commit_list(repo_path, START_COMMIT)
    print(f"Found {len(commit_hashes)} commits from {START_COMMIT[:8]}..HEAD")

    commits = []
    for commit_hash in tqdm(commit_hashes, desc="Extracting metadata"):
        meta = get_commit_metadata(repo_path, commit_hash)

        commit = CommitInfo(
            commit_hash=meta["hash"],
            author_name=meta["author_name"],
            author_email=meta["author_email"],
            timestamp=meta["timestamp"],
            datetime_utc=datetime.fromtimestamp(meta["timestamp"], tz=timezone.utc),
            message=meta["message"],
            is_merge=meta["is_merge"],
            parent_hash=meta["parents"][0] if meta["parents"] else None,
        )
        commits.append(commit)

    # Sort by timestamp (oldest first) for processing
    commits.sort(key=lambda c: c.timestamp)

    # Save to parquet
    commits_df = pd.DataFrame([c.model_dump() for c in commits])
    commits_path = output_dir / "intermediate" / "commits_metadata.parquet"
    commits_df.to_parquet(commits_path, index=False)
    print(f"Saved {len(commits)} commits to {commits_path}")

    return commits


def phase_b_parse_and_classify(
    repo_path: Path, commits: list[CommitInfo], output_dir: Path
) -> pd.DataFrame:
    """Phase B: Parse CSV changes and classify each commit."""
    print("\n=== Phase B: Parsing changes and classifying ===")

    all_row_changes = []
    prev_commit = None
    prev_df = None

    # Filter out merge commits
    non_merge_commits = [c for c in commits if not c.is_merge]
    print(f"Processing {len(non_merge_commits)} non-merge commits")

    # Get initial state from parent of first commit
    if non_merge_commits:
        first_commit = non_merge_commits[0]
        if first_commit.parent_hash:
            try:
                parent_content = get_file_at_commit(
                    repo_path, first_commit.parent_hash, CSV_FILE
                )
                prev_df = convert_coord_columns(parse_csv_content(parent_content))
                print(f"Loaded parent state from {first_commit.parent_hash[:8]}")
            except Exception as e:
                print(f"Warning: Could not get parent state: {e}")

    for commit in tqdm(non_merge_commits, desc="Processing commits"):
        # Calculate time since previous commit
        time_since_prev = None
        if prev_commit:
            time_since_prev = commit.timestamp - prev_commit.timestamp

        # Get CSV state at this commit
        try:
            csv_content = get_file_at_commit(repo_path, commit.commit_hash, CSV_FILE)
            current_df = convert_coord_columns(parse_csv_content(csv_content))
        except Exception as e:
            print(f"Warning: Could not read CSV at {commit.commit_hash[:8]}: {e}")
            prev_commit = commit
            continue

        # Find changes if we have a previous state
        row_changes = []
        if prev_df is not None:
            row_changes = find_coordinate_changes(prev_df, current_df)

        # Classify the commit
        row_count = len(row_changes)
        classification, reason = classify_commit(commit, row_count, time_since_prev)

        # Update commit metadata
        commit.rows_changed = row_count
        commit.classification = classification
        commit.classification_reason = reason
        commit.time_since_prev_seconds = time_since_prev

        # Record row-level changes
        for change in row_changes:
            row_change = RowChange(
                province_number=change["provinceNumber"],
                registrar_code=change["registrar_code"],
                subdis_code=change["subdis_code"],
                electorate=change["electorate"],
                location=change["location"],
                lat_before=change["lat_before"],
                lng_before=change["lng_before"],
                lat_after=change["lat_after"],
                lng_after=change["lng_after"],
                commit_hash=commit.commit_hash,
                author_name=commit.author_name,
                author_email=commit.author_email,
                timestamp=commit.timestamp,
                classification=classification
                if classification != "none"
                else "uncertain",
            )
            all_row_changes.append(row_change)

        prev_commit = commit
        prev_df = current_df

    # Save updated commits metadata
    commits_df = pd.DataFrame([c.model_dump() for c in commits])
    commits_path = output_dir / "intermediate" / "commits_metadata.parquet"
    commits_df.to_parquet(commits_path, index=False)

    # Save row changes
    if all_row_changes:
        changes_df = pd.DataFrame([rc.model_dump() for rc in all_row_changes])
        changes_path = output_dir / "intermediate" / "row_changes.parquet"
        changes_df.to_parquet(changes_path, index=False)
        print(f"Saved {len(all_row_changes)} row changes to {changes_path}")
    else:
        changes_df = pd.DataFrame()
        print("No row changes found")

    # Print classification summary
    class_counts = commits_df["classification"].value_counts()
    print("\nClassification summary:")
    for cls, count in class_counts.items():
        print(f"  {cls}: {count}")

    return changes_df


def phase_c_build_output(
    repo_path: Path, changes_df: pd.DataFrame, output_dir: Path
) -> pd.DataFrame:
    """Phase C: Build final output with source attribution."""
    print("\n=== Phase C: Building final output ===")

    # Get latest CSV state
    csv_content = get_file_at_commit(repo_path, "HEAD", CSV_FILE)
    final_df = convert_coord_columns(parse_csv_content(csv_content))
    print(f"Loaded {len(final_df)} rows from current CSV")

    # Rename columns to match output schema
    final_df = final_df.rename(
        columns={
            "provinceNumber": "province_number",
            "registrar_code": "registrar_code",
            "subdis_code": "subdis_code",
            "electorate": "electorate",
            "location": "location",
            "province": "province",
            "registrar": "registrar",
            "subdistrict": "subdistrict",
            "latitude": "latitude",
            "longitude": "longitude",
        }
    )

    # Add source attribution columns
    final_df["has_coords"] = (
        final_df["latitude"].notna() & final_df["longitude"].notna()
    )
    final_df["source_commit"] = None
    final_df["source_author"] = None
    final_df["source_classification"] = "none"
    final_df["source_timestamp"] = None

    if not changes_df.empty:
        # Create lookup key for matching
        final_df["_key"] = (
            final_df["province_number"].astype(str)
            + "|"
            + final_df["registrar_code"].astype(str)
            + "|"
            + final_df["subdis_code"].astype(str)
            + "|"
            + final_df["electorate"].astype(str)
            + "|"
            + final_df["location"].astype(str)
        )

        changes_df["_key"] = (
            changes_df["province_number"].astype(str)
            + "|"
            + changes_df["registrar_code"].astype(str)
            + "|"
            + changes_df["subdis_code"].astype(str)
            + "|"
            + changes_df["electorate"].astype(str)
            + "|"
            + changes_df["location"].astype(str)
        )

        # Get latest change for each row (by timestamp)
        latest_changes = (
            changes_df.sort_values("timestamp").groupby("_key").last().reset_index()
        )

        # Create attribution lookup
        attribution = {}
        for _, row in latest_changes.iterrows():
            attribution[row["_key"]] = {
                "source_commit": row["commit_hash"],
                "source_author": row["author_name"],
                "source_classification": row["classification"],
                "source_timestamp": row["timestamp"],
            }

        # Apply attribution
        for idx, row in final_df.iterrows():
            key = row["_key"]
            if key in attribution:
                attr = attribution[key]
                final_df.at[idx, "source_commit"] = attr["source_commit"]
                final_df.at[idx, "source_author"] = attr["source_author"]
                final_df.at[idx, "source_classification"] = attr[
                    "source_classification"
                ]
                final_df.at[idx, "source_timestamp"] = attr["source_timestamp"]

        final_df = final_df.drop(columns=["_key"])

    # Save output
    output_path = output_dir / "outputs" / "station66_with_source.parquet"
    final_df.to_parquet(output_path, index=False)
    print(f"Saved {len(final_df)} rows to {output_path}")

    # Print summary
    source_counts = final_df["source_classification"].value_counts()
    print("\nSource attribution summary:")
    for src, count in source_counts.items():
        print(f"  {src}: {count}")

    coords_count = final_df["has_coords"].sum()
    print(
        f"\nRows with coordinates: {coords_count} / {len(final_df)} ({100 * coords_count / len(final_df):.1f}%)"
    )

    return final_df


def main():
    parser = argparse.ArgumentParser(
        description="Extract PR contributions from election-station-66 repository"
    )
    parser.add_argument(
        "--source-repo",
        type=Path,
        default=Path.home() / "ddd" / "ninyawee" / "election-station-66",
        help="Path to the election-station-66 git repository",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent.parent,
        help="Output directory (default: ect69-geo-decoding)",
    )

    args = parser.parse_args()

    # Validate paths
    if not args.source_repo.exists():
        print(f"Error: Source repo not found: {args.source_repo}")
        sys.exit(1)

    print(f"Source repo: {args.source_repo}")
    print(f"Output dir: {args.output_dir}")

    # Ensure output directories exist
    (args.output_dir / "intermediate").mkdir(parents=True, exist_ok=True)
    (args.output_dir / "outputs").mkdir(parents=True, exist_ok=True)

    # Run ETL phases
    commits = phase_a_extract_commits(args.source_repo, args.output_dir)
    changes_df = phase_b_parse_and_classify(args.source_repo, commits, args.output_dir)
    phase_c_build_output(args.source_repo, changes_df, args.output_dir)

    print("\n=== ETL Complete ===")


if __name__ == "__main__":
    main()
