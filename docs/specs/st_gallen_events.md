# Engineering Specification: St. Gallen Public Event Aggregation Pipeline

> Keep `Status: DRAFT` until Operator review is complete. Set `APPROVED` only after Operator sign-off.

- **Status:** APPROVED
- **Owner:** Agent (Modality B Software Delivery)
- **Target Package(s):** `src/st_gallen_events_kata`
- **Inputs:** `docs/job_brief.md`, `docs/events.schema.json`, `tests/fixtures/`
- **Core Invariant:** Zero internal engine leakage; 100% public PyPI; offline deterministic tests.

---

## 1. Objective & Scope

Deliver a standalone, fault-tolerant Python 3.11+ aggregation pipeline (`src/st_gallen_events_kata`) that collects upcoming in-person public events in and around St. Gallen, Switzerland, normalizes and deduplicates them across sources, and writes a single JSON document to `data/events.json` validating 100% against `docs/events.schema.json` (JSON Schema Draft 2020-12).

### Covered Sources

1. **Eventfrog Public API (`eventfrog`):** Primary structured REST source (`https://api.eventfrog.net`), authenticated via a free Public API key (`EVENTFROG_API_KEY` environment variable) and rate-limited to at most 30 requests/minute.
2. **University of St. Gallen Event Calendar (`hsg_calendar`):** Server-rendered TYPO3 CMS HTML calendar (`https://www.unisg.ch/de/news/veranstaltungen/veranstaltungskalender/`).
3. **HSG SQUARE Programme (`hsg_square`):** Server-rendered TYPO3 CMS HTML programme (`https://www.hsg-square.ch/de/programm/`).

### Operational Parameters & Configurability

- **Single Configuration Contract:** Location (`St. Gallen`, `47.4245, 9.3767`), search radius (`15 km`), forward time window (`30 days`), timezone (`Europe/Zurich`), and refresh schedule (`weekly on Monday 05:00 Europe/Zurich`, cron `0 5 * * 1`) are centralized in one configuration object/file.
- **Fault Isolation:** Each source adapter executes independently. If one source fails (network timeout, HTTP 5xx, or upstream schema drift), the remaining sources still run and the error is logged. If all sources fail or yield zero valid events during a live run, the previous valid `data/events.json` is preserved.
- **Entry Points:**
  - `python run.py`: Runs the aggregation pipeline and writes `data/events.json`.
  - `python validate.py`: Validates `data/events.json` against `docs/events.schema.json`.

---

## 2. Ingress & Transport Viability (Phase 0 Evidence)

| Source ID      | Endpoint / Target URL                                                  | HTTP Status | Content-Type               | Anti-Bot / WAF Classification                                           | Rate Limit & Transport Policy                                                                                                                                                       |
| :------------- | :--------------------------------------------------------------------- | :---------- | :------------------------- | :---------------------------------------------------------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `eventfrog`    | `https://api.eventfrog.net/v1/events`                                  | `200 OK`    | `application/json`         | None (Public REST API; Bearer / API Key auth via `EVENTFROG_API_KEY`)   | Max 30 requests/min (`>= 2.0s` interval between requests); `httpx.Client` with 15s timeout; offline fallback to fixture/cached response when no API key is configured in local dev. |
| `hsg_calendar` | `https://www.unisg.ch/de/news/veranstaltungen/veranstaltungskalender/` | `200 OK`    | `text/html; charset=utf-8` | None (TYPO3 CMS `tx-cs2-events` SSR HTML; `meta robots="index,follow"`) | Polite sequential pagination (`?page=N`) via `httpx.Client`, `1.0s` delay between pages, standard User-Agent header.                                                                |
| `hsg_square`   | `https://www.hsg-square.ch/de/programm/`                               | `200 OK`    | `text/html; charset=utf-8` | None (TYPO3 CMS `tx-cs2-events` SSR HTML; `meta robots="index,follow"`) | Polite sequential pagination (`?page=N`) via `httpx.Client`, `1.0s` delay between pages, standard User-Agent header.                                                                |

### Sanitized Offline Fixtures (`tests/fixtures/`)

- `tests/fixtures/eventfrog_events.json`: Sanitized Eventfrog JSON payload (2 representative St. Gallen events with location, coordinates, CHF pricing, ticket URLs, and images).
- `tests/fixtures/unisg_calendar.html`: Sanitized TYPO3 HTML document from `unisg.ch` containing 10 `.event-item` cards across categories (`Öffentliche Vorlesungen`, `Öffentliche Veranstaltungen`), single-day (`etype-0`) and multi-day (`etype-1`) formats, and pagination metadata (`ul.cs2events-pagination`, pages 1–9).
- `tests/fixtures/hsg_square.html`: Sanitized TYPO3 HTML document from `hsg-square.ch` containing 10 `.event-item` cards (including cross-listed events shared with `unisg_calendar.html`) and pagination metadata (`ul.cs2events-pagination`, pages 1–2).

---

## 3. Data Contracts & Schema Mapping

All records are validated using Pydantic v2 (`pydantic>=2.8.0`) in `src/st_gallen_events_kata/models.py` and verified against `docs/events.schema.json` using `jsonschema` (`Draft202012Validator` with format checking enabled).

### Enum Definitions

```python
class EventSource(StrEnum):
    EVENTFROG = "eventfrog"
    HSG_CALENDAR = "hsg_calendar"
    HSG_SQUARE = "hsg_square"


class EventCategory(StrEnum):
    NIGHTLIFE_MUSIC = "nightlife_music"
    SPORTS = "sports"
    CULTURE = "culture"
    TALKS_UNIVERSITY = "talks_university"
    FOOD_DRINKS = "food_drinks"
    OTHER = "other"


class EventLanguage(StrEnum):
    DE = "de"
    EN = "en"
```

### Pydantic Models (`Event` & `EventList`)

| Field           | JSON Schema Type & Constraints                                                                       | Pydantic Type & Validation Rule                                                                                |
| :-------------- | :--------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------- |
| `id`            | `string`, pattern `^(eventfrog\|hsg_calendar\|hsg_square):.+$`                                       | `str = Field(pattern=r"^(eventfrog\|hsg_calendar\|hsg_square):.+$")`; constructed as `f"{source}:{source_id}"` |
| `source`        | `string`, enum `["eventfrog", "hsg_calendar", "hsg_square"]`                                         | `EventSource`                                                                                                  |
| `source_id`     | `string`, `minLength: 1`                                                                             | `str = Field(min_length=1)`                                                                                    |
| `source_url`    | `string`, `format: "uri"`, pattern `^https?://`                                                      | `str = Field(pattern=r"^https?://\S+$")`                                                                       |
| `title`         | `string`, `minLength: 1`, `maxLength: 200`                                                           | `str = Field(min_length=1, max_length=200)`                                                                    |
| `description`   | `["string", "null"]`, `maxLength: 500`, plain text                                                   | `str \| None = Field(default=None, max_length=500)` (HTML tags and soft hyphens `\u00ad` stripped)             |
| `category`      | `string`, enum of 6 categories                                                                       | `EventCategory`                                                                                                |
| `start`         | `string`, `format: "date-time"`, pattern `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?([+-]\d{2}:\d{2})$` | `str` formatted in `ZoneInfo("Europe/Zurich")` with explicit `+01:00` / `+02:00` offset                        |
| `end`           | `["string", "null"]`, `format: "date-time"`, same pattern                                            | `str \| None = None` formatted in `ZoneInfo("Europe/Zurich")` with explicit offset                             |
| `all_day`       | `boolean`                                                                                            | `bool`                                                                                                         |
| `venue_name`    | `string`, `minLength: 1`                                                                             | `str = Field(min_length=1)`                                                                                    |
| `address`       | `string`, `minLength: 1` (`Street, ZIP, city`)                                                       | `str = Field(min_length=1)`                                                                                    |
| `latitude`      | `["number", "null"]`, `[-90, 90]`                                                                    | `float \| None = Field(default=None, ge=-90.0, le=90.0)`                                                       |
| `longitude`     | `["number", "null"]`, `[-180, 180]`                                                                  | `float \| None = Field(default=None, ge=-180.0, le=180.0)`                                                     |
| `price_min_chf` | `["number", "null"]`, `minimum: 0`                                                                   | `float \| None = Field(default=None, ge=0.0)` (`0.0` = free, `None` = unknown)                                 |
| `price_max_chf` | `["number", "null"]`, `minimum: 0`                                                                   | `float \| None = Field(default=None, ge=0.0)`                                                                  |
| `ticket_url`    | `["string", "null"]`, `format: "uri"`, `^https?://`                                                  | `str \| None = Field(default=None, pattern=r"^https?://\S+$")`                                                 |
| `language`      | `["string", "null"]`, enum `["de", "en", null]`                                                      | `EventLanguage \| None = None`                                                                                 |
| `image_url`     | `["string", "null"]`, `format: "uri"`, `^https?://`                                                  | `str \| None = Field(default=None, pattern=r"^https?://\S+$")`                                                 |
| `last_seen_at`  | `string`, `format: "date-time"`                                                                      | `str` ISO 8601 timestamp with `Europe/Zurich` offset                                                           |

`Event` and `EventList` both set `model_config = ConfigDict(extra="forbid")` to enforce `"additionalProperties": false`.

### ISO 8601 `Europe/Zurich` Formatting Rules

- All timestamps (`generated_at`, `start`, `end`, `last_seen_at`) use `zoneinfo.ZoneInfo("Europe/Zurich")` and `.isoformat(timespec="seconds")`, producing `YYYY-MM-DDTHH:MM:SS+01:00` (CET) or `YYYY-MM-DDTHH:MM:SS+02:00` (CEST).
- For all-day or timeless events on `unisg.ch` / `hsg-square.ch`:
  - Single-day without clock times (e.g., `23.11.2026`): `all_day = True`, `start = "2026-11-23T00:00:00+01:00"`, `end = None`.
  - Multi-day range (`etype-1`, e.g., `18.11. - 20.11.2026`): `all_day = True`, `start = "2026-11-18T00:00:00+01:00"`, `end = "2026-11-20T23:59:59+01:00"`.
  - Single-day where start and end clock times are identical (e.g., `18:15 - 18:15`): `all_day = False`, `start = "2026-11-24T18:15:00+01:00"`, `end = None`.

---

## 4. Module Layout & Diff Boundaries

| Module Path                                  | Action | Responsibility                                                                                                        |
| :------------------------------------------- | :----- | :-------------------------------------------------------------------------------------------------------------------- |
| `src/st_gallen_events_kata/models.py`        | Create | Pydantic `Event`, `EventList`, `PipelineConfig` schemas, enums, and Zurich ISO 8601 helpers                           |
| `src/st_gallen_events_kata/eventfrog.py`     | Create | Eventfrog REST API client, rate limiter (max 30 req/min), and JSON record parser                                      |
| `src/st_gallen_events_kata/typo3_scraper.py` | Create | Shared Unisg (`hsg_calendar`) & HSG Square (`hsg_square`) `selectolax.lexbor` HTML parser and HTTP pagination scraper |
| `src/st_gallen_events_kata/deduplicator.py`  | Create | Canonical `(title, start, venue)` and `id` deduplication with Eventfrog priority                                      |
| `src/st_gallen_events_kata/pipeline.py`      | Create | Source orchestration, fault isolation, last-valid-file preservation, and `data/events.json` writer                    |
| `run.py`                                     | Create | Single CLI entry point executing the aggregation pipeline                                                             |
| `validate.py`                                | Create | JSON Schema validation entry point checking `data/events.json` against `docs/events.schema.json`                      |

---

## 5. Deduplication & Normalization Logic

### 5.1 Canonical Deduplication Rules (`deduplicator.py`)

1. **Priority Order:**
   - `EventSource.EVENTFROG`: Priority `0` (highest — always kept when merged)
   - `EventSource.HSG_SQUARE`: Priority `1`
   - `EventSource.HSG_CALENDAR`: Priority `2`
2. **Primary ID Deduplication:**
   - No duplicate `event.id` values may appear in `events`.
3. **Cross-Source Semantic Deduplication Key:**
   - Key tuple: `(norm_title, norm_start, norm_venue)` where:
     - `norm_title`: `re.sub(r"\s+", " ", title.strip().lower())`
     - `norm_start`: `start` normalized to `Europe/Zurich` minute precision (`YYYY-MM-DDTHH:MM`)
     - `norm_venue`: `re.sub(r"\s+", " ", venue_name.strip().lower())`
   - Events are sorted deterministically by source priority (`eventfrog` first) before deduplication, or replaced in-place when a higher-priority source matches an existing `(norm_title, norm_start, norm_venue)` key.
   - Final output list is sorted chronologically by `(start, id)`.

### 5.2 Category Taxonomy Mapping

Every event is mapped deterministically to one of the six schema categories:

| Target `EventCategory` | Source Category / Keyword Rules                                                                                                                                                                                                                                               |
| :--------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `nightlife_music`      | Eventfrog `nightlife_music`, `konzerte`, `musik`, `party`, `jazz`, `club`, `dj`; or title/description keywords (`concert`, `konzert`, `jazz`, `live music`, `party`).                                                                                                         |
| `sports`               | Eventfrog `sports`, `sport`, `fussball`; or title/description keywords (`sport`, `fussball`, `match`, `turnier`, `lauf`, `yoga`).                                                                                                                                             |
| `culture`              | Eventfrog `culture`, `kultur`, `theater`, `film`, `kino`, `kunst`, `museum`; or HSG `Öffentliche Veranstaltungen` matching cultural markers (`cinema@square`, `film`, `dokfilm`, `artists in residence`, `bühne`, `kunst`, `theater`, `konzert`, `ausstellung`).              |
| `talks_university`     | HSG `Öffentliche Vorlesungen`, `Kongresse und Tagungen`, `Info-Veranstaltungen`; or HSG `Öffentliche Veranstaltungen` with academic/lecture markers (`vorlesung`, `antrittsvorlesung`, `symposium`, `jour fixe`, `forum`, `kolloquium`, `seminar`, `workshop`, `diskussion`). |
| `food_drinks`          | Eventfrog `food_drinks`, `gastronomie`, `kulinarik`; or title/description keywords (`lunch`, `dinner`, `degustation`, `brunch`, `apéro`, `food`, `wine`).                                                                                                                     |
| `other`                | Fallback for any event not matching the above rules (e.g., general community/meditation gatherings).                                                                                                                                                                          |

### 5.3 Venue, Address, Language & Online-Only Normalization (`typo3_scraper.py`)

- **Online-Only Exclusion:** Events whose raw venue or title indicates exclusively online attendance (`"online"`, `"onlineseminar"`, `"webinar"`, `"zoom-meeting"`) without a physical location are filtered out. Hybrid events with a physical room (e.g., `"Universität St.Gallen, Raum A 01-011 und online"`) are retained as in-person events.
- **Venue & Address Extraction from TYPO3 `Ort:` Field:**
  - Split the `Ort:` HTML container on `<br>` tags and strip whitespace from each non-empty line.
  - First line becomes `venue_name` (e.g., `"Festsaal St.Katharinen"`, `"SQUARE, Raum Vadian"`, `"Universität St.Gallen, Raum A 09-011"`).
  - If additional lines are present:
    - If they contain a street and/or postal code (`\b\d{4}\b`), join them with `", "` as `address` (appending `"9000 St. Gallen"` if only a building name like `"Bibliotheksgebäude"` or `"Audimax"` is given).
  - If only a single line is present:
    - If `venue_name` starts with `"SQUARE"` (case-insensitive): `address = "Guisanstrasse 20, 9010 St. Gallen"`.
    - Otherwise (HSG campus rooms/buildings): `address = "Dufourstrasse 50, 9000 St. Gallen"`.
- **Language Detection:**
  - Inspect speaker/metadata lines (`ReferentIn` / `Referenten`) and description: if `"Event in English"` or `"Events in English"` (without `"und Deutsch"`) is present, or English-only text is detected, set `language = EventLanguage.EN`; if `"Deutsch"` or German text is present, set `language = EventLanguage.DE` (default `EventLanguage.DE` for `/de/` calendar pages).
- **Description Cleaning:**
  - Extract plain text via `selectolax.lexbor`, remove soft hyphens (`\u00ad`), replace non-breaking spaces (`\xa0`) with standard spaces, collapse whitespace runs, and truncate to at most 500 characters (preserving word boundary with `...` if > 500 chars).

---

## 6. Test Spec & Offline Fixture Contract

All tests in `tests/` execute 100% offline against `tests/fixtures/` with zero network I/O.

### `tests/test_parser.py`

- **`test_offline_fixtures_available`:** Verifies `unisg_calendar.html`, `hsg_square.html`, and `eventfrog_events.json` exist in `tests/fixtures/`.
- **`test_parse_eventfrog_fixture`:** Parses `tests/fixtures/eventfrog_events.json` and verifies 2 `Event` instances (`eventfrog:102938475`, `eventfrog:554433221`), CHF prices, coordinates, and `Europe/Zurich` timestamps.
- **`test_parse_unisg_calendar_fixture`:** Parses `tests/fixtures/unisg_calendar.html` and verifies all 10 events, including single-day timed events, multi-day `etype-1` (`Artists in Residence: Origen`), multiline `Ort:` addresses (`Festsaal St.Katharinen`, `Akademikerhaus`), and pagination link discovery.
- **`test_parse_hsg_square_fixture`:** Parses `tests/fixtures/hsg_square.html` and verifies all 10 events, including timeless single-day (`KI Jour fixe @ SQUARE`), identical start/end time handling (`cinema@SQUARE: A Minecraft Movie`), soft-hyphen stripping, and language extraction (`24. DocNet Symposium` -> `en`).
- **`test_static_parser_extracts_at_least_40_events_across_fixture_pages`:** Verifies the static parser extracts `>= 40` events across multi-page offline fixture batches (e.g., 2 pages of `unisg_calendar.html` + 2 pages of `hsg_square.html` + `eventfrog_events.json` = 42 events), satisfying `AC-3`.
- **`test_online_only_events_excluded`:** Verifies synthetic HTML/JSON items with `Ort: Online` or `Onlineseminar` are filtered out while hybrid rooms (`Raum A 01-011 und online`) are retained.

### `tests/test_pipeline.py`

- **`test_deduplicator_merges_same_title_start_venue_with_eventfrog_priority`:** Verifies that duplicate events sharing `(title, start, venue_name)` across `hsg_calendar`, `hsg_square`, and `eventfrog` collapse into a single event and preserve the `eventfrog` record when present (`AC-2`).
- **`test_deduplicator_cross_source_hsg_fixtures`:** Verifies that the 4 overlapping events between `unisg_calendar.html` and `hsg_square.html` (`Klimagerechtigkeit`, `cinema@SQUARE: Tetris`, `SanktGaller Gesundheitsforum`, `Artists in Residence: Origen`) deduplicate cleanly from 20 raw HTML events down to 16 unique HTML events (+ 2 Eventfrog = 18 unique events).
- **`test_pipeline_offline_end_to_end_and_schema_validation`:** Runs the pipeline offline into a temporary `events.json` and validates 100% compliance against `docs/events.schema.json` via `validate.py` (`AC-1`).
- **`test_pipeline_fault_isolation_and_last_valid_file_preservation`:** Simulates a single-source failure (confirming remaining sources still produce valid output) and a total-source failure (confirming the existing valid `events.json` is preserved).

---

## 7. Machine-Checkable Acceptance Criteria

| AC ID    | Criterion                                         | Verification Command                            |
| :------- | :------------------------------------------------ | :---------------------------------------------- |
| **AC-1** | Output validates against events.schema.json       | `just validate`                                 |
| **AC-2** | Deduplication merges same title/start/venue       | `just test -k deduplicator`                     |
| **AC-3** | Static parser extracts >= 40 events from fixtures | `just test -k parser`                           |
| **AC-4** | Zero internal engine imports                      | `fish -c "not rg 'extraction_infra' src tests"` |
| **AC-5** | Canonical verification gate passes                | `just check`                                    |

---

## 8. Non-Goals & Out of Scope

- **No Internal Engine Dependencies:** Never import or reference `extraction-infra`, `target-ops`, or any non-PyPI internal packages.
- **No Database or Persistent Storage:** Output is strictly a flat JSON file (`data/events.json`).
- **No Paid Services or Headless Browsers:** All HTTP fetching uses `httpx` and all HTML parsing uses `selectolax.lexbor`.
- **No Online-Only Events:** Webinars and virtual-only listings are excluded.
- **No Phase 3 Implementation in Phase 2:** Source code under `src/` and `tests/` is not modified until Operator approves this specification (`Status: APPROVED`).

---

## 9. Verification Gate Execution

Once Operator approves this specification and TDD implementation (Phases 3 & 4) is complete, execute:

```fish
just test
just run --offline
just validate
just check
```
