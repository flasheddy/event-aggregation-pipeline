"""TYPO3 HTML parser and polite pagination scraper for the HSG sources."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as clock_time
from html import unescape
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse, urlunparse

import httpx
from selectolax.lexbor import LexborHTMLParser, LexborNode

from .models import (
    HSG_SQUARE_URL,
    UNISG_CALENDAR_URL,
    ZURICH_TZ,
    Event,
    EventSource,
    to_zurich_iso,
)
from .normalization import categorize_event, clean_text, detect_language, is_online_only

logger = logging.getLogger(__name__)

USER_AGENT = "event-aggregation-pipeline/0.1 (polite event aggregation)"
REQUEST_TIMEOUT_SECONDS = 15.0
PAGE_DELAY_SECONDS = 1.0

_BASE_URLS: dict[EventSource, str] = {
    EventSource.HSG_CALENDAR: UNISG_CALENDAR_URL,
    EventSource.HSG_SQUARE: HSG_SQUARE_URL,
}

_CLOCK_RE = re.compile(r"^\d{1,2}:\d{2}$")
_DATE_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.$")
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_VENUE_LABELS = frozenset({"ort", "location", "venue"})
_SPEAKER_LABELS = frozenset({"referent", "referentin", "referenten", "speaker"})


@dataclass(frozen=True, slots=True)
class ParsedTypo3Page:
    """Parsed cards and the highest pagination page discovered on one page."""

    events: tuple[Event, ...]
    max_page: int = 1


def parse_typo3_html(
    html: str,
    source: EventSource,
    *,
    last_seen_at: datetime | None = None,
    base_url: str | None = None,
) -> ParsedTypo3Page:
    """Parse all TYPO3 event cards in a static HTML document."""

    if source not in (EventSource.HSG_CALENDAR, EventSource.HSG_SQUARE):
        raise ValueError(f"unsupported TYPO3 source: {source.value}")

    reference = last_seen_at or datetime.now(ZURICH_TZ)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=ZURICH_TZ)
    reference = reference.astimezone(ZURICH_TZ)
    last_seen = to_zurich_iso(reference)
    resolved_base_url = base_url or _BASE_URLS[source]

    tree = LexborHTMLParser(html)
    events: list[Event] = []
    for card in tree.css(".event-item"):
        try:
            event = _parse_card(card, source, reference, last_seen, resolved_base_url)
        except (ValueError, TypeError, KeyError) as exc:
            logger.warning("Skipping malformed %s card: %s", source.value, exc)
            continue
        if event is not None:
            events.append(event)

    return ParsedTypo3Page(events=tuple(events), max_page=_max_page(tree))


def scrape_typo3_site(
    url: str,
    source: EventSource,
    *,
    client: httpx.Client | None = None,
    max_pages: int | None = None,
    page_delay: float = PAGE_DELAY_SECONDS,
    last_seen_at: datetime | None = None,
) -> list[Event]:
    """Fetch and parse a paginated TYPO3 listing with polite delays."""

    reference = last_seen_at or datetime.now(ZURICH_TZ)
    owns_client = client is None
    http = client or httpx.Client(
        timeout=REQUEST_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        first_page = _fetch_page(http, url, source, reference)
        events = list(first_page.events)
        final_page = (
            first_page.max_page if max_pages is None else min(first_page.max_page, max_pages)
        )
        for page_number in range(2, final_page + 1):
            if page_delay > 0:
                time.sleep(page_delay)
            page_url = _with_page_number(url, page_number)
            page = _fetch_page(http, page_url, source, reference)
            events.extend(page.events)
        return events
    finally:
        if owns_client:
            http.close()


def _parse_card(
    card: LexborNode,
    source: EventSource,
    reference: datetime,
    last_seen_at: str,
    base_url: str,
) -> Event | None:
    title_node = card.css_first("h3")
    title = clean_text(title_node.text() if title_node is not None else None, max_length=200)
    if title is None:
        raise ValueError("missing title")

    description_node = card.css_first(".font-size-biggerRegular")
    description = clean_text(description_node.text() if description_node is not None else None)

    category_node = card.css_first(".cat-title")
    source_category = category_node.text() if category_node is not None else None

    venue_lines = _html_lines(_field_container(card, _VENUE_LABELS))
    venue_name = venue_lines[0] if venue_lines else ""
    raw_address = ", ".join(venue_lines[1:]) if len(venue_lines) > 1 else ""

    if is_online_only(title, venue_name, raw_address):
        return None
    if not venue_name:
        raise ValueError("missing venue")

    address = _derive_address(venue_lines)
    speakers = " ".join(_html_lines(_field_container(card, _SPEAKER_LABELS)))

    link = card.css_first("a.stretched-link")
    if link is None:
        link = card.css_first("a[href]")
    href = link.attributes.get("href") if link is not None else None
    if not href:
        raise ValueError("missing event URL")
    source_url = urljoin(base_url, href)
    source_id = _source_id_from_url(source_url)
    if not source_id:
        raise ValueError("missing event slug")

    event_class = card.attributes.get("class") or ""
    start_datetime, end_datetime, all_day = _parse_temporal(
        card,
        reference,
        multi_day="etype-1" in event_class.split(),
    )

    # The schema requires complete ISO timestamps. Normalize back to Zurich
    # after date arithmetic so DST transitions keep the correct offset.
    start = to_zurich_iso(start_datetime)
    end = to_zurich_iso(end_datetime) if end_datetime is not None else None

    return Event(
        id=f"{source.value}:{source_id}",
        source=source,
        source_id=source_id,
        source_url=source_url,
        title=title,
        description=description,
        category=categorize_event(source, source_category, title, description),
        start=start,
        end=end,
        all_day=all_day,
        venue_name=venue_name,
        address=address,
        latitude=None,
        longitude=None,
        price_min_chf=None,
        price_max_chf=None,
        ticket_url=None,
        language=detect_language(speakers, description, title),
        image_url=None,
        last_seen_at=last_seen_at,
    )


def _parse_temporal(
    card: LexborNode,
    reference: datetime,
    *,
    multi_day: bool,
) -> tuple[datetime, datetime | None, bool]:
    date_nodes = card.css(".left-part .h1.huge")
    parsed_dates = [
        match.groups()
        for node in date_nodes
        if (match := _DATE_RE.match(node.text(strip=True))) is not None
    ]
    if not parsed_dates:
        raise ValueError("missing event date")

    year = _extract_year(card, reference)
    start_day = _build_date(year, parsed_dates[0], reference)
    if multi_day and len(parsed_dates) > 1:
        end_day = _build_date(year, parsed_dates[1], reference)
        if end_day < start_day:
            end_day = end_day.replace(year=end_day.year + 1)
        start_datetime = datetime.combine(start_day, clock_time.min, tzinfo=ZURICH_TZ)
        end_datetime = datetime.combine(
            end_day,
            clock_time(23, 59, 59),
            tzinfo=ZURICH_TZ,
        )
        return start_datetime, end_datetime, True

    clock_values = [
        node.text(strip=True)
        for node in card.css(".left-part .font-size-ui-nav")
        if _CLOCK_RE.match(node.text(strip=True))
    ]
    if not clock_values:
        start_datetime = datetime.combine(start_day, clock_time.min, tzinfo=ZURICH_TZ)
        return start_datetime, None, True

    start_clock = _parse_clock(clock_values[0])
    start_datetime = datetime.combine(start_day, start_clock, tzinfo=ZURICH_TZ)
    if len(clock_values) < 2:
        return start_datetime, None, False

    end_clock = _parse_clock(clock_values[1])
    if end_clock == start_clock:
        return start_datetime, None, False

    end_datetime = datetime.combine(start_day, end_clock, tzinfo=ZURICH_TZ)
    if end_datetime < start_datetime:
        end_datetime += timedelta(days=1)
    return start_datetime, end_datetime, False


def _extract_year(card: LexborNode, reference: datetime) -> int:
    for node in card.css(".left-part .font-size-ui-small"):
        match = _YEAR_RE.search(node.text(strip=True))
        if match is not None:
            return int(match.group(1))
    return reference.year


def _build_date(year: int, parts: tuple[str, ...], reference: datetime) -> date:
    day = int(parts[0])
    month = int(parts[1])
    candidate = date(year, month, day)
    if year == reference.year and candidate < reference.date() - timedelta(days=180):
        candidate = candidate.replace(year=year + 1)
    return candidate


def _parse_clock(value: str) -> clock_time:
    hours, minutes = value.split(":", maxsplit=1)
    return clock_time(int(hours), int(minutes))


def _field_container(card: LexborNode, labels: frozenset[str]) -> LexborNode | None:
    cells = card.css(".row .col-12")
    for index, cell in enumerate(cells):
        label = clean_text(cell.text(), max_length=64)
        if label is None:
            continue
        normalized = label.rstrip(":").strip().casefold()
        if normalized in labels and index + 1 < len(cells):
            return cells[index + 1]
    return None


def _html_lines(node: LexborNode | None) -> list[str]:
    """Return non-empty text lines, treating <br> as a line separator."""

    if node is None:
        return []
    fragment = node.html or ""
    lines: list[str] = []
    for part in re.split(r"(?i)<br\s*/?>", fragment):
        text = unescape(re.sub(r"(?s)<[^>]+>", " ", part))
        text = text.replace("\u00ad", "").replace("\xa0", " ")
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            lines.append(text)
    if not lines:
        fallback = clean_text(node.text())
        if fallback:
            lines.append(fallback)
    return lines


def _derive_address(lines: list[str]) -> str:
    if not lines:
        return "St. Gallen"
    if len(lines) == 1:
        if lines[0].casefold().startswith("square"):
            return "Guisanstrasse 20, 9010 St. Gallen"
        return "Dufourstrasse 50, 9000 St. Gallen"

    extras = [line for line in lines[1:] if line]
    address = ", ".join(extras)
    if not re.search(r"\b\d{4}\b", address):
        address = f"{address}, 9000 St. Gallen" if address else "9000 St. Gallen"
    return address


def _source_id_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    slug = path.rsplit("/", maxsplit=1)[-1]
    return unquote(slug)


def _max_page(tree: LexborHTMLParser) -> int:
    container = tree.css_first("ul.cs2events-pagination")
    links = container.css("a") if container is not None else tree.css('a[href*="page="]')
    pages = [number for link in links if (number := _page_number_from_link(link)) is not None]
    return max(pages, default=1)


def _page_number_from_link(link: LexborNode) -> int | None:
    data_page = link.attributes.get("data-page")
    if data_page is not None and data_page.isdigit():
        return int(data_page)

    href = link.attributes.get("href")
    if href is None:
        return None
    query = parse_qs(urlparse(href).query)
    values = query.get("page")
    if values and values[0].isdigit():
        return int(values[0])
    return None


def _fetch_page(
    client: httpx.Client,
    url: str,
    source: EventSource,
    reference: datetime,
) -> ParsedTypo3Page:
    response = client.get(url)
    response.raise_for_status()
    return parse_typo3_html(response.text, source, last_seen_at=reference, base_url=url)


def _with_page_number(url: str, page_number: int) -> str:
    scheme, netloc, path, params, query, fragment = urlparse(url)
    query_values = parse_qs(query)
    query_values["page"] = [str(page_number)]
    return urlunparse((scheme, netloc, path, params, urlencode(query_values, doseq=True), fragment))
