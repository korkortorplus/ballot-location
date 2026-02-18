"""Load spatial reference data into PostGIS.

Tables populated:
  - ref.electoral_district  (from 2569 shapefile)
  - ref.admin_boundary      (level 1: province, level 2: amphoe, level 3: tambon + BMA)
    with parent_id hierarchy and ltree path column

Data sources (3 different providers, hence the name-matching headaches):
  - Province (level 1): OCHA tha_admin_boundaries.geojson.zip → tha_admin1.geojson
  - Amphoe   (level 2): OCHA tha_admin2.geojson (standalone copy)
  - Tambon   (level 3): DOL tambon_DOL_utf8.gpkg + BMA BMA_ADMIN_SUB_DISTRICT.gpkg

Province and amphoe share OCHA pcodes (TH10, TH1001) so they join cleanly.
Tambon has no pcodes — we join by matching Thai province + amphoe names,
which requires fixing 21 misspelled/outdated names (see AMPHOE_NAME_FIXES).

The load runs in two phases:
  Phase 1: Insert all rows via to_postgis (province → amphoe → tambon+BMA).
  Phase 2: ALTER TABLE to add id/path/parent_id columns that to_postgis can't
           create, then UPDATE to wire up the hierarchy via SQL joins.

After loading:
  - 77 provinces, 928 amphoe, ~7796 tambon (1 null-name DOL placeholder has no parent)
  - ltree paths: TH10 → TH10.TH1001 → TH10.TH1001.t_<row_id>

Usage:
  fnox exec -- uv run python ect69-geo-decoding/scripts/load_ref_geodata_to_postgis.py
"""

import os

import geopandas as gpd
import pandas as pd
from sqlalchemy import create_engine, text

PASSWORD = os.environ["POSTGIS_PASSWORD"]
ENGINE = create_engine(f"postgresql://postgres:{PASSWORD}@localhost:5433/postgres")

# -- Paths --
CONSTITUENCIES_SHP = "/home/ben/ddd/ninyawee/Thai-ECT-election-map/ECT Constituencies/2569/ShapeFile/2569_Election_Constituencies.shp"
TAMBON_GPKG = "/home/ben/ddd/ninyawee/ballot-location/ect66-geo-decoding/shapefiles/tambon_DOL_utf8.gpkg"  # DOL = Department of Lands
BMA_GPKG = "/home/ben/ddd/ninyawee/ballot-location/ect66-geo-decoding/shapefiles/BMA_ADMIN_SUB_DISTRICT.gpkg"  # BMA = Bangkok Metropolitan Administration
AMPHOE_GEOJSON = "/home/ben/ddd/ninyawee/landmap/web/static/data/tha_admin2.geojson"  # OCHA admin level 2
PROVINCE_GEOJSON_ZIP = "/home/ben/ddd/ninyawee/landmap/web/static/data/tha_admin_boundaries.geojson.zip"  # OCHA admin level 1 (inside zip)

# The DOL tambon shapefile uses old/misspelled amphoe names that don't match
# the OCHA tha_admin2.geojson reference. This dict maps (province, wrong) → correct.
# Each entry is annotated with the reason for the mismatch.
AMPHOE_NAME_FIXES: dict[tuple[str, str], str] = {
    # --- Renamed when promoted from กิ่งอำเภอ to อำเภอ ---
    ("กาฬสินธุ์", "ฆ้องชัยพัฒนา"): "ฆ้องชัย",  # renamed 2007
    # --- Truncated names (DOL data cut short) ---
    ("ขอนแก่น", "บ้านแฮ"): "บ้านแฮด",
    ("ขอนแก่น", "หนองนา"): "หนองนาคำ",
    ("ขอนแก่น", "โคกโพธิ์"): "โคกโพธิ์ไชย",
    ("อุดรธานี", "ประจักษ์"): "ประจักษ์ศิลปาคม",
    ("ศรีสะเกษ", "เมืองศรีเกษ"): "เมืองศรีสะเกษ",
    # --- Short "เมือง" without province suffix ---
    ("นครราชสีมา", "เมือง"): "เมืองนครราชสีมา",
    ("ปทุมธานี", "เมือง"): "เมืองปทุมธานี",
    # --- OCHA uses short form without เมือง prefix ---
    ("นครศรีธรรมราช", "เมืองนครศรีธรรมราช"): "นครศรีธรรมราช",
    # --- Thai spelling errors (wrong vowels / consonants) ---
    ("กาฬสินธุ์", "เมืองกาฬสินธ์"): "เมืองกาฬสินธุ์",  # missing ุ์
    ("นครราชสีมา", "หนองบุนนาก"): "หนองบุญมาก",  # บุน→บุญ, นาก→มาก
    ("นครราชสีมา", "เทพารัษ์"): "เทพารักษ์",  # รัษ์→รักษ์
    ("พัทลุง", "ป่าพยอม"): "ป่าพะยอม",  # พยอม→พะยอม
    ("พิจิตร", "สะพานหิน"): "ตะพานหิน",  # สะ→ตะ
    ("มุกดาหาร", "ว่านใหญ่"): "หว้านใหญ่",  # ว่าน→หว้าน
    ("ยะลา", "กรงปีนัง"): "กรงปินัง",  # ปีนัง→ปินัง
    ("สงขลา", "บางกลำ่"): "บางกล่ำ",  # swapped vowel/tone position
    ("สงขลา", "หาดให่ญ"): "หาดใหญ่",  # ให่ญ→ใหญ่
    # --- Typo in prefix (กื่ง instead of กิ่ง) so regex didn't strip it ---
    ("สระแก้ว", "กื่ง อ.วังสมบูรณ์"): "วังสมบูรณ์",
    # --- Garbled/swapped syllables ---
    ("สุราษฎร์ธานี", "บ้านขุนตาล"): "บ้านตาขุน",  # ขุนตาล→ตาขุน
    # --- Wrong amphoe entirely (source data error) ---
    # ต.นาม่วง was listed under บึงสามัคคี (กำแพงเพชร amphoe) but actually
    # belongs to ประจักษ์ศิลปาคม per Wikipedia and official records.
    ("อุดรธานี", "บึงสามัคคี"): "ประจักษ์ศิลปาคม",
}


def load_electoral_districts():
    print("Loading electoral districts...")
    gdf = gpd.read_file(CONSTITUENCIES_SHP)
    gdf = gdf.to_crs(epsg=4326)

    # Normalize to MultiPolygon
    gdf["geometry"] = gdf["geometry"].apply(
        lambda g: g
        if g.geom_type == "MultiPolygon"
        else g.buffer(0)
        if g is None
        else g
        if g.geom_type == "MultiPolygon"
        else gpd.GeoSeries([g]).unary_union
    )

    # Map columns: P_name -> province_name, CONS_no -> district_number
    out = gpd.GeoDataFrame(geometry=gdf.geometry)
    out["province_name"] = gdf["P_name"]
    out["district_number"] = gdf["CONS_no"].astype(int)

    out = out.rename_geometry("geom")
    out.to_postgis(
        "electoral_district", ENGINE, schema="ref", if_exists="replace", index=False
    )
    print(f"  Loaded {len(out)} electoral districts")


def load_admin_boundaries():
    # =========================================================================
    # Phase 1: Load all three levels into the table
    # =========================================================================

    # -- Province (level 1) --
    print("Loading province (level-1) boundaries from zip...")
    province = gpd.read_file(f"zip://{PROVINCE_GEOJSON_ZIP}!tha_admin1.geojson")
    province = province.to_crs(epsg=4326)
    print(f"  Province columns: {province.columns.tolist()}")

    province_out = gpd.GeoDataFrame(geometry=province.geometry)
    province_out["admin_level"] = 1
    province_out["name_th"] = province["adm1_name1"]
    province_out["name_en"] = province["adm1_name"]
    province_out["parent_id"] = None
    province_out["path"] = None  # will be set in phase 2
    # Temp columns used in phase 2 SQL joins, then dropped.
    # All 3 levels must have the same columns because to_postgis(append) requires it.
    province_out["adm1_pcode"] = province["adm1_pcode"]  # e.g. "TH10"
    province_out["adm2_pcode"] = None
    province_out["_prov_name"] = None
    province_out["_amphoe_name"] = None
    province_out = province_out.rename_geometry("geom")

    # Write provinces first (replace table)
    province_out.to_postgis(
        "admin_boundary", ENGINE, schema="ref", if_exists="replace", index=False
    )
    print(f"  Loaded {len(province_out)} level-1 province boundaries")

    # -- Amphoe (level 2) --
    print("Loading amphoe (level-2) boundaries...")
    amphoe = gpd.read_file(AMPHOE_GEOJSON)
    amphoe = amphoe.to_crs(epsg=4326)
    print(f"  Amphoe columns: {amphoe.columns.tolist()}")

    amphoe_out = gpd.GeoDataFrame(geometry=amphoe.geometry)
    amphoe_out["admin_level"] = 2
    amphoe_out["name_th"] = amphoe["adm2_name1"]
    amphoe_out["name_en"] = amphoe["adm2_name"]
    amphoe_out["parent_id"] = None  # will be set in phase 2
    amphoe_out["path"] = None
    amphoe_out["adm1_pcode"] = amphoe["adm1_pcode"]  # e.g. "TH10" — joins to province
    amphoe_out["adm2_pcode"] = amphoe[
        "adm2_pcode"
    ]  # e.g. "TH1001" — becomes part of ltree path
    amphoe_out["_prov_name"] = None
    amphoe_out["_amphoe_name"] = None
    amphoe_out = amphoe_out.rename_geometry("geom")

    amphoe_out.to_postgis(
        "admin_boundary", ENGINE, schema="ref", if_exists="append", index=False
    )
    print(f"  Appended {len(amphoe_out)} level-2 amphoe boundaries")

    # -- Tambon (level 3) --
    print("Loading tambon boundaries...")
    tambon = gpd.read_file(TAMBON_GPKG)
    tambon = tambon.to_crs(epsg=4326)
    print(f"  Tambon columns: {tambon.columns.tolist()}")

    tambon_out = gpd.GeoDataFrame(geometry=tambon.geometry)
    tambon_out["admin_level"] = 3
    tambon_out["name_th"] = tambon["TAM_NAM_T"]
    tambon_out["name_en"] = None
    tambon_out["parent_id"] = None
    tambon_out["path"] = None
    tambon_out["adm1_pcode"] = None  # DOL tambon has no OCHA pcode
    tambon_out["adm2_pcode"] = None
    # DOL uses Thai province name (no prefix) and amphoe name with อ./กิ่ง อ. prefix.
    # We strip the prefix so it matches OCHA's adm2_name1 (plain amphoe name).
    tambon_out["_prov_name"] = tambon["PROV_NAM_T"]
    tambon_out["_amphoe_name"] = tambon["AMPHOE_T"].str.replace(
        r"^(กิ่ง อ\.|อ\.)\s*", "", regex=True
    )
    # Apply hand-verified name fixes for old/misspelled amphoe names.
    # Without these, ~170 tambon rows fail to join to an amphoe parent.
    for (prov, wrong), correct in AMPHOE_NAME_FIXES.items():
        mask = (tambon_out["_prov_name"] == prov) & (
            tambon_out["_amphoe_name"] == wrong
        )
        tambon_out.loc[mask, "_amphoe_name"] = correct
    tambon_out = tambon_out.rename_geometry("geom")

    print("Loading BMA sub-district boundaries...")
    bma = gpd.read_file(BMA_GPKG)
    bma = bma.to_crs(epsg=4326)
    print(f"  BMA columns: {bma.columns.tolist()}")

    bma_out = gpd.GeoDataFrame(geometry=bma.geometry)
    bma_out["admin_level"] = 3
    # BMA column names are misleading: SUBDISTRIC is a numeric code (e.g. "100608"),
    # SUBDISTR_1 is the actual Thai name (e.g. "หัวหมาก").
    bma_out["name_th"] = bma["SUBDISTR_1"]
    bma_out["name_en"] = None
    bma_out["parent_id"] = None
    bma_out["path"] = None
    bma_out["adm1_pcode"] = None
    bma_out["adm2_pcode"] = None
    # BMA rows have _prov_name=None to distinguish them from DOL tambon in phase 2.
    # They join to amphoe by _amphoe_name (district) within Bangkok (adm1_pcode=TH10).
    bma_out["_prov_name"] = None
    # Fix truncated/misspelled BMA district names to match OCHA amphoe names
    bma_out["_amphoe_name"] = bma["DISTRICT_N"].replace(
        {
            "ป้อมปราบศัต": "ป้อมปราบศัตรูพ่าย",  # truncated
            "บึ่งกุ่ม": "บึงกุ่ม",  # typo บึ่ง→บึง
        }
    )
    bma_out = bma_out.rename_geometry("geom")

    # Combine tambon + BMA
    level3 = pd.concat([tambon_out, bma_out], ignore_index=True)
    level3 = gpd.GeoDataFrame(level3, geometry="geom", crs="EPSG:4326")

    level3.to_postgis(
        "admin_boundary", ENGINE, schema="ref", if_exists="append", index=False
    )
    print(f"  Appended {len(level3)} level-3 admin boundaries")

    # =========================================================================
    # Phase 2: Set up ltree extension, path column, parent_id, and indexes
    # =========================================================================
    # Phase 2 fixes up the schema that to_postgis couldn't create:
    # - to_postgis creates columns from DataFrame dtypes, so parent_id/path are TEXT
    # - There's no id SERIAL PRIMARY KEY (not in the DataFrame)
    # We ALTER TABLE to add proper types, then UPDATE to set values via SQL joins.
    print("Setting up id column, ltree extension, and path column...")
    with ENGINE.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS ltree"))

        # id: to_postgis doesn't create auto-increment PKs
        conn.execute(
            text("""
            ALTER TABLE ref.admin_boundary
            ADD COLUMN id SERIAL PRIMARY KEY
        """)
        )

        # parent_id: to_postgis wrote it as TEXT (all nulls), re-create as INT FK
        conn.execute(
            text("""
            ALTER TABLE ref.admin_boundary
            DROP COLUMN parent_id
        """)
        )
        conn.execute(
            text("""
            ALTER TABLE ref.admin_boundary
            ADD COLUMN parent_id INT REFERENCES ref.admin_boundary(id)
        """)
        )

        # path: to_postgis wrote it as TEXT, re-create as LTREE
        conn.execute(
            text("""
            ALTER TABLE ref.admin_boundary
            DROP COLUMN IF EXISTS path
        """)
        )
        conn.execute(
            text("""
            ALTER TABLE ref.admin_boundary
            ADD COLUMN path LTREE
        """)
        )

        # --- Province paths: e.g. TH10 ---
        print("  Setting province paths...")
        conn.execute(
            text("""
            UPDATE ref.admin_boundary
            SET path = adm1_pcode::ltree
            WHERE admin_level = 1 AND adm1_pcode IS NOT NULL
        """)
        )

        # --- Amphoe parent_id + paths: e.g. TH10.TH1001 ---
        # Joins on adm1_pcode (both province and amphoe have it from OCHA).
        print("  Setting amphoe parent_id and paths...")
        conn.execute(
            text("""
            UPDATE ref.admin_boundary a
            SET parent_id = p.id,
                path = (p.adm1_pcode || '.' || a.adm2_pcode)::ltree
            FROM ref.admin_boundary p
            WHERE a.admin_level = 2
              AND p.admin_level = 1
              AND a.adm1_pcode = p.adm1_pcode
        """)
        )

        # --- Tambon parent_id + paths (non-BMA): e.g. TH10.TH1001.t_42 ---
        # DOL tambon has no pcodes, so we join by Thai name:
        #   tambon._prov_name  = province.name_th   (both Thai, no prefix)
        #   tambon._amphoe_name = amphoe.name_th    (after stripping อ./กิ่ง อ. + fixes)
        # The t_<id> suffix uses the auto-generated row id since tambon has no pcode.
        print("  Setting tambon parent_id and paths...")
        conn.execute(
            text("""
            UPDATE ref.admin_boundary t
            SET parent_id = a.id,
                path = (a.path::text || '.t_' || t.id::text)::ltree
            FROM ref.admin_boundary a
            JOIN ref.admin_boundary p ON a.parent_id = p.id AND p.admin_level = 1
            WHERE t.admin_level = 3
              AND a.admin_level = 2
              AND t._prov_name IS NOT NULL
              AND t._prov_name = p.name_th
              AND t._amphoe_name = a.name_th
        """)
        )

        # --- BMA sub-districts parent_id + paths ---
        # BMA sub-districts are separate from DOL tambon (BMA covers Bangkok only).
        # They have _prov_name=NULL (distinguishes from DOL rows) and join by
        # _amphoe_name = DISTRICT_N (BMA district) matching amphoe.name_th,
        # restricted to Bangkok province (adm1_pcode='TH10').
        print("  Setting BMA sub-district parent_id and paths...")
        conn.execute(
            text("""
            UPDATE ref.admin_boundary t
            SET parent_id = a.id,
                path = (a.path::text || '.t_' || t.id::text)::ltree
            FROM ref.admin_boundary a
            WHERE t.admin_level = 3
              AND a.admin_level = 2
              AND t._prov_name IS NULL
              AND t._amphoe_name IS NOT NULL
              AND t._amphoe_name = a.name_th
              AND a.parent_id IN (
                  SELECT id FROM ref.admin_boundary
                  WHERE admin_level = 1 AND adm1_pcode = 'TH10'
              )
        """)
        )

        # --- Drop temporary columns used only for joining ---
        print("  Dropping temporary columns...")
        for col in ["adm1_pcode", "adm2_pcode", "_prov_name", "_amphoe_name"]:
            conn.execute(
                text(f"ALTER TABLE ref.admin_boundary DROP COLUMN IF EXISTS {col}")
            )

        # --- Create indexes ---
        print("  Creating indexes...")
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_admin_boundary_geom
            ON ref.admin_boundary USING GIST(geom)
        """)
        )
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_admin_boundary_level_name
            ON ref.admin_boundary(admin_level, name_th)
        """)
        )
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_admin_boundary_path
            ON ref.admin_boundary USING GIST(path)
        """)
        )

    # --- Verification ---
    print("\nVerification:")
    with ENGINE.connect() as conn:
        result = conn.execute(
            text("""
            SELECT admin_level, count(*),
                   count(parent_id) AS has_parent,
                   count(path) AS has_path
            FROM ref.admin_boundary
            GROUP BY admin_level
            ORDER BY admin_level
        """)
        )
        for row in result:
            print(
                f"  Level {row[0]}: {row[1]} rows, {row[2]} with parent_id, {row[3]} with path"
            )

        # 1 orphan expected: the null-name Bangkok placeholder row from DOL data
        orphans = conn.execute(
            text("""
            SELECT count(*) FROM ref.admin_boundary
            WHERE admin_level = 3 AND parent_id IS NULL
        """)
        ).scalar()
        if orphans:
            print(f"  WARNING: {orphans} level-3 rows without parent_id")

        # --- Spatial containment: amphoe centroid within province ---
        # All amphoe centroids should fall inside their parent province.
        # Coastal amphoe (islands) may be a few km off due to OCHA coastline
        # clipping, so we only flag those >5 km away.
        amphoe_outside = conn.execute(
            text("""
            SELECT a.name_th, p.name_th AS province,
                   ST_Distance(ST_Centroid(a.geom)::geography, p.geom::geography)::int AS dist_m
            FROM ref.admin_boundary a
            JOIN ref.admin_boundary p ON a.parent_id = p.id
            WHERE a.admin_level = 2
              AND NOT ST_Intersects(ST_Centroid(a.geom), p.geom)
              AND ST_Distance(ST_Centroid(a.geom)::geography, p.geom::geography) > 5000
        """)
        ).fetchall()
        if amphoe_outside:
            names = [f"{r[0]} ({r[1]}, {r[2]}m)" for r in amphoe_outside]
            raise AssertionError(
                f"{len(amphoe_outside)} amphoe centroids >5 km outside province: {names}"
            )
        print("  OK: all amphoe centroids within province (5 km tolerance)")

        # --- Spatial containment: tambon centroid within province ---
        # DOL tambon polygons for islands extend into the sea beyond OCHA province
        # coastlines. We only flag tambon >50 km away to catch truly wrong
        # assignments, not coastline clipping artifacts.
        tambon_far_outside = conn.execute(
            text("""
            SELECT t.name_th, p.name_th AS province,
                   ST_Distance(ST_Centroid(t.geom)::geography, p.geom::geography)::int AS dist_m
            FROM ref.admin_boundary t
            JOIN ref.admin_boundary p ON p.admin_level = 1 AND t.path <@ p.path
            WHERE t.admin_level = 3
              AND NOT ST_Intersects(ST_Centroid(t.geom), p.geom)
              AND ST_Distance(ST_Centroid(t.geom)::geography, p.geom::geography) > 50000
        """)
        ).fetchall()
        if tambon_far_outside:
            names = [f"{r[0]} ({r[1]}, {r[2]}m)" for r in tambon_far_outside]
            raise AssertionError(
                f"{len(tambon_far_outside)} tambon centroids >50 km outside province: {names}"
            )
        print("  OK: all tambon centroids within province (50 km tolerance)")


if __name__ == "__main__":
    # Verify connection
    with ENGINE.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("Connected to PostGIS")

    load_electoral_districts()
    load_admin_boundaries()
    print("Done.")
