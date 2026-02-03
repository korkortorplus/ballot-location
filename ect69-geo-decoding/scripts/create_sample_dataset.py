"""Create a 300-location sample dataset via diversity sampling.

Uses TF-IDF + K-means clustering on Thai location strings to select
300 maximally diverse polling station locations from the ECT69 raw CSV.
"""

from pathlib import Path

import pandas as pd
from pythainlp.tokenize import word_tokenize
from scipy.sparse import csr_matrix
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_distances
from tqdm import tqdm

INPUT_CSV = Path("ect69-geo-decoding/inputs/ect69-voting-units-20260121.csv")
OUTPUT_PARQUET = Path("ect69-geo-decoding/outputs/sample_300_locations.parquet")
N_CLUSTERS = 300
RANDOM_STATE = 42

LOCATION_COL = "สถานที่เลือกตั้ง"
COLUMNS = [
    "จังหวัด",
    "เขตเลือกตั้ง",
    "อำเภอ",
    "สำนักทะเบียน",
    "ตำบล",
    "หน่วยเลือกตั้ง",
    "สถานที่เลือกตั้ง",
]


def thai_tokenizer(text: str) -> list[str]:
    return word_tokenize(text, engine="newmm")


def main() -> None:
    print(f"Reading {INPUT_CSV}...")
    df = pd.read_csv(INPUT_CSV)
    print(f"  Total rows: {len(df):,}")

    # Strip '#' delimiter from location strings
    df[LOCATION_COL] = df[LOCATION_COL].str.replace("#", "", regex=False).str.strip()

    # Deduplicate on full location string
    df_unique = df.drop_duplicates(subset=[LOCATION_COL]).reset_index(drop=True)
    print(f"  Unique locations: {len(df_unique):,}")

    # Build TF-IDF matrix
    print("Building TF-IDF matrix...")
    vectorizer = TfidfVectorizer(tokenizer=thai_tokenizer, token_pattern=None)
    tfidf_matrix = vectorizer.fit_transform(df_unique[LOCATION_COL])
    print(f"  TF-IDF shape: {tfidf_matrix.shape}")

    # K-means clustering
    print(f"Running K-means (k={N_CLUSTERS})...")
    kmeans = KMeans(
        n_clusters=N_CLUSTERS,
        random_state=RANDOM_STATE,
        n_init=10,
        verbose=0,
    )
    labels = kmeans.fit_predict(tfidf_matrix)

    # For each cluster, pick the row closest to the centroid
    print("Selecting closest-to-centroid samples...")
    centroids = csr_matrix(kmeans.cluster_centers_)
    selected_indices = []

    for cluster_id in tqdm(range(N_CLUSTERS), desc="Clusters"):
        mask = labels == cluster_id
        cluster_indices = df_unique.index[mask].tolist()
        cluster_vectors = tfidf_matrix[mask]

        # Cosine distance from each point to its centroid
        centroid = centroids[cluster_id]
        distances = cosine_distances(cluster_vectors, centroid).flatten()

        # Pick the closest
        best_local_idx = distances.argmin()
        selected_indices.append(cluster_indices[best_local_idx])

    # Build output dataframe
    result = df_unique.loc[selected_indices, COLUMNS].copy()
    result["cluster_id"] = range(N_CLUSTERS)
    result = result.reset_index(drop=True)

    # Save
    OUTPUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(OUTPUT_PARQUET, index=False)
    print(f"\nSaved {len(result)} rows to {OUTPUT_PARQUET}")

    # Quick diversity check
    print(f"\nProvinces covered: {result['จังหวัด'].nunique()}")
    print(f"Districts covered: {result['อำเภอ'].nunique()}")
    print("\nSample locations:")
    for _, row in result.sample(5, random_state=RANDOM_STATE).iterrows():
        print(f"  [{row['จังหวัด']}] {row[LOCATION_COL]}")


if __name__ == "__main__":
    main()
