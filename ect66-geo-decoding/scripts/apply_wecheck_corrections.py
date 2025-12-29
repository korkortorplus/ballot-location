#!/usr/bin/env python3
"""
Apply WeCheck community corrections to ECT66 geocoded dataset.

This script integrates validated community corrections from the WeCheck
platform into the main geocoded voting unit dataset.

Usage:
    # Preview changes without applying
    uv run python scripts/apply_wecheck_corrections.py --dry-run

    # Apply corrections
    uv run python scripts/apply_wecheck_corrections.py
"""

import argparse
import sys
import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, Tuple

import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from geopy.distance import geodesic


def create_backup(input_path: Path, backup_dir: Path) -> Path:
    """
    Create timestamped backup before modifications.

    Args:
        input_path: Path to file to back up
        backup_dir: Directory for backup files

    Returns:
        Path to backup file
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"{input_path.stem}_backup_{timestamp}{input_path.suffix}"
    backup_path = backup_dir / backup_filename

    backup_dir.mkdir(exist_ok=True, parents=True)
    shutil.copy2(input_path, backup_path)

    # Verify backup
    if backup_path.exists():
        original_size = input_path.stat().st_size
        backup_size = backup_path.stat().st_size
        if original_size == backup_size:
            return backup_path
        else:
            raise IOError("Backup verification failed: size mismatch")
    else:
        raise IOError(f"Backup creation failed: {backup_path} not found")


def load_tambon_polygons(shapefile_path: Path) -> gpd.GeoDataFrame:
    """
    Load tambon polygons for validation.

    Args:
        shapefile_path: Path to tambon GeoPackage

    Returns:
        GeoDataFrame with tambon polygons
    """
    tb = gpd.read_file(shapefile_path)
    tb = tb.to_crs(epsg=4326)  # Ensure WGS84

    # Clean column names (remove prefix from tambon name)
    if "TAM_NAM_T" in tb.columns:
        tb["TAM_NAM_T"] = tb["TAM_NAM_T"].str.removeprefix("ต.")

    # Handle duplicates by combining geometries
    import shapely.ops

    tb = (
        tb.groupby(["PROV_NAM_T", "TAM_NAM_T"])
        .agg({"geometry": lambda x: shapely.ops.unary_union(x)})
        .reset_index()
    )

    # Strip whitespace
    tb["PROV_NAM_T"] = tb["PROV_NAM_T"].str.strip()
    tb["TAM_NAM_T"] = tb["TAM_NAM_T"].str.strip()

    return tb


def validate_coordinate(
    lat: float, lng: float, province: str, tambon: str, tambon_gdf: gpd.GeoDataFrame
) -> Dict:
    """
    Validate WeCheck coordinate against Thailand bounds and tambon polygons.

    Args:
        lat: Latitude
        lng: Longitude
        province: Province name (will strip 'จังหวัด' prefix)
        tambon: Tambon/subdistrict name
        tambon_gdf: GeoDataFrame with tambon polygons

    Returns:
        dict with validation results
    """
    warnings = []

    # Thailand bounds check
    if not (5.6 <= lat <= 20.5 and 97.3 <= lng <= 105.6):
        return {
            "is_valid": False,
            "confidence": 0.0,
            "warnings": ["Coordinate outside Thailand bounds"],
            "within_tambon": False,
        }

    # Create point
    point = Point(lng, lat)

    # Find matching tambon polygon
    province_clean = province.replace("จังหวัด", "").strip()
    tambon_clean = tambon.strip()

    tambon_match = tambon_gdf[
        (tambon_gdf["PROV_NAM_T"] == province_clean)
        & (tambon_gdf["TAM_NAM_T"] == tambon_clean)
    ]

    within_tambon = False
    if not tambon_match.empty:
        tambon_poly = tambon_match.iloc[0]["geometry"]
        within_tambon = point.within(tambon_poly)
        if not within_tambon:
            warnings.append("Point outside expected tambon polygon")
    else:
        warnings.append("Tambon polygon not found")

    confidence = 0.9 if within_tambon else 0.7

    return {
        "is_valid": True,
        "confidence": confidence,
        "warnings": warnings,
        "within_tambon": within_tambon,
    }


def calculate_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate distance in kilometers between two coordinates."""
    return geodesic((lat1, lng1), (lat2, lng2)).km


def apply_corrections(args) -> Tuple[pd.DataFrame, Dict]:
    """
    Main correction application logic.

    Args:
        args: Parsed command-line arguments

    Returns:
        Tuple of (corrected_df, report_dict)
    """
    print("=" * 80)
    print("WeCheck Correction Application".center(80))
    print("=" * 80)
    print()

    # Load datasets
    print(f"Loading main dataset: {args.main_dataset}")
    main_df = pd.read_parquet(args.main_dataset)
    print(f"  ✓ Loaded {len(main_df):,} voting units")
    print()

    print(f"Loading WeCheck data: {args.wecheck_input}")
    wecheck_df = pd.read_csv(args.wecheck_input)
    print(f"  ✓ Loaded {len(wecheck_df):,} corrections")
    print()

    # Load tambon polygons for validation
    tambon_path = Path("shapefiles/tambon_DOL_utf8.gpkg")
    print(f"Loading tambon polygons: {tambon_path}")
    tambon_gdf = load_tambon_polygons(tambon_path)
    print(f"  ✓ Loaded {len(tambon_gdf):,} tambon polygons")
    print()

    # Create backup if not dry-run
    if not args.dry_run:
        print("Creating backup...")
        backup_path = create_backup(Path(args.main_dataset), Path(args.backup_dir))
        print(f"  ✓ Backup created: {backup_path}")
        print()
    else:
        print("⚠ DRY RUN MODE: No files will be modified")
        print()

    # Initialize correction tracking
    corrections_applied = []
    corrections_skipped = []
    tier_before = main_df["TierLocation"].value_counts().to_dict()

    # Add new columns if they don't exist
    if "CorrectionSource" not in main_df.columns:
        # Initialize based on existing tier
        main_df["CorrectionSource"] = main_df.apply(
            lambda row: "Google" if row["TierLocation"] == "A+" else "Synthetic", axis=1
        )

    if "UnitNameOriginal" not in main_df.columns:
        main_df["UnitNameOriginal"] = main_df["UnitName"]

    # Filter for validated corrections
    wecheck_valid = wecheck_df[
        (wecheck_df["Edited"])
        & (wecheck_df["UnitId"].notna())
        & (wecheck_df["Latitude"].notna())
        & (wecheck_df["Longitude"].notna())
    ].copy()

    print(f"Processing {len(wecheck_valid)} validated corrections...")
    print()

    # Apply corrections
    for idx, wecheck_row in wecheck_valid.iterrows():
        unit_id = int(wecheck_row["UnitId"])

        # Find matching unit in main dataset
        main_idx = main_df[main_df["UnitId"] == unit_id].index

        if len(main_idx) == 0:
            corrections_skipped.append(
                {"UnitId": unit_id, "reason": "UnitId not found in main dataset"}
            )
            continue

        main_idx = main_idx[0]
        unit_row = main_df.loc[main_idx]

        # Validate coordinate
        validation = validate_coordinate(
            wecheck_row["Latitude"],
            wecheck_row["Longitude"],
            unit_row["ProvinceName"],
            unit_row["SubDistrictName"],
            tambon_gdf,
        )

        if not validation["is_valid"]:
            corrections_skipped.append(
                {
                    "UnitId": unit_id,
                    "reason": f"Validation failed: {', '.join(validation['warnings'])}",
                }
            )
            continue

        # Calculate distance moved
        old_lat = unit_row["Lat"]
        old_lng = unit_row["Lng"]
        new_lat = wecheck_row["Latitude"]
        new_lng = wecheck_row["Longitude"]
        distance_km = calculate_distance(old_lat, old_lng, new_lat, new_lng)

        # Update unit
        if not args.dry_run:
            main_df.loc[main_idx, "Lat"] = new_lat
            main_df.loc[main_idx, "Lng"] = new_lng
            main_df.loc[main_idx, "TierLocation"] = "A+"
            main_df.loc[main_idx, "CorrectionSource"] = "WeCheck"
            main_df.loc[main_idx, "PlaceId"] = ""  # Clear Google Place ID
            main_df.loc[main_idx, "Formatted_Address"] = ""  # Clear Google address

            # Update name if provided
            if pd.notna(wecheck_row.get("ชื่อหน่วยเลือกตั้งที่ถูกต้อง")):
                corrected_name = wecheck_row["ชื่อหน่วยเลือกตั้งที่ถูกต้อง"]
                main_df.loc[main_idx, "UnitName"] = corrected_name
                main_df.loc[main_idx, "DisplayUnitName"] = (
                    f"{unit_row['UnitNumber']} - {corrected_name}"
                )

        # Record correction
        corrections_applied.append(
            {
                "UnitId": unit_id,
                "province": unit_row["ProvinceName"],
                "tambon": unit_row["SubDistrictName"],
                "old_coord": {"lat": old_lat, "lng": old_lng},
                "new_coord": {"lat": new_lat, "lng": new_lng},
                "distance_moved_km": round(distance_km, 2),
                "tier_before": unit_row["TierLocation"],
                "tier_after": "A+",
                "source_before": unit_row.get("CorrectionSource", "Unknown"),
                "source_after": "WeCheck",
                "name_changed": pd.notna(wecheck_row.get("ชื่อหน่วยเลือกตั้งที่ถูกต้อง")),
                "validation": {
                    "passed": validation["is_valid"],
                    "confidence": validation["confidence"],
                    "within_tambon": validation["within_tambon"],
                    "warnings": validation["warnings"],
                },
            }
        )

        print(
            f"  ✓ Corrected UnitId {unit_id} ({unit_row['ProvinceName']}, {unit_row['SubDistrictName']})"
        )
        print(f"    Distance moved: {distance_km:.2f} km")
        print(f"    Tier: {unit_row['TierLocation']} → A+")

    print()

    # Calculate tier changes
    tier_after = (
        main_df["TierLocation"].value_counts().to_dict()
        if not args.dry_run
        else tier_before
    )

    # Prepare report
    report = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "pipeline_version": "2.1.0",
            "script_version": "1.0.0",
            "dry_run": args.dry_run,
            "input_files": {
                "main_dataset": str(args.main_dataset),
                "wecheck_data": str(args.wecheck_input),
            },
        },
        "summary": {
            "total_wecheck_rows": len(wecheck_df),
            "validated_ready": len(wecheck_valid),
            "applied": len(corrections_applied),
            "skipped": len(corrections_skipped),
            "pending_geocoding": len(
                wecheck_df[
                    (wecheck_df["ชื่อหน่วยเลือกตั้งที่ถูกต้อง"].notna())
                    & (wecheck_df["Latitude"].isna() | wecheck_df["Longitude"].isna())
                ]
            ),
        },
        "tier_changes": {
            "D_to_A_plus": sum(
                1 for c in corrections_applied if c["tier_before"] == "D"
            ),
            "A_plus_improved": sum(
                1 for c in corrections_applied if c["tier_before"] == "A+"
            ),
        },
        "quality_metrics": {
            "before": {k: int(v) for k, v in tier_before.items()},
            "after": {k: int(v) for k, v in tier_after.items()},
            "improvement_pct": round((len(corrections_applied) / len(main_df)) * 100, 3)
            if len(corrections_applied) > 0
            else 0,
        },
        "corrections_applied": corrections_applied,
        "corrections_skipped": corrections_skipped,
    }

    return main_df, report


def generate_reports(report: Dict, report_dir: Path, dry_run: bool):
    """Generate human-readable and machine-readable reports."""
    report_dir = Path(report_dir)
    report_dir.mkdir(exist_ok=True, parents=True)

    # JSON report
    json_path = report_dir / "wecheck_correction_report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"✓ JSON report saved: {json_path}")

    # Text report
    txt_path = report_dir / "wecheck_correction_report.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write("WeCheck Correction Report".center(80) + "\n")
        f.write("=" * 80 + "\n")
        f.write(f"Generated: {report['metadata']['generated_at']}\n")
        f.write(f"Pipeline Version: {report['metadata']['pipeline_version']}\n")
        f.write(f"Script Version: {report['metadata']['script_version']}\n")
        if dry_run:
            f.write("\n⚠ DRY RUN MODE - No changes applied\n")
        f.write("\n")

        f.write("SUMMARY\n")
        f.write("-" * 80 + "\n")
        f.write(
            f"Total WeCheck corrections in file: {report['summary']['total_wecheck_rows']:,}\n"
        )
        f.write(
            f"  ✓ Validated (ready to apply):  {report['summary']['validated_ready']}\n"
        )
        f.write(f"  ✓ Applied:                      {report['summary']['applied']}\n")
        f.write(f"  ✗ Skipped:                      {report['summary']['skipped']}\n")
        f.write(
            f"  ⧗ Pending (needs geocoding):   {report['summary']['pending_geocoding']}\n"
        )
        f.write("\n")

        f.write("TIER CHANGES\n")
        f.write("-" * 80 + "\n")
        f.write(
            f"Tier D → A+ (Community):  {report['tier_changes']['D_to_A_plus']} units\n"
        )
        f.write(
            f"Tier A+ improved:          {report['tier_changes']['A_plus_improved']} units\n"
        )
        f.write("\n")

        if report["corrections_applied"]:
            f.write("CORRECTIONS APPLIED\n")
            f.write("-" * 80 + "\n")
            for corr in report["corrections_applied"]:
                f.write(
                    f"  UnitId {corr['UnitId']}: {corr['province']}, {corr['tambon']}\n"
                )
                f.write(
                    f"    Old: ({corr['old_coord']['lat']}, {corr['old_coord']['lng']}) [{corr['tier_before']}, {corr['source_before']}]\n"
                )
                f.write(
                    f"    New: ({corr['new_coord']['lat']}, {corr['new_coord']['lng']}) [{corr['tier_after']}, {corr['source_after']}]\n"
                )
                f.write(f"    Distance moved: {corr['distance_moved_km']} km\n")
                f.write(
                    f"    Name changed: {'YES' if corr['name_changed'] else 'NO'}\n"
                )
                f.write(
                    f"    Validation: {corr['validation']['confidence'] * 100:.0f}% confidence, within tambon: {corr['validation']['within_tambon']}\n"
                )
                f.write("\n")

        f.write("DATASET QUALITY IMPACT\n")
        f.write("-" * 80 + "\n")
        before = report["quality_metrics"]["before"]
        after = report["quality_metrics"]["after"]
        total = sum(after.values())
        f.write("Before corrections:\n")
        for tier, count in sorted(before.items()):
            pct = (count / total) * 100
            f.write(f"  Tier {tier}: {count:,} units ({pct:.1f}%)\n")
        f.write(f"  Total:   {total:,} units\n\n")

        f.write("After corrections:\n")
        for tier, count in sorted(after.items()):
            pct = (count / total) * 100
            f.write(f"  Tier {tier}: {count:,} units ({pct:.1f}%)\n")
        f.write(f"  Total:   {total:,} units\n\n")

        f.write(
            f"Quality improvement: +{report['quality_metrics']['improvement_pct']:.3f}%\n"
        )
        f.write("\n")

        if report["summary"]["pending_geocoding"] > 0:
            f.write("PENDING WORK\n")
            f.write("-" * 80 + "\n")
            f.write(
                f"{report['summary']['pending_geocoding']} corrections have names but no coordinates.\n\n"
            )
            f.write("Recommendation: Re-geocode using corrected names\n")
            f.write("  1. Extract corrected names\n")
            f.write("  2. Run through Google Maps API (reuse batch_geocode.py)\n")
            f.write("  3. Apply spatial validation\n")
            f.write(
                f"  Estimated cost: ${report['summary']['pending_geocoding'] * 0.005:.2f}\n"
            )
            f.write("\n")

        f.write("=" * 80 + "\n")

    print(f"✓ Text report saved: {txt_path}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Apply WeCheck community corrections to ECT66 dataset",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview changes without applying
  uv run python scripts/apply_wecheck_corrections.py --dry-run

  # Apply corrections
  uv run python scripts/apply_wecheck_corrections.py
        """,
    )

    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without modifying files"
    )

    parser.add_argument(
        "--main-dataset",
        type=str,
        default="outputs/ect66_geocoded_validated.parquet",
        help="Path to main geocoded dataset",
    )

    parser.add_argument(
        "--wecheck-input",
        type=str,
        default="inputs/wecheck_corrections.csv",
        help="Path to WeCheck corrections CSV",
    )

    parser.add_argument(
        "--backup-dir",
        type=str,
        default="outputs/backups",
        help="Directory for backup files",
    )

    parser.add_argument(
        "--report-dir",
        type=str,
        default="outputs",
        help="Directory for correction reports",
    )

    args = parser.parse_args()

    # Validate input files exist
    if not Path(args.main_dataset).exists():
        print(f"ERROR: Main dataset not found: {args.main_dataset}")
        sys.exit(1)

    if not Path(args.wecheck_input).exists():
        print(f"ERROR: WeCheck file not found: {args.wecheck_input}")
        print("Run: uv run python scripts/clean_wecheck_data.py")
        sys.exit(1)

    # Apply corrections
    corrected_df, report = apply_corrections(args)

    # Generate reports
    print()
    print("Generating reports...")
    generate_reports(report, Path(args.report_dir), args.dry_run)
    print()

    # Save corrected dataset
    if not args.dry_run and report["summary"]["applied"] > 0:
        print(f"Saving corrected dataset: {args.main_dataset}")
        corrected_df.to_parquet(args.main_dataset, index=False)
        print("  ✓ Dataset updated")
        print()

    # Summary
    print("=" * 80)
    if args.dry_run:
        print("✓ Dry run complete! Review reports and run without --dry-run to apply.")
    else:
        print("✓ Corrections applied successfully!")
        print(f"  {report['summary']['applied']} units corrected")
        print(f"  {report['summary']['skipped']} skipped")
    print("=" * 80)


if __name__ == "__main__":
    main()
