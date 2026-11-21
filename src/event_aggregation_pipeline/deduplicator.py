"""Deterministic ID and semantic deduplication with Eventfrog priority."""

from __future__ import annotations

import re
from collections.abc import Iterable

from .models import Event, EventSource, parse_zurich_datetime, to_zurich_iso

SOURCE_PRIORITY: dict[EventSource, int] = {
    EventSource.EVENTFROG: 0,
    EventSource.HSG_SQUARE: 1,
    EventSource.HSG_CALENDAR: 2,
}

_DEDUPLICATION_KEY = tuple[str, str, str]


def normalize_title(title: str) -> str:
    """Normalize a title for semantic cross-source comparison."""

    return re.sub(r"\s+", " ", title.strip().lower())


def normalize_start(start: str) -> str:
    """Normalize a start timestamp to Europe/Zurich minute precision."""

    return to_zurich_iso(start)[:16]


def normalize_venue(venue_name: str) -> str:
    """Normalize a venue name for semantic cross-source comparison."""

    return re.sub(r"\s+", " ", venue_name.strip().lower())


def deduplication_key(event: Event) -> _DEDUPLICATION_KEY:
    return (
        normalize_title(event.title),
        normalize_start(event.start),
        normalize_venue(event.venue_name),
    )


def deduplicate_events(events: Iterable[Event]) -> list[Event]:
    """Collapse duplicate ids and semantic duplicates.

    Higher-priority sources are processed first, so an Eventfrog record always
    wins over an HSG SQUARE record, which in turn wins over the university
    calendar. The final list is chronological by ``(start, id)``.
    """

    ordered = sorted(
        events,
        key=lambda event: (SOURCE_PRIORITY[event.source], event.id),
    )
    kept_by_key: dict[_DEDUPLICATION_KEY, Event] = {}
    seen_ids: set[str] = set()

    for event in ordered:
        if event.id in seen_ids:
            continue
        key = deduplication_key(event)
        if key in kept_by_key:
            continue
        kept_by_key[key] = event
        seen_ids.add(event.id)

    return sorted(
        kept_by_key.values(),
        key=lambda event: (parse_zurich_datetime(event.start), event.id),
    )
