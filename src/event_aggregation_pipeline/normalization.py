"""Shared text cleaning, language detection, and taxonomy mapping helpers."""

from __future__ import annotations

import html as html_lib
import re

from .models import EventCategory, EventLanguage, EventSource

SOFT_HYPHEN = "\u00ad"
NO_BREAK_SPACE = "\xa0"

_HTML_TAG_RE = re.compile(r"(?s)<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_ENGLISH_ANNOUNCEMENT_RE = re.compile(
    r"\bevents?\s+in\s+(?:english|englisch)\b",
    flags=re.IGNORECASE,
)
_ENGLISH_WORDS = frozenset(
    {
        "the",
        "and",
        "with",
        "what",
        "when",
        "where",
        "this",
        "that",
        "these",
        "those",
        "for",
        "from",
        "your",
        "our",
        "is",
        "are",
        "was",
        "were",
        "have",
        "has",
        "will",
        "would",
        "can",
        "could",
        "should",
        "join",
        "together",
        "people",
        "experience",
        "chance",
        "insights",
        "new",
        "care",
        "paths",
        "event",
        "events",
        "university",
        "culture",
        "arts",
    }
)
_GERMAN_WORDS = frozenset(
    {
        "und",
        "der",
        "die",
        "das",
        "mit",
        "für",
        "ist",
        "nicht",
        "ein",
        "eine",
        "einen",
        "einem",
        "zu",
        "wir",
        "auf",
        "von",
        "im",
        "den",
        "dem",
        "des",
        "auch",
        "werden",
        "wird",
        "sich",
        "oder",
        "als",
        "bei",
        "aus",
        "nach",
        "über",
        "zum",
        "zur",
        "sie",
        "hat",
        "haben",
        "kann",
        "können",
        "diese",
        "dieser",
        "dieses",
        "veranstaltung",
        "universität",
    }
)
_ONLINE_MARKERS = (
    "online",
    "webinar",
    "zoom-meeting",
    "zoom meeting",
    "virtuell",
    "virtual",
)
_HYBRID_MARKERS = (
    "und online",
    "and online",
    "online und",
    "online and",
    "hybrid",
)
_PHYSICAL_VENUE_MARKERS = (
    "raum",
    "room",
    "square",
    "campus",
    "strasse",
    "street",
    "saal",
    "audimax",
    "bibliothek",
    "gebäude",
    "building",
    "universität",
    "university",
    "hsg",
    "festsaal",
    "akademikerhaus",
    "atrium",
    "arena",
    "kugl",
    "kybunpark",
)

_SOURCE_CATEGORY_MAP: dict[str, EventCategory] = {
    "nightlife_music": EventCategory.NIGHTLIFE_MUSIC,
    "nightlife": EventCategory.NIGHTLIFE_MUSIC,
    "konzerte": EventCategory.NIGHTLIFE_MUSIC,
    "musik": EventCategory.NIGHTLIFE_MUSIC,
    "party": EventCategory.NIGHTLIFE_MUSIC,
    "jazz": EventCategory.NIGHTLIFE_MUSIC,
    "club": EventCategory.NIGHTLIFE_MUSIC,
    "dj": EventCategory.NIGHTLIFE_MUSIC,
    "sports": EventCategory.SPORTS,
    "sport": EventCategory.SPORTS,
    "fussball": EventCategory.SPORTS,
    "culture": EventCategory.CULTURE,
    "kultur": EventCategory.CULTURE,
    "theater": EventCategory.CULTURE,
    "film": EventCategory.CULTURE,
    "kino": EventCategory.CULTURE,
    "kunst": EventCategory.CULTURE,
    "museum": EventCategory.CULTURE,
    "food_drinks": EventCategory.FOOD_DRINKS,
    "gastronomie": EventCategory.FOOD_DRINKS,
    "kulinarik": EventCategory.FOOD_DRINKS,
    "other": EventCategory.OTHER,
}
_HSG_TALK_CATEGORIES = frozenset(
    {
        "öffentliche vorlesungen",
        "öffentliche vorlesung",
        "kongresse und tagungen",
        "info-veranstaltungen",
        "informationsveranstaltungen",
    }
)
_CATEGORY_MARKERS: tuple[tuple[EventCategory, tuple[str, ...]], ...] = (
    (
        EventCategory.NIGHTLIFE_MUSIC,
        ("concert", "konzert", "jazz", "live music", "party", "club", "dj "),
    ),
    (
        EventCategory.SPORTS,
        ("sport", "fussball", "football", "match", "turnier", "lauf", "yoga"),
    ),
    (
        EventCategory.CULTURE,
        (
            "cinema@square",
            "film",
            "dokfilm",
            "artists in residence",
            "bühne",
            "buehne",
            "kunst",
            "theater",
            "konzert",
            "ausstellung",
            "culture",
            "kultur",
            "kino",
            "museum",
        ),
    ),
    (
        EventCategory.TALKS_UNIVERSITY,
        (
            "vorlesung",
            "antrittsvorlesung",
            "symposium",
            "jour fixe",
            "forum",
            "kolloquium",
            "seminar",
            "workshop",
            "diskussion",
            "lecture",
            "talk",
            "conference",
            "kongress",
            "tagung",
        ),
    ),
    (
        EventCategory.FOOD_DRINKS,
        (
            "lunch",
            "dinner",
            "degustation",
            "brunch",
            "apéro",
            "apero",
            "food",
            "wine",
            "gastronomie",
            "kulinarik",
        ),
    ),
)


def clean_text(value: str | None, *, max_length: int = 500) -> str | None:
    """Strip markup, soft hyphens, and NBSPs, then collapse whitespace."""

    if value is None:
        return None
    text = _HTML_TAG_RE.sub(" ", value)
    text = html_lib.unescape(text)
    text = text.replace(SOFT_HYPHEN, "").replace(NO_BREAK_SPACE, " ")
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if not text:
        return None
    if len(text) <= max_length:
        return text
    if max_length <= 3:
        return text[:max_length]

    cutoff = max_length - 3
    candidate = text[:cutoff]
    if " " in candidate:
        candidate = candidate.rsplit(" ", 1)[0]
    candidate = candidate.rstrip(" ,;:-–—")
    if not candidate:
        candidate = text[:cutoff]
    return f"{candidate}..."


def detect_language(
    *parts: str | None,
    default: EventLanguage = EventLanguage.DE,
) -> EventLanguage:
    """Detect German or English from explicit markers and lightweight keywords."""

    combined = " ".join(part for part in parts if part).casefold()
    if not combined:
        return default

    if _ENGLISH_ANNOUNCEMENT_RE.search(combined):
        if "und deutsch" in combined or "and german" in combined:
            return EventLanguage.DE
        return EventLanguage.EN

    if re.search(r"\bevents?\s+in\s+(?:german|deutsch)\b", combined):
        return EventLanguage.DE

    tokens = re.findall(r"[a-zäöüß]+", combined)
    english_hits = sum(1 for token in tokens if token in _ENGLISH_WORDS)
    german_hits = sum(1 for token in tokens if token in _GERMAN_WORDS)
    if english_hits >= 2 and english_hits > german_hits * 2:
        return EventLanguage.EN
    if german_hits >= 2 and german_hits >= english_hits:
        return EventLanguage.DE
    return default


def is_online_only(title: str, venue_name: str, address: str | None = None) -> bool:
    """Return True only when an event has no physical venue at all."""

    title_text = title.casefold()
    venue_text = " ".join(part for part in (venue_name, address) if part).casefold()
    combined = f"{title_text} {venue_text}"

    if not any(marker in combined for marker in _ONLINE_MARKERS):
        return False
    if any(marker in combined for marker in _HYBRID_MARKERS):
        return False
    if re.search(r"\b\d{4}\b", venue_text):
        return False
    has_physical_venue = any(
        re.search(rf"(?<!\w){re.escape(marker)}(?!\w)", venue_text)
        for marker in _PHYSICAL_VENUE_MARKERS
    )
    return not has_physical_venue


def categorize_event(
    source: EventSource,
    source_category: str | None,
    title: str,
    description: str | None,
) -> EventCategory:
    """Map an upstream category and text markers to the fixed taxonomy."""

    raw_category = _WHITESPACE_RE.sub(" ", (source_category or "").casefold()).strip()
    if source is not EventSource.EVENTFROG and raw_category in _HSG_TALK_CATEGORIES:
        return EventCategory.TALKS_UNIVERSITY
    direct = _SOURCE_CATEGORY_MAP.get(raw_category)
    if direct is not None:
        return direct

    title_text = title.casefold()
    description_text = (description or "").casefold()

    for category, markers in _CATEGORY_MARKERS:
        if any(marker in title_text for marker in markers):
            return category
    for category, markers in _CATEGORY_MARKERS:
        if any(marker in description_text for marker in markers):
            return category
    return EventCategory.OTHER
