from datetime import datetime
from typing import Literal, Optional, List
from enum import Enum, auto
from urllib import response
from autoname import AutoName
from pydantic import BaseModel, Json
import httpx


morning_end = datetime.fromisoformat("2023-05-14T09:00:00+07:00")
evening_start = datetime.fromisoformat("2023-05-14T17:00:00+07:00")
evening_end = datetime.fromisoformat("2023-05-14T20:00:00+07:00")


class UnitStatus(AutoName):
    Unknown = auto()
    Opening = auto()
    Closed = auto()


class UnitColor(AutoName):
    Gray = auto()
    Red = auto()
    Green = auto()


class IncidentData(BaseModel):
    objectid: str

    UnitData_objectid: str

    time: datetime
    description: str

    latitude: float
    longitude: float


class UnitData(BaseModel):
    objectid: Optional[int] = None

    unit_name: str
    province_name: str
    division_number: int
    sub_district_name: str
    unit_number: int

    latitude: float
    longitude: float
    google_address: str
    source: Literal["vote62", "ect", "wewatch"] = "ect"

    is_prefill_location: bool = False
    last_observed_time: Optional[datetime] = None

    # '[IncidentData_objectid, IncidentData_objectid]'
    incidents: Json[List[str]] = "[]"

    is_55_valid_morning: bool = False
    is_sign_valid_morning: bool = False
    is_55_valid_during_day: bool = False
    is_sign_valid_during_day: bool = False
    is_55_valid_evening: bool = False
    is_sign_valid_evening: bool = False
    is_57_valid_evening: bool = False
    is_518_valid_end_day: bool = False
    is_has_counting_spectator: bool = False

    @staticmethod
    def is_same_unit(unit: "UnitData") -> bool:
        return unit.unit_id == unit.unit_id

    @property
    def is_has_geo_location(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def assign_geo_location(self, lat: float, long: float):
        self.latitude = lat
        self.longitude = long

    @property
    def unit_color(self) -> UnitColor:
        current_time = datetime.now()
        if self.is_observation_completed(current_time):
            return UnitColor.Gray

        if self.is_last_observation_expired(current_time):
            return UnitColor.Red

        if self.is_observation_valid(current_time):
            return UnitColor.Green

        return UnitColor.Red

    def is_last_observation_expired(self, current_time: datetime) -> bool:
        if self.last_observed_time is None:
            return True

        time_difference_hours = (
            current_time - self.last_observed_time
        ).total_seconds() / 3600

        return time_difference_hours > 3

    def is_observation_valid(self, current_time: datetime) -> bool:
        if current_time < morning_end:
            return self.is_55_valid_morning and self.is_sign_valid_morning
        else:
            if current_time < evening_start:
                return self.is_55_valid_during_day and self.is_sign_valid_during_day
            elif current_time < evening_end:
                return (
                    self.is_55_valid_evening
                    and self.is_sign_valid_evening
                    and self.is_57_valid_evening
                    and self.is_has_counting_spectator
                )
            else:
                return self.is_518_valid_end_day or self.is_has_counting_spectator

    def is_observation_completed(self, current_time: datetime) -> bool:
        return current_time >= evening_end and self.is_518_valid_end_day

    #     {
    #     "type": "FeatureCollection",
    #     "features": [
    #         {
    #             "type": "Feature",
    #             "properties": {
    #                 "flood_level": 1
    #             },
    #             "geometry": {
    #                 "type": "Point",
    #                 "coordinates": [
    #                     102.79855728149414,
    #                     16.42800703334046
    #                 ]
    #             }
    #         }
    #     ]
    # }

    def get_geojson(self):
        return {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [self.longitude, self.latitude],
            },
            "properties": self.dict(exclude={"latitude", "longitude", "objectid"})
        }


class VA_Elect_API:
    api_key: str
    defualt_collection_id: str = "645ba137f1b89d8b8f1c5f09"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def _create(self, geojson: dict, collection_id=None) -> httpx.Response:
        client = httpx.Client()

        if collection_id is None:
            collection_id = self.defualt_collection_id

        reqUrl = f"https://b-2.i-bitz.world/core/api/features/1.0-beta/collections/{collection_id}/items?api_key={self.api_key}"

        data = client.post(reqUrl, json=geojson)

        return data

    def create(self, units: List[UnitData]):
        geojson = {
            "type": "FeatureCollection",
            "features": [unit.get_geojson() for unit in units],
        }

        response = self._create(geojson)

        return response.json()


#         {
#     "type": "FeatureCollection",
#     "features": [
#         {
#             "id": "645e0b8d92d61deb5313d6c1",
#             "type": "Feature",
#             "geometry": {
#                 "type": "Point",
#                 "coordinates": [
#                     102.79855728149414,
#                     16.42800703334046
#                 ]
#             },
#             "properties": {
#                 "_collectionId": "645ba137f1b89d8b8f1c5f09",
#                 "_createdAt": "2023-05-12T09:49:01.668Z",
#                 "_createdBy": "645b9fa7d6677d0b8265ac0a",
#                 "_id": "645e0b8d92d61deb5313d6c1",
#                 "_updatedAt": "2023-05-12T09:49:01.668Z",
#                 "_updatedBy": "645b9fa7d6677d0b8265ac0a",
#                 "flood_level": 1
#             }
#         }
#     ]
# }

if __name__ == "__main__":
    from pandas import read_excel, read_pickle

    df = read_pickle("data/sample_geocoded.pkl.gz")

    units = []

    for i, row in df.iterrows():
        r = row.to_dict()

        if len(r["geocoded_obj"]) == 0:
            continue

        u = UnitData(
            unit_name=r["สถานที่เลือกตั้ง"],
            province_name=r["จังหวัด"],
            division_number=r["เขตเลือกตั้ง"],
            sub_district_name=r["ตำบล"],
            unit_number=r["หน่วยเลือกตั้ง"],
            latitude=r["geocoded_obj"][0]["geometry"]["location"]["lat"],
            longitude=r["geocoded_obj"][0]["geometry"]["location"]["lng"],
            google_address=r["geocoded_obj"][0]["formatted_address"],
        )
        units.append(u)

    import os
    from dotenv import load_dotenv

    load_dotenv()
    api_client = VA_Elect_API(os.getenv("VA_DB_API_KEY"))
    api_client.create(units)
