"""Offline tests for St. Gallen event parsing and fixtures."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from event_aggregation_pipeline.eventfrog import parse_eventfrog_payload
from event_aggregation_pipeline.models import Event, EventCategory, EventLanguage, EventSource
from event_aggregation_pipeline.typo3_scraper import ParsedTypo3Page, parse_typo3_html

FIXTURES_DIR = Path(__file__).parent / "fixtures"
ZURICH = ZoneInfo("Europe/Zurich")
FIXED_NOW = datetime(2026, 11, 17, 0, 0, tzinfo=ZURICH)


def _read_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _load_eventfrog() -> list[Event]:
    payload: object = json.loads(_read_fixture("eventfrog_events.json"))
    return parse_eventfrog_payload(payload, last_seen_at=FIXED_NOW)


def _parse_typo3_fixture(name: str, source: EventSource) -> ParsedTypo3Page:
    return parse_typo3_html(_read_fixture(name), source, last_seen_at=FIXED_NOW)


def _find_event(
    events: Sequence[Event],
    title: str,
    start_prefix: str | None = None,
) -> Event:
    matches = [
        event
        for event in events
        if event.title == title and (start_prefix is None or event.start.startswith(start_prefix))
    ]
    assert len(matches) == 1, f"expected exactly one {title!r}, got {len(matches)}"
    return matches[0]


def _synthetic_card(
    *,
    title: str,
    venue: str,
    slug: str,
    times: tuple[str, str] | None = ("10:00", "11:00"),
) -> str:
    if times is None:
        time_block = ""
    else:
        start, end = times
        time_block = (
            '<div class="mt-3 text-center h-100">'
            f'<div class="font-size-ui-nav">{start}</div>'
            '<div class="my-1">-</div>'
            f'<div class="font-size-ui-nav">{end}</div>'
            "</div>"
        )
    return f"""
    <div class="event-item position-relative bg-light h-100 etype-0">
      <div class="row h-100">
        <div class="col-4">
          <div class="bg-primary text-white left-part position-relative">
            <div class="font-size-ui-nav text-uppercase mb-2">Mo</div>
            <div class="h1 huge mb-0">23.11.</div>
            {time_block}
            <div class="mt-3 text-center">
              <div class="font-size-ui-small">2026</div>
            </div>
          </div>
        </div>
        <div class="col-8">
          <div class="events-text">
            <div class="cat-title font-size-ui-small mb-2">Öffentliche Veranstaltungen</div>
            <h3 class="mb-3">{title}</h3>
            <div class="font-size-biggerRegular">A synthetic fixture event.</div>
          </div>
          <div class="font-size-ui mb-0 pr-9 row">
            <div class="col-12 col-lg-3">Ort:</div>
            <div class="col-12 col-lg-9">{venue}</div>
          </div>
        </div>
        <a href="https://example.org/events/{slug}" class="stretched-link"></a>
      </div>
    </div>
    """


def _synthetic_page(cards: Sequence[str]) -> str:
    return "<html><body>" + "".join(cards) + "</body></html>"


def test_offline_fixtures_available() -> None:
    assert (FIXTURES_DIR / "unisg_calendar.html").is_file()
    assert (FIXTURES_DIR / "hsg_square.html").is_file()
    assert (FIXTURES_DIR / "eventfrog_events.json").is_file()


def test_parse_eventfrog_fixture() -> None:
    events = _load_eventfrog()

    assert len(events) == 2
    assert {event.id for event in events} == {
        "eventfrog:102938475",
        "eventfrog:554433221",
    }
    assert all(isinstance(event, Event) for event in events)
    assert all(event.source is EventSource.EVENTFROG for event in events)

    jazz = _find_event(events, "St. Gallen Jazz Night")
    assert jazz.source_id == "102938475"
    assert jazz.source_url.endswith("st-gallen-jazz-night-102938475.html")
    assert jazz.category is EventCategory.NIGHTLIFE_MUSIC
    assert jazz.start == "2026-11-20T20:00:00+01:00"
    assert jazz.end == "2026-11-20T23:30:00+01:00"
    assert jazz.all_day is False
    assert jazz.venue_name == "Kugl St. Gallen"
    assert jazz.address == "Güterbahnhofstrasse 4, 9000 St. Gallen"
    assert jazz.latitude == pytest.approx(47.4212)
    assert jazz.longitude == pytest.approx(9.3621)
    assert jazz.price_min_chf == pytest.approx(15.0)
    assert jazz.price_max_chf == pytest.approx(25.0)
    assert jazz.ticket_url == "https://eventfrog.net/tickets/102938475"
    assert jazz.image_url == "https://eventfrog.net/media/event-102938475.jpg"
    assert jazz.language is EventLanguage.DE
    assert jazz.last_seen_at == "2026-11-17T00:00:00+01:00"

    football = _find_event(events, "FC St. Gallen vs FC Basel")
    assert football.category is EventCategory.SPORTS
    assert football.venue_name == "Kybunpark"
    assert football.address == "Zürcherstrasse 464, 9015 St. Gallen"
    assert football.price_min_chf == pytest.approx(25.0)
    assert football.price_max_chf == pytest.approx(70.0)
    assert football.latitude == pytest.approx(47.4089)
    assert football.longitude == pytest.approx(9.3094)


def test_parse_unisg_calendar_fixture() -> None:
    page = _parse_typo3_fixture("unisg_calendar.html", EventSource.HSG_CALENDAR)

    assert len(page.events) == 10
    assert all(event.source is EventSource.HSG_CALENDAR for event in page.events)

    first = _find_event(page.events, "Was zählt im Leben?")
    assert first.id == "hsg_calendar:was-zaehlt-im-leben"
    assert first.start == "2026-11-17T09:30:00+01:00"
    assert first.end == "2026-11-17T11:00:00+01:00"
    assert first.all_day is False
    assert first.venue_name == "Festsaal St.Katharinen"
    assert first.address == "Katharinengasse 11, 9000 St. Gallen"
    assert first.category is EventCategory.TALKS_UNIVERSITY
    assert first.language is EventLanguage.DE
    assert first.source_url.endswith("/was-zaehlt-im-leben/")
    assert first.description is not None
    assert "Sinn, Hoffnung, Beziehungen" in first.description

    lunch = _find_event(page.events, "Lunch mit Gästen")
    assert lunch.venue_name == "Akademikerhaus"
    assert lunch.address == "Dufourstrasse 87, 9000 St. Gallen"
    assert lunch.category is EventCategory.FOOD_DRINKS

    kinder_uni = _find_event(page.events, "Kinder-Uni")
    assert kinder_uni.description is not None
    assert "\xa0" not in kinder_uni.description
    assert "Baumhaus –" in kinder_uni.description

    cinema = _find_event(page.events, "cinema@SQUARE: Tetris")
    assert cinema.start == "2026-11-17T18:15:00+01:00"
    assert cinema.end == "2026-11-17T21:00:00+01:00"
    assert cinema.venue_name == "SQUARE, Raum Wiborada"
    assert cinema.address == "Guisanstrasse 20, 9010 St. Gallen"
    assert cinema.category is EventCategory.CULTURE

    multi_day = _find_event(page.events, "Artists in Residence: Origen")
    assert multi_day.all_day is True
    assert multi_day.start == "2026-11-18T00:00:00+01:00"
    assert multi_day.end == "2026-11-20T23:59:59+01:00"
    assert multi_day.venue_name == "SQUARE"
    assert multi_day.address == "Guisanstrasse 20, 9010 St. Gallen"
    assert multi_day.category is EventCategory.CULTURE

    assert page.max_page == 9
    assert page.page_numbers == tuple(range(1, 10))
    assert any("page=2" in url for url in page.pagination_urls)
    assert any("page=9" in url for url in page.pagination_urls)


def test_parse_hsg_square_fixture() -> None:
    page = _parse_typo3_fixture("hsg_square.html", EventSource.HSG_SQUARE)

    assert len(page.events) == 10
    assert all(event.source is EventSource.HSG_SQUARE for event in page.events)

    klimagerechtigkeit = _find_event(
        page.events, "Klimagerechtigkeit", start_prefix="2026-11-17T18:15"
    )
    assert klimagerechtigkeit.venue_name == "SQUARE, Raum Vadian"
    assert klimagerechtigkeit.address == "Guisanstrasse 20, 9010 St. Gallen"
    assert klimagerechtigkeit.category is EventCategory.TALKS_UNIVERSITY

    jour_fixe = _find_event(page.events, "KI Jour fixe @ SQUARE")
    assert jour_fixe.all_day is True
    assert jour_fixe.start == "2026-11-23T00:00:00+01:00"
    assert jour_fixe.end is None
    assert jour_fixe.venue_name == "SQUARE"
    assert jour_fixe.address == "Guisanstrasse 20, 9010 St. Gallen"
    assert jour_fixe.description is not None
    assert "\u00ad" not in jour_fixe.description
    assert "Herbstsemester" in jour_fixe.description
    assert jour_fixe.language is EventLanguage.DE

    minecraft = _find_event(page.events, "cinema@SQUARE: A Minecraft Movie")
    assert minecraft.all_day is False
    assert minecraft.start == "2026-11-24T18:15:00+01:00"
    assert minecraft.end is None
    assert minecraft.category is EventCategory.CULTURE

    docnet = _find_event(
        page.events,
        "24. DocNet Symposium: ARTificial Intelligence – Arts in the Age of AI",
    )
    assert docnet.language is EventLanguage.EN
    assert docnet.category is EventCategory.TALKS_UNIVERSITY

    roleplay = _find_event(page.events, "Roleplay: Consent, Power & University Culture")
    assert roleplay.language is EventLanguage.EN
    assert roleplay.category is EventCategory.CULTURE

    assert page.max_page == 2
    assert page.page_numbers == (1, 2)


def test_static_parser_extracts_at_least_40_events_across_fixture_pages() -> None:
    unisg = _parse_typo3_fixture("unisg_calendar.html", EventSource.HSG_CALENDAR)
    square = _parse_typo3_fixture("hsg_square.html", EventSource.HSG_SQUARE)
    eventfrog = _load_eventfrog()

    parsed: list[Event] = []
    for _ in range(2):
        parsed.extend(unisg.events)
        parsed.extend(square.events)
    parsed.extend(eventfrog)

    assert len(parsed) == 42
    assert len(parsed) >= 40
    assert sum(event.source is EventSource.EVENTFROG for event in parsed) == 2
    assert sum(event.source is EventSource.HSG_CALENDAR for event in parsed) == 20
    assert sum(event.source is EventSource.HSG_SQUARE for event in parsed) == 20


def test_online_only_events_excluded() -> None:
    html = _synthetic_page(
        [
            _synthetic_card(
                title="Online-Only Webinar",
                venue="Online",
                slug="online-only-webinar",
            ),
            _synthetic_card(
                title="Onlineseminar: Research Methods",
                venue="Onlineseminar",
                slug="onlineseminar-research-methods",
            ),
            _synthetic_card(
                title="Hybrid Talk",
                venue="Universität St.Gallen, Raum A 01-011 und online",
                slug="hybrid-talk",
            ),
        ]
    )
    page = parse_typo3_html(html, EventSource.HSG_SQUARE, last_seen_at=FIXED_NOW)

    assert len(page.events) == 1
    hybrid = page.events[0]
    assert hybrid.title == "Hybrid Talk"
    assert "Raum A 01-011" in hybrid.venue_name
    assert hybrid.address == "Dufourstrasse 50, 9000 St. Gallen"

    eventfrog_payload: object = [
        {
            "id": "900001",
            "title": "Virtual Webinar",
            "url": "https://eventfrog.net/e/900001",
            "category": "other",
            "start": "2026-11-23T18:00:00+01:00",
            "location": {"name": "Online", "city": "St. Gallen"},
        },
        {
            "id": "900002",
            "title": "Hybrid Concert",
            "url": "https://eventfrog.net/e/900002",
            "category": "nightlife_music",
            "start": "2026-11-23T20:00:00+01:00",
            "location": {
                "name": "SQUARE, Raum Vadian und online",
                "street": "Guisanstrasse 20",
                "zip": "9010",
                "city": "St. Gallen",
            },
        },
    ]
    eventfrog_events = parse_eventfrog_payload(eventfrog_payload, last_seen_at=FIXED_NOW)

    assert [event.title for event in eventfrog_events] == ["Hybrid Concert"]
    assert eventfrog_events[0].venue_name == "SQUARE, Raum Vadian und online"
