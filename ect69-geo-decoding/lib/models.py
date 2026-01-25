"""Pydantic models for ETL data structures."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from shapely.geometry import Point


class CommitInfo(BaseModel):
    """Metadata for a git commit."""

    commit_hash: str
    author_name: str
    author_email: str
    timestamp: int
    datetime_utc: datetime
    message: str
    is_merge: bool
    parent_hash: str | None = None

    # Classification fields (populated during analysis)
    rows_changed: int = 0
    classification: Literal["manual", "scripted", "uncertain", "none"] = "none"
    classification_reason: str = ""
    time_since_prev_seconds: int | None = None


class RowChange(BaseModel):
    """Record of a coordinate change for a single row."""

    # Row identifier (natural key from CSV)
    province_number: int
    registrar_code: int
    subdis_code: int
    electorate: int
    location: str

    # Coordinate changes
    lat_before: float | None = None
    lng_before: float | None = None
    lat_after: float | None = None
    lng_after: float | None = None

    # Attribution
    commit_hash: str
    author_name: str
    author_email: str
    timestamp: int
    classification: Literal["manual", "scripted", "uncertain"]


class Station66Record(BaseModel):
    """Final output record with source attribution."""

    # Original CSV columns
    province_number: int
    province: str
    registrar_code: int
    registrar: str
    subdis_code: int
    subdistrict: str
    electorate: int
    location: str
    latitude: float | None = None
    longitude: float | None = None

    # Source attribution
    has_coords: bool = False
    source_commit: str | None = None
    source_author: str | None = None
    source_classification: Literal["manual", "scripted", "none"] = "none"
    source_timestamp: int | None = None


class GMapEntry(BaseModel):
    """Google Maps geocoding result entry."""

    lat: float
    lng: float
    place_id: str
    formatted_address: str

    @classmethod
    def from_geocode_result(cls, result: dict) -> "GMapEntry":
        """Parse Google Maps API geocoding response."""
        return cls(
            lat=result["geometry"]["location"]["lat"],
            lng=result["geometry"]["location"]["lng"],
            place_id=result["place_id"],
            formatted_address=result["formatted_address"],
        )

    @property
    def point(self) -> Point:
        """Get Shapely Point geometry (lng, lat order for GIS)."""
        return Point(self.lng, self.lat)


class EarlyVotingLocation(BaseModel):
    """Early voting location with geocoding results."""

    location_name: str
    geocode_query: str
    subdistrict: str | None
    district: str | None
    original: str  # Join key to source CSV
    lat: float | None = None
    lng: float | None = None
    place_id: str = ""
    formatted_address: str = ""
    tier_location: str = "D"  # A+ (validated) or D (fallback)
