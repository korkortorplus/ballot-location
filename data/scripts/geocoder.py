import pandas as pd
import os
import googlemaps
from tqdm import tqdm
from dotenv import load_dotenv
import joblib

load_dotenv()

tqdm.pandas(desc="Geocoding..")


apikey = os.getenv("GMAP_API_KEY")
assert apikey is not None, "Please set GMAP_API_KEY in .env file"

gmaps = googlemaps.Client(key=apikey)


cache = joblib.Memory(".cache", verbose=0)


@cache.cache
def geocode(street_address, subdistrict, district=None, province=None, country="TH"):
    # components = {'administrative_area_level_1': province, 'sublocality_level_1': district, 'sublocality_level_2': subdistrict, 'country': country}
    # # remove None values
    # components = {k: v for k, v in components.items() if v is not None}

    components = {"sublocality_level_2": subdistrict, "country": country}
    if district is not None:
        components["sublocality_level_1"] = district
    if province is not None:
        components["administrative_area_level_1"] = province

    return gmaps.geocode(street_address, language="th", components=components)


df = pd.read_parquet("data/ect/ect.parquet")

df["GMap"] = dict()


def run_batch1():
    """
    apply to first 1000 rows
    """

    df.loc[df.index[:1000], "GMap"] = df.iloc[:1000].progress_apply(
        lambda x: geocode(
            street_address=x["UnitName"],
            subdistrict=x["SubDistrictName"],
            province=x["ProvinceName"],
        ),
        axis=1,
    )


def run_batch2():
    """
    apply to first 10000 rows
    """
    df.loc[df.index[1000:10000], "GMap"] = df.iloc[1000:10000].progress_apply(
        lambda x: geocode(
            street_address=x["UnitName"],
            subdistrict=x["SubDistrictName"],
            province=x["ProvinceName"],
        ),
        axis=1,
    )


def run_batch3():
    """
    apply to the rest
    """
    df.loc[df.index[10000:], "GMap"] = df.iloc[10000:].progress_apply(
        lambda x: geocode(
            street_address=x["UnitName"],
            subdistrict=x["SubDistrictName"],
            province=x["ProvinceName"],
        ),
        axis=1,
    )


if __name__ == "__main__":
    run_batch1()
    df.to_csv("data/ect/ect_batch_1.csv")
    df.to_parquet("data/ect/ect_batch_1.parquet")
    df.to_pickle("data/ect/ect_batch_1.pkl")
    input("Press Enter to continue...")
    run_batch2()
    df.to_csv("data/ect/ect_batch_2.csv")
    df.to_parquet("data/ect/ect_batch_2.parquet")
    df.to_pickle("data/ect/ect_batch_2.pkl")
    input("Press Enter to continue...")
    run_batch3()
    df.to_csv("data/ect/ect_batch_3.csv")
    df.to_parquet("data/ect/ect_batch_3.parquet")
    df.to_pickle("data/ect/ect_batch_3.pkl")
    input("Press Enter to continue...")
