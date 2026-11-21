"""Eventfrog public REST client and JSON payload parser."""

from __future__ import annotations

import logging
import os
import time
from collections import deque
from collections.abc import Callable, Mapping
from datetime import datetime
from datetime import time as clock_time
from typing import Self, cast

import httpx

from .models import (
    EVENTFROG_API_URL,
    ZURICH_TZ,
    Event,
    EventLanguage,
    EventSource,
    parse_zurich_datetime,
    to_zurich_iso,
)
from .normalization import categorize_event, clean_text, detect_language, is_online_only

logger = logging.getLogger(__name__)

DEFAULT_REQUESTS_PER_MINUTE = 30
DEFAULT_REQUEST_INTERVAL_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 15.0


class EventfrogError(RuntimeError):
    """Base class for Eventfrog client and payload failures."""


class EventfrogConfigurationError(EventfrogError):
    """Raised when no Eventfrog API key is configured."""


class EventfrogParseError(EventfrogError):
    """Raised when the upstream payload shape is not usable."""


class RateLimiter:
    """Sliding-window limiter enforcing at most N requests per period."""

    def __init__(
        self,
        *,
        max_requests: int = DEFAULT_REQUESTS_PER_MINUTE,
        period_seconds: float = 60.0,
        min_interval_seconds: float = DEFAULT_REQUEST_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be positive")
        self.max_requests = max_requests
        self.period_seconds = period_seconds
        self.min_interval_seconds = min_interval_seconds
        self._clock = clock
        self._sleep = sleeper
        self._timestamps: deque[float] = deque()

    def acquire(self) -> None:
        """Block until one more request fits inside the configured window."""

        while True:
            now = self._clock()
            while self._timestamps and now - self._timestamps[0] >= self.period_seconds:
                self._timestamps.popleft()

            wait_seconds = 0.0
            if self._timestamps and now - self._timestamps[-1] < self.min_interval_seconds:
                wait_seconds = self.min_interval_seconds - (now - self._timestamps[-1])
            if len(self._timestamps) >= self.max_requests:
                wait_seconds = max(
                    wait_seconds,
                    self.period_seconds - (now - self._timestamps[0]),
                )
            if wait_seconds > 0:
                self._sleep(wait_seconds)
                continue

            self._timestamps.append(now)
            return


class EventfrogClient:
    """Small synchronous client with authentication and rate limiting."""

    def __init__(
        self,
        api_key: str,
        *,
        api_url: str = EVENTFROG_API_URL,
        client: httpx.Client | None = None,
        limiter: RateLimiter | None = None,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        if not api_key.strip():
            raise EventfrogConfigurationError("EVENTFROG_API_KEY must not be empty")
        self.api_key = api_key
        self.api_url = api_url
        self._limiter = limiter or RateLimiter()
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        api_url: str = EVENTFROG_API_URL,
    ) -> EventfrogClient:
        source = environ if environ is not None else os.environ
        return cls(source.get("EVENTFROG_API_KEY", ""), api_url=api_url)

    def fetch_events(
        self,
        *,
        location: str = "St. Gallen",
        radius_km: float = 15.0,
        limit: int = 100,
        last_seen_at: datetime | None = None,
    ) -> list[Event]:
        """Fetch one page from Eventfrog, respecting the 30 req/min limit."""

        self._limiter.acquire()
        response = self._client.get(
            self.api_url,
            params={
                "apikey": self.api_key,
                "location": location,
                "radius": radius_km,
                "limit": limit,
            },
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        try:
            payload: object = response.json()
        except ValueError as exc:
            raise EventfrogParseError("Eventfrog returned invalid JSON") from exc
        return parse_eventfrog_payload(payload, last_seen_at=last_seen_at)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def parse_eventfrog_payload(
    payload: object,
    *,
    last_seen_at: datetime | None = None,
) -> list[Event]:
    """Parse Eventfrog JSON into validated Event models.

    Both a bare list and common envelope shapes (``events``/``data``/``items``)
    are accepted. Individual malformed records are skipped and logged.
    """

    reference = last_seen_at or datetime.now(ZURICH_TZ)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=ZURICH_TZ)
    last_seen = to_zurich_iso(reference)

    events: list[Event] = []
    for record in _extract_records(payload):
        if not isinstance(record, Mapping):
            logger.warning("Skipping non-object Eventfrog record")
            continue
        try:
            event = _parse_record(cast(Mapping[str, object], record), last_seen)
        except (EventfrogParseError, ValueError, TypeError, KeyError) as exc:
            logger.warning("Skipping malformed Eventfrog record: %s", exc)
            continue
        if event is not None:
            events.append(event)
    return events


def _extract_records(payload: object) -> list[object]:
    if isinstance(payload, list):
        return cast(list[object], payload)
    if isinstance(payload, Mapping):
        mapping = cast(Mapping[str, object], payload)
        for key in ("events", "data", "items", "results"):
            value = mapping.get(key)
            if isinstance(value, list):
                return cast(list[object], value)
    raise EventfrogParseError("unexpected Eventfrog payload shape")


def _parse_record(record: Mapping[str, object], last_seen_at: str) -> Event | None:
    event_id = _string(record.get("id"))
    if not event_id:
        raise EventfrogParseError("record has no id")

    title = clean_text(_string(record.get("title")) or _string(record.get("name")), max_length=200)
    if not title:
        raise EventfrogParseError("record has no title")

    url = _string(record.get("url")) or _string(record.get("source_url"))
    source_url = (
        url if url is not None and _is_http_url(url) else f"https://eventfrog.net/e/{event_id}"
    )

    start_raw = (
        _string(record.get("start"))
        or _string(record.get("startDate"))
        or _string(record.get("start_date"))
    )
    if not start_raw:
        raise EventfrogParseError("record has no start timestamp")
    start_datetime = parse_zurich_datetime(start_raw)

    end_raw = (
        _string(record.get("end"))
        or _string(record.get("endDate"))
        or _string(record.get("end_date"))
    )
    end_datetime = parse_zurich_datetime(end_raw) if end_raw else None

    all_day = _boolean(record.get("all_day")) or _boolean(record.get("allDay"))
    if all_day:
        start_datetime = datetime.combine(start_datetime.date(), clock_time.min, tzinfo=ZURICH_TZ)
        if end_datetime is not None:
            end_datetime = datetime.combine(
                end_datetime.date(), clock_time(23, 59, 59), tzinfo=ZURICH_TZ
            )

    location = _mapping(record.get("location"))
    venue_name = (
        _string(location.get("name"))
        or _string(record.get("venue_name"))
        or _string(record.get("venue"))
        or "St. Gallen"
    )
    street = _string(location.get("street")) or _string(record.get("street"))
    postal_code = _string(location.get("zip")) or _string(record.get("zip"))
    city = _string(location.get("city")) or _string(record.get("city")) or "St. Gallen"
    city_line = " ".join(part for part in (postal_code, city) if part)
    address = ", ".join(part for part in (street, city_line) if part) or city

    description = clean_text(_string(record.get("description")) or _string(record.get("summary")))
    if is_online_only(title, venue_name, address):
        return None

    price = _mapping(record.get("price"))
    currency = (_string(price.get("currency")) or "CHF").upper()
    price_min = _float(price.get("min")) if currency == "CHF" else None
    price_max = _float(price.get("max")) if currency == "CHF" else None
    ticket_url = _string(price.get("ticket_url")) or _string(record.get("ticket_url"))
    if not _is_http_url(ticket_url):
        ticket_url = None

    category_name = _category_name(record.get("category")) or _string(record.get("category_slug"))
    language = _language(_string(record.get("language")) or _string(record.get("lang")))
    if language is None:
        language = detect_language(description, title)

    latitude = _float(location.get("latitude"))
    if latitude is None:
        latitude = _float(record.get("latitude"))
    longitude = _float(location.get("longitude"))
    if longitude is None:
        longitude = _float(record.get("longitude"))
    image_url = _image_url(record.get("image") or record.get("image_url"))
    if not _is_http_url(image_url):
        image_url = None

    return Event(
        id=f"{EventSource.EVENTFROG.value}:{event_id}",
        source=EventSource.EVENTFROG,
        source_id=event_id,
        source_url=source_url,
        title=title,
        description=description,
        category=categorize_event(
            EventSource.EVENTFROG,
            category_name,
            title,
            description,
        ),
        start=to_zurich_iso(start_datetime),
        end=to_zurich_iso(end_datetime) if end_datetime is not None else None,
        all_day=all_day,
        venue_name=venue_name,
        address=address,
        latitude=latitude,
        longitude=longitude,
        price_min_chf=price_min,
        price_max_chf=price_max,
        ticket_url=ticket_url,
        language=language,
        image_url=image_url,
        last_seen_at=last_seen_at,
    )


def _mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    return {}


def _string(value: object) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _boolean(value: object) -> bool:
    return value is True


def _category_name(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        return _string(mapping.get("name")) or _string(mapping.get("slug"))
    return None


def _language(value: str | None) -> EventLanguage | None:
    if value is None:
        return None
    normalized = value.casefold()
    if normalized.startswith("de") or normalized in {"german", "deutsch"}:
        return EventLanguage.DE
    if normalized.startswith("en") or normalized == "english":
        return EventLanguage.EN
    return None


def _image_url(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        return _string(mapping.get("url")) or _string(mapping.get("src"))
    return None


def _is_http_url(value: str | None) -> bool:
    return value is not None and value.startswith(("http://", "https://"))
