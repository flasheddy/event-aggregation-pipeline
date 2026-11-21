"""Fault-isolated orchestration and atomic events.json writer."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from datetime import time as clock_time
from pathlib import Path

from .deduplicator import deduplicate_events
from .eventfrog import EventfrogClient, parse_eventfrog_payload
from .models import (
    ZURICH_TZ,
    Event,
    EventList,
    EventSource,
    PipelineConfig,
    parse_zurich_datetime,
    to_zurich_iso,
)
from .normalization import is_online_only
from .typo3_scraper import parse_typo3_html, scrape_typo3_site

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"

SourceLoader = Callable[[], Sequence[Event]]
_SOURCE_ORDER: tuple[EventSource, ...] = (
    EventSource.EVENTFROG,
    EventSource.HSG_CALENDAR,
    EventSource.HSG_SQUARE,
)


class PipelineError(RuntimeError):
    """Raised when no events can be produced and no prior output is available."""


def run_pipeline(
    config: PipelineConfig | None = None,
    *,
    offline: bool = False,
    output_path: Path | str | None = None,
    now: datetime | None = None,
    source_loaders: Mapping[EventSource, SourceLoader] | None = None,
) -> EventList:
    """Run every source independently, deduplicate, and write the output file."""

    cfg = config or PipelineConfig()
    reference = now or datetime.now(ZURICH_TZ)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=ZURICH_TZ)
    reference = reference.astimezone(ZURICH_TZ)
    generated_at = to_zurich_iso(reference)

    destination = _resolve_output_path(cfg, output_path)
    loaders = (
        dict(source_loaders)
        if source_loaders is not None
        else _build_source_loaders(cfg, offline=offline, last_seen_at=reference)
    )

    collected: list[Event] = []
    for source in _SOURCE_ORDER:
        loader = loaders.get(source)
        if loader is None:
            continue
        try:
            source_events = list(loader())
        except Exception:
            logger.exception("Source %s failed; continuing with remaining sources", source.value)
            continue

        usable = [
            event
            for event in source_events
            if not is_online_only(event.title, event.venue_name, event.address)
            and _is_within_window(event, reference, cfg.window_days)
        ]
        logger.info(
            "Source %s returned %d events (%d usable)",
            source.value,
            len(source_events),
            len(usable),
        )
        collected.extend(usable)

    unique_events = deduplicate_events(collected)
    if not unique_events:
        previous = _read_previous(destination)
        if previous is not None:
            logger.warning(
                "All sources failed or yielded no usable events; preserving %s",
                destination,
            )
            return previous
        raise PipelineError(
            "all sources failed or yielded no usable events and no previous output exists"
        )

    event_list = EventList(generated_at=generated_at, events=unique_events)
    write_events(event_list, destination)
    logger.info("Wrote %d unique events to %s", len(unique_events), destination)
    return event_list


def write_events(event_list: EventList, output_path: Path | str) -> Path:
    """Atomically write a validated EventList document as UTF-8 JSON."""

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = event_list.model_dump(mode="json")
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temporary = destination.with_name(f"{destination.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(destination)
    return destination


def _resolve_output_path(
    config: PipelineConfig,
    output_path: Path | str | None,
) -> Path:
    if output_path is None:
        candidate = Path(config.output_path)
        return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate
    candidate = Path(output_path)
    return candidate if candidate.is_absolute() else Path.cwd() / candidate


def _is_within_window(event: Event, reference: datetime, window_days: int) -> bool:
    window_start = datetime.combine(reference.date(), clock_time.min, tzinfo=ZURICH_TZ)
    window_end = window_start + timedelta(days=window_days)
    start = parse_zurich_datetime(event.start)
    return window_start <= start <= window_end


def _read_previous(path: Path) -> EventList | None:
    if not path.is_file():
        return None
    try:
        return EventList.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("Previous output at %s is not a valid event document", path)
        return None


def _build_source_loaders(
    config: PipelineConfig,
    *,
    offline: bool,
    last_seen_at: datetime,
) -> dict[EventSource, SourceLoader]:
    if offline:
        return _offline_loaders(last_seen_at)

    def load_eventfrog() -> list[Event]:
        with EventfrogClient.from_env() as client:
            return client.fetch_events(
                location=config.location_name,
                radius_km=config.radius_km,
                last_seen_at=last_seen_at,
            )

    def load_unisg() -> list[Event]:
        return scrape_typo3_site(
            config.unisg_calendar_url,
            EventSource.HSG_CALENDAR,
            last_seen_at=last_seen_at,
        )

    def load_square() -> list[Event]:
        return scrape_typo3_site(
            config.hsg_square_url,
            EventSource.HSG_SQUARE,
            last_seen_at=last_seen_at,
        )

    return {
        EventSource.EVENTFROG: load_eventfrog,
        EventSource.HSG_CALENDAR: load_unisg,
        EventSource.HSG_SQUARE: load_square,
    }


def _offline_loaders(last_seen_at: datetime) -> dict[EventSource, SourceLoader]:
    def load_eventfrog() -> list[Event]:
        payload: object = json.loads(
            (FIXTURES_DIR / "eventfrog_events.json").read_text(encoding="utf-8")
        )
        return parse_eventfrog_payload(payload, last_seen_at=last_seen_at)

    def load_unisg() -> list[Event]:
        html = (FIXTURES_DIR / "unisg_calendar.html").read_text(encoding="utf-8")
        return list(
            parse_typo3_html(
                html,
                EventSource.HSG_CALENDAR,
                last_seen_at=last_seen_at,
            ).events
        )

    def load_square() -> list[Event]:
        html = (FIXTURES_DIR / "hsg_square.html").read_text(encoding="utf-8")
        return list(
            parse_typo3_html(
                html,
                EventSource.HSG_SQUARE,
                last_seen_at=last_seen_at,
            ).events
        )

    return {
        EventSource.EVENTFROG: load_eventfrog,
        EventSource.HSG_CALENDAR: load_unisg,
        EventSource.HSG_SQUARE: load_square,
    }
