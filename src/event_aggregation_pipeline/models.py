"""Pydantic data contracts and shared configuration for the event pipeline."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

ZURICH_TZ = ZoneInfo("Europe/Zurich")

ISO_DATETIME_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?([+-]\d{2}:\d{2})$"
HTTP_URL_PATTERN = r"^https?://\S+$"

EVENTFROG_API_URL = "https://api.eventfrog.net/v1/events"
UNISG_CALENDAR_URL = "https://www.unisg.ch/de/news/veranstaltungen/veranstaltungskalender/"
HSG_SQUARE_URL = "https://www.hsg-square.ch/de/programm/"


class EventSource(StrEnum):
    """Supported upstream event sources."""

    EVENTFROG = "eventfrog"
    HSG_CALENDAR = "hsg_calendar"
    HSG_SQUARE = "hsg_square"


class EventCategory(StrEnum):
    """Fixed category taxonomy required by the output schema."""

    NIGHTLIFE_MUSIC = "nightlife_music"
    SPORTS = "sports"
    CULTURE = "culture"
    TALKS_UNIVERSITY = "talks_university"
    FOOD_DRINKS = "food_drinks"
    OTHER = "other"


class EventLanguage(StrEnum):
    """Languages that can be reported in the output schema."""

    DE = "de"
    EN = "en"


def parse_zurich_datetime(value: datetime | str) -> datetime:
    """Parse a date/datetime and normalize it to Europe/Zurich.

    Naive values are interpreted as Zurich local time. Date-only strings are
    accepted and become midnight on that date.
    """

    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZURICH_TZ)
    return parsed.astimezone(ZURICH_TZ)


def to_zurich_iso(value: datetime | str) -> str:
    """Format an instant as ISO 8601 with a numeric Europe/Zurich offset."""

    return parse_zurich_datetime(value).isoformat(timespec="seconds")


class Event(BaseModel):
    """One normalized event, matching docs/events.schema.json."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^(eventfrog|hsg_calendar|hsg_square):.+$")
    source: EventSource
    source_id: str = Field(min_length=1)
    source_url: str = Field(pattern=HTTP_URL_PATTERN)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    category: EventCategory
    start: str = Field(pattern=ISO_DATETIME_PATTERN)
    end: str | None = Field(default=None, pattern=ISO_DATETIME_PATTERN)
    all_day: bool
    venue_name: str = Field(min_length=1)
    address: str = Field(min_length=1)
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    price_min_chf: float | None = Field(default=None, ge=0.0)
    price_max_chf: float | None = Field(default=None, ge=0.0)
    ticket_url: str | None = Field(default=None, pattern=HTTP_URL_PATTERN)
    language: EventLanguage | None = None
    image_url: str | None = Field(default=None, pattern=HTTP_URL_PATTERN)
    last_seen_at: str = Field(pattern=ISO_DATETIME_PATTERN)

    @model_validator(mode="after")
    def _validate_stable_id(self) -> Self:
        expected = f"{self.source.value}:{self.source_id}"
        if self.id != expected:
            raise ValueError(f"id must equal {expected!r}, got {self.id!r}")
        return self

    @model_validator(mode="after")
    def _validate_temporal_order(self) -> Self:
        if self.end is not None and parse_zurich_datetime(self.end) < parse_zurich_datetime(
            self.start
        ):
            raise ValueError("end must not be before start")
        return self

    @model_validator(mode="after")
    def _validate_price_range(self) -> Self:
        if (
            self.price_min_chf is not None
            and self.price_max_chf is not None
            and self.price_min_chf > self.price_max_chf
        ):
            raise ValueError("price_min_chf must not exceed price_max_chf")
        return self


class EventList(BaseModel):
    """Top-level output document written to data/events.json."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str = Field(pattern=ISO_DATETIME_PATTERN)
    events: list[Event] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_unique_ids(self) -> Self:
        ids = [event.id for event in self.events]
        if len(ids) != len(set(ids)):
            raise ValueError("event ids must be unique")
        return self


class PipelineConfig(BaseModel):
    """Runtime settings for collection and output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    location_name: str = Field(default="St. Gallen", min_length=1)
    radius_km: float = Field(default=15.0, gt=0.0)
    window_days: int = Field(default=30, ge=1)

    eventfrog_api_url: str = Field(default=EVENTFROG_API_URL, pattern=HTTP_URL_PATTERN)
    unisg_calendar_url: str = Field(default=UNISG_CALENDAR_URL, pattern=HTTP_URL_PATTERN)
    hsg_square_url: str = Field(default=HSG_SQUARE_URL, pattern=HTTP_URL_PATTERN)
    output_path: str = Field(default="data/events.json", min_length=1)
