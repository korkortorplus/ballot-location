# https://coda.io/d/Coda-for-Product-Managers_dzzTV9e3Peb/We-Check-Map-Data-Structures_suANd

from calendar import c
from datetime import datetime
import random
from typing import Literal, Optional, List
from enum import Enum, auto
from autoname import AutoName, AutoNameLower
from pydantic import BaseModel, Json
import httpx
from fastapi_utils.api_model import APIModel
from pyrsistent import b
from furl import furl
from shapely.geometry import Point, Polygon
import geopandas as gpd
import pandas as pd

morning_end = datetime.fromisoformat("2023-05-14T09:00:00+07:00")
evening_start = datetime.fromisoformat("2023-05-14T17:00:00+07:00")
evening_end = datetime.fromisoformat("2023-05-14T20:00:00+07:00")


class UnitColor(AutoNameLower):
    Gray = auto()
    Red = auto()
    Green = auto()


def create_google_url(latlng: tuple[float, float], placeId: str = "") -> str:
    f = furl("https://www.google.com/maps/search/")
    f.args["api"] = 1
    f.args["query"] = f"{latlng[0]},{latlng[1]}"
    if placeId != "":
        f.args["query_place_id"] = placeId
    return f.url


class UnitData(APIModel):
    unit_id: int
    unit_name: str
    province_name: str
    division_number: int
    district_name: str
    sub_district_name: str
    unit_number: int

    color: UnitColor = UnitColor.Red

    latitude: float
    longitude: float
    google_map_url: str
    tier_location: str

    isObservationValid: bool = False
    last_observed_time: Optional[datetime] = None
    incident_count: int = 0
    incident_str: str = (
        ""  # Example "[ "เปิดหน่วยเลือกตั้งช้า", "จนท คุกคามผู้ใช้สิทธิ์" ]"
    )

    def get_geojson(self):
        return {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [self.longitude, self.latitude],
            },
            "properties": self.dict(by_alias=True),
        }


import asyncio
import httpx
import os
from typing import List
from pandas import read_pickle
from dotenv import load_dotenv
from tqdm import tqdm
from uuid import uuid4
from furl import furl


class VA_Elect_API:
    api_key: str
    default_collection_id: str = "645ba137f1b89d8b8f1c5f09"

    def create_client(self):
        self.timeout = httpx.Timeout(600.0, connect=600.0)
        self.client = httpx.AsyncClient(timeout=self.timeout)

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

        self.create_client()

    async def _create(self, geojson: dict, collection_id=None) -> httpx.Response:
        if collection_id is None:
            collection_id = self.default_collection_id

        reqUrl = f"https://b-2.i-bitz.world/core/api/features/1.0-beta/collections/{collection_id}/items?api_key={self.api_key}"

        req_id = uuid4()

        print(
            f"{str(req_id)[-6:]}: Making POST request with {len(geojson['features'])} units"
        )
        data = await self.client.post(reqUrl, json=geojson)
        print(f"{str(req_id)[-6:]}: done")
        return data

    async def create(self, units: List[UnitData]):
        geojson = {
            "type": "FeatureCollection",
            "features": [unit.get_geojson() for unit in units],
        }

        response = await self._create(geojson)

        return response.json()

    async def _update(
        self, obj_id: str, geojson: dict, collection_id=None
    ) -> httpx.Response:
        if collection_id is None:
            collection_id = self.default_collection_id

        reqUrl = f"https://b-2.i-bitz.world/core/api/features/1.0-beta/collections/{collection_id}/items/{obj_id}?api_key={self.api_key}"

        req_id = uuid4()

        print(
            f"{str(req_id)[-6:]}: Making PUT request with {len(geojson['features'])} units"
        )
        data = await self.client.put(reqUrl, json=geojson)
        print(f"{str(req_id)[-6:]}: done")
        return data

    async def update(self, obj_id: str, units: List[UnitData]):
        geojson = {
            "type": "FeatureCollection",
            "features": [unit.get_geojson() for unit in units],
        }
        response = await self._update(obj_id, geojson)

        return response.json()

    async def _delete_all(self, collection_id=None) -> httpx.Response:
        if collection_id is None:
            collection_id = self.default_collection_id

        reqUrl = f"https://b-2.i-bitz.world/core/api/features/1.0-beta/collections/{collection_id}/items?api_key={self.api_key}"

        data = await self.client.delete(reqUrl)
        return data

    async def delete_all(self):
        response = await self._delete_all()
        return response

    async def _get_one(self, obj_id: str, collection_id=None) -> httpx.Response:
        if collection_id is None:
            collection_id = self.default_collection_id

        reqUrl = f"https://b-2.i-bitz.world/core/api/features/1.0-beta/collections/{collection_id}/items/{obj_id}?api_key={self.api_key}"

        data = await self.client.get(reqUrl)
        return data

    async def get_one(self, obj_id: str):
        response = await self._get_one(obj_id)
        return response.json()

    async def _get_many(
        self,
        properties: dict,
        collection_id=None,
    ) -> httpx.Response:
        if collection_id is None:
            collection_id = self.default_collection_id

        reqUrl = f"https://b-2.i-bitz.world/core/api/features/1.0/collections/{collection_id}/items?api_key={self.api_key}"
        reqUrl = furl(reqUrl).add(properties).url
        data = await self.client.get(reqUrl)
        return data

    async def get_many(self, properties: dict):
        response = await self._get_many(properties)
        return response.json()

    async def _edit_one(
        self, obj_id: str, geojson: dict, collection_id=None
    ) -> httpx.Response:
        if collection_id is None:
            collection_id = self.default_collection_id

        reqUrl = f"https://b-2.i-bitz.world/core/api/features/1.0-beta/collections/{collection_id}/items/{obj_id}?api_key={self.api_key}"

        data = await self.client.patch(reqUrl, json=geojson)
        return data

    async def edit_one(self, obj_id: str, unit: UnitData):
        response = await self._edit_one(obj_id, unit.get_geojson())
        return response.json()


# class GMapEntry(BaseModel):
#     lat: float
#     lng: float
#     place_id: str
#     formatted_address: str

#     @classmethod
#     def from_geocode_result(cls, result):
#         return cls(
#             lat=result["geometry"]["location"]["lat"],
#             lng=result["geometry"]["location"]["lng"],
#             place_id=result["place_id"],
#             formatted_address=result["formatted_address"],
#         )

#     @property
#     def point(self):
#         return Point(self.lng, self.lat)


async def main(batch_size: int):
    df = read_pickle("data/ect/ect_geofilterd.pkl")
    # df = pd.read_parquet("data/ect/ect_geofilterd.parquet")

    units = []
    count = 0

    load_dotenv()
    api_client = VA_Elect_API(os.getenv("VA_DB_API_KEY"))

    # delete all units
    await api_client.delete_all()

    tasks = []
    semaphore = asyncio.Semaphore(4)

    async def create_units(units):
        async with semaphore:
            return await api_client.create(units)

    for i, row in tqdm(df.iterrows(), total=df.shape[0]):
        r = row.to_dict()

        u = UnitData(
            unit_id=r["UnitId"],
            unit_name=r["UnitName"],
            province_name=r["ProvinceName"],
            division_number=r["DivisionNumber"],
            district_name=r["DistrictName"],
            sub_district_name=r["SubDistrictName"],
            unit_number=r["UnitNumber"],
            latitude=r["Lat"],
            longitude=r["Lng"],
            google_map_url=create_google_url(
                (r["Lat"], r["Lng"]), placeId=r["PlaceId"]
            ),
            tier_location=r["TierLocation"],
        )
        units.append(u)

        # If the length of units is equal to batch_size, send them to the API and clear the list
        if len(units) == batch_size:
            count += len(units)
            tasks.append(create_units(units))
            units = []

    # Send any remaining units to the API
    if units:
        count += len(units)
        tasks.append(create_units(units))

    result = await asyncio.gather(*tasks)

    # save mapping
    import pickle

    with open("data/ect/ect_api_result.pkl", "wb") as f:
        pickle.dump(result, f)

    # import pandas as pd
    # # save mapping as csv
    # df = pd.DataFrame([u.dict() for u in units])

    # df.to_csv("data/ect/ect_unit_id_map.csv", index=False)


import asyncio
import aiohttp
import os
from dotenv import load_dotenv
from pandas import read_pickle
from tqdm import tqdm
from random import choice


import asyncio
import os
from dotenv import load_dotenv
from pandas import read_pickle
from tqdm import tqdm
from random import choice


async def update_unit(semaphore, api_client, unit):
    async with semaphore:
        unit.color = choice([UnitColor.Gray, UnitColor.Green])

        # get the unit from the API
        unit_raw = await api_client.get_many(properties={"unitId": unit.unit_id})

        # update the unit
        await api_client.edit_one(unit_raw["features"][0]["properties"]["_id"], unit)


async def random_change_color():
    """ """
    df = read_pickle("data/ect/ect_gpd.pkl")

    units = []
    count = 0

    load_dotenv()
    api_client = VA_Elect_API(os.getenv("VA_DB_API_KEY"))

    for i, row in tqdm(df.sample(1000).iterrows(), total=1000):
        r = row.to_dict()

        if r["PlaceId"] is None:
            continue

        u = UnitData(
            unit_id=r["UnitId"],
            unit_name=r["UnitName"],
            province_name=r["ProvinceName"],
            division_number=r["DivisionNumber"],
            district_name=r["DistrictName"],
            sub_district_name=r["SubDistrictName"],
            unit_number=r["UnitNumber"],
            latitude=r["Lat"],
            longitude=r["Lng"],
            google_map_url=create_google_url(
                (r["Lat"], r["Lng"]), placeId=r["PlaceId"]
            ),
        )
        units.append(u)

    # pick random unit
    semaphore = asyncio.Semaphore(8)  # limit the number of concurrent requests
    tasks = []
    for unit in tqdm(units):
        task = asyncio.create_task(update_unit(semaphore, api_client, unit))
        tasks.append(task)
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main(batch_size=200))
    # asyncio.run(random_change_color())

    # print(
    #     create_google_url(
    #         (13.755134, 100.490892), placeId="ChIJA7PG9AuZ4jARIyvh-TR_wkA"
    #     )
    # )
