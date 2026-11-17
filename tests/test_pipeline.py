"""Offline tests for deduplication, orchestration, and schema validation."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import validate as validate_module
from st_gallen_events_kata.deduplicator import deduplicate_events
from st_gallen_events_kata.eventfrog import parse_eventfrog_payload
from st_gallen_events_kata.models import (
    Event,
    EventCategory,
    EventSource,
    PipelineConfig,
)
from st_gallen_events_kata.pipeline import run_pipeline
from st_gallen_events_kata.typo3_scraper import parse_typo3_html

FIXTURES_DIR = Path(__file__).parent / "fixtures"
ZURICH = ZoneInfo("Europe/Zurich")
FIXED_NOW = datetime(2026, 11, 17, 5, 0, tzinfo=ZURICH)
LAST_SEEN_AT = "2026-11-17T00:00:00+01:00"


def _calendar_events() -> list[Event]:
    html = (FIXTURES_DIR / "unisg_calendar.html").read_text(encoding="utf-8")
    return list(parse_typo3_html(html, EventSource.HSG_CALENDAR).events)


def _square_events() -> list[Event]:
    html = (FIXTURES_DIR / "hsg_square.html").read_text(encoding="utf-8")
    return list(parse_typo3_html(html, EventSource.HSG_SQUARE).events)


def _eventfrog_events() -> list[Event]:
    payload: object = json.loads(
        (FIXTURES_DIR / "eventfrog_events.json").read_text(encoding="utf-8")
    )
    return parse_eventfrog_payload(payload)


def _event(
    source: EventSource,
    source_id: str,
    *,
    title: str = "Klimagerechtigkeit",
    start: str = "2026-11-17T18:15:00+01:00",
    venue_name: str = "SQUARE, Raum Vadian",
    category: EventCategory = EventCategory.TALKS_UNIVERSITY,
    latitude: float | None = None,
    longitude: float | None = None,
    price_min_chf: float | None = None,
    price_max_chf: float | None = None,
) -> Event:
    return Event(
        id=f"{source.value}:{source_id}",
        source=source,
        source_id=source_id,
        source_url=f"https://example.org/{source.value}/{source_id}",
        title=title,
        description="Synthetic event for deterministic deduplication tests.",
        category=category,
        start=start,
        end=None,
        all_day=False,
        venue_name=venue_name,
        address="Guisanstrasse 20, 9010 St. Gallen",
        latitude=latitude,
        longitude=longitude,
        price_min_chf=price_min_chf,
        price_max_chf=price_max_chf,
        language=None,
        last_seen_at=LAST_SEEN_AT,
    )


def _failing_loader() -> list[Event]:
    raise RuntimeError("simulated upstream failure")


def test_deduplicator_merges_same_title_start_venue_with_eventfrog_priority() -> None:
    calendar = _event(
        EventSource.HSG_CALENDAR,
        "klimagerechtigkeit-1",
        title="  Klimagerechtigkeit  ",
        start="2026-11-17T18:15:59+01:00",
        venue_name="square,  raum vadian",
    )
    square = _event(
        EventSource.HSG_SQUARE,
        "klimagerechtigkeit-1",
        title="Klimagerechtigkeit",
        start="2026-11-17T18:15:00+01:00",
        venue_name="SQUARE, Raum Vadian",
    )
    eventfrog = _event(
        EventSource.EVENTFROG,
        "102938475",
        category=EventCategory.NIGHTLIFE_MUSIC,
        latitude=47.4212,
        longitude=9.3621,
        price_min_chf=15.0,
        price_max_chf=25.0,
    )

    merged = deduplicate_events([calendar, eventfrog, square])

    assert len(merged) == 1
    kept = merged[0]
    assert kept.id == "eventfrog:102938475"
    assert kept.source is EventSource.EVENTFROG
    assert kept.category is EventCategory.NIGHTLIFE_MUSIC
    assert kept.latitude == 47.4212
    assert kept.longitude == 9.3621
    assert kept.price_min_chf == 15.0

    assert len(deduplicate_events([eventfrog, eventfrog])) == 1


def test_deduplicator_cross_source_hsg_fixtures() -> None:
    calendar = _calendar_events()
    square = _square_events()
    eventfrog = _eventfrog_events()

    assert len(calendar) == 10
    assert len(square) == 10
    assert len(eventfrog) == 2

    html_only = deduplicate_events([*calendar, *square])
    assert len(html_only) == 16

    merged = deduplicate_events([*calendar, *square, *eventfrog])
    assert len(merged) == 18
    assert len({event.id for event in merged}) == len(merged)

    overlaps = (
        ("Klimagerechtigkeit", "2026-11-17T18:15"),
        ("cinema@SQUARE: Tetris", "2026-11-17T18:15"),
        ("SanktGaller Gesundheitsforum", "2026-11-18T17:15"),
        ("Artists in Residence: Origen", "2026-11-18T00:00"),
    )
    for title, start_prefix in overlaps:
        matches = [
            event
            for event in merged
            if event.title == title and event.start.startswith(start_prefix)
        ]
        assert len(matches) == 1, title
        assert matches[0].source is EventSource.HSG_SQUARE


def test_pipeline_offline_end_to_end_and_schema_validation(tmp_path: Path) -> None:
    config = PipelineConfig()
    output_path = tmp_path / "data" / "events.json"

    event_list = run_pipeline(offline=True, output_path=output_path, now=FIXED_NOW)

    assert output_path.is_file()
    assert event_list.generated_at == "2026-11-17T05:00:00+01:00"
    assert len(event_list.events) == 18

    document = validate_module.validate_file(output_path)
    assert document["generated_at"] == "2026-11-17T05:00:00+01:00"
    raw_events = document["events"]
    assert isinstance(raw_events, list)
    assert len(raw_events) == 18

    sources = {str(event["source"]) for event in raw_events}
    assert sources == {"eventfrog", "hsg_calendar", "hsg_square"}

    ids = {str(event["id"]) for event in raw_events}
    assert len(ids) == 18
    assert config.timezone == "Europe/Zurich"
    assert config.schedule_cron == "0 5 * * 1"


def test_pipeline_fault_isolation_and_last_valid_file_preservation(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    output_path = tmp_path / "data" / "events.json"

    isolated = run_pipeline(
        source_loaders={
            EventSource.EVENTFROG: _eventfrog_events,
            EventSource.HSG_CALENDAR: _failing_loader,
            EventSource.HSG_SQUARE: _square_events,
        },
        output_path=output_path,
        now=FIXED_NOW,
    )

    assert "hsg_calendar" in caplog.text
    assert len(isolated.events) == 12
    assert all(event.source is not EventSource.HSG_CALENDAR for event in isolated.events)
    document = validate_module.validate_file(output_path)
    raw_events = document["events"]
    assert isinstance(raw_events, list)
    assert len(raw_events) == 12

    before = output_path.read_bytes()
    preserved = run_pipeline(
        source_loaders={
            EventSource.EVENTFROG: _failing_loader,
            EventSource.HSG_CALENDAR: _failing_loader,
            EventSource.HSG_SQUARE: _failing_loader,
        },
        output_path=output_path,
        now=FIXED_NOW,
    )

    assert output_path.read_bytes() == before
    assert len(preserved.events) == 12
    validate_module.validate_file(output_path)
