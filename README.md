# St. Gallen Events Pipeline

A robust, fault-isolated Python data pipeline that aggregates upcoming physical events in and around St. Gallen, Switzerland, into a single normalized JSON document adhering strictly to Draft 2020-12 JSON Schema (`docs/events.schema.json`).

Designed for direct integration into early-stage activity recommendation services.

---

## Features

- **Multi-Source Aggregation**:
  - **Eventfrog Public API** (`api.eventfrog.net`): Primary source for public concerts, parties, and community events with built-in token-bucket rate limiting (max 30 requests/minute).
  - **University of St. Gallen (Unisg)** (`unisg.ch/...`): Public academic calendar, public lectures, and conferences.
  - **HSG SQUARE** (`hsg-square.ch/...`): Campus dialogue, cultural exhibitions, and workshops.
- **Strict Schema Compliance**: Every output validates 100% against `docs/events.schema.json` via Draft 2020-12 validator.
- **Fault-Isolated Execution**: Each upstream source executes independently. If one source fails, the remaining sources continue. If all sources fail, the previous valid output file is preserved.
- **Intelligent Deduplication**: Cross-source duplicates matching `(title, start, venue)` are merged automatically, prioritizing Eventfrog metadata.
- **Physical Event Enforcement**: Automatically filters out online-only webinars and virtual meetings while preserving hybrid on-premise events.
- **Zero-Leakage Standalone Package**: Uses only standard public PyPI dependencies (`httpx`, `jsonschema`, `pydantic`, `selectolax`). No proprietary frameworks, databases, or external infrastructure required.

---

## Directory Structure

```text
.
├── .github/workflows/
│   └── events.yml              # Scheduled GitHub Actions refresh workflow
├── data/
│   └── events.json             # Canonical output file
├── docs/
│   ├── events.schema.json      # Draft 2020-12 JSON Schema
│   └── specs/                  # Architecture & engineering specifications
├── src/st_gallen_events_kata/
│   ├── deduplicator.py         # Cross-source entity deduplication
│   ├── eventfrog.py            # Eventfrog REST client & rate limiter
│   ├── models.py               # Pydantic data contracts & PipelineConfig
│   ├── normalization.py        # Text sanitization, date/TZ & taxonomy mapping
│   ├── pipeline.py             # Fault-isolated source orchestration
│   └── typo3_scraper.py        # Lexbor CSS card parser (Unisg + HSG Square)
├── tests/
│   ├── fixtures/               # Sanitized offline HTML & JSON payloads
│   ├── test_parser.py          # Offline parser tests
│   └── test_pipeline.py        # Offline pipeline integration tests
├── .env.example                # Sample environment variables
├── justfile                    # Local development task recipes
├── pyproject.toml              # Project configuration and dependencies
├── requirements.txt            # Pinned production dependencies
├── run.py                      # Pipeline CLI entry point
└── validate.py                 # JSON Schema validator CLI
```

---

## Setup & Installation

### Requirements

- Python 3.11 or higher
- (Optional) `uv` for ultra-fast virtualenv management or `just` for task runner convenience.

### Option A: Standard `pip` (Production)

```bash
# 1. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install pinned production dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### Option B: Modern `uv` (Development)

```bash
# Sync all runtime and development tools
uv sync
```

### Environment Configuration

Copy `.env.example` to `.env` and provide your Eventfrog API key:

```bash
cp .env.example .env
```

Edit `.env`:
```ini
EVENTFROG_API_KEY=your_actual_api_key_here
```

> **Note:** If no API key is provided, the pipeline logs a warning and continues with the web scraping sources (Unisg and HSG Square) without crashing.

---

## How to Run

### Live Execution

To execute the live pipeline, fetching events across all sources and writing to `data/events.json`:

```bash
python run.py
```

Or using `just`:
```bash
just run
```

### Offline Execution (Fixtures)

To test the entire aggregation, normalization, deduplication, and export flow completely offline using pre-sanitized fixtures:

```bash
python run.py --offline
```

Or using `just`:
```bash
just run --offline
```

### Custom Output Path and Logging

```bash
python run.py --output /tmp/custom_events.json --log-level DEBUG
```

---

## Schema Validation

Every run of the pipeline produces `data/events.json`. To validate this file against the official Draft 2020-12 schema:

```bash
python validate.py
```

Or using `just`:
```bash
just validate
```

You can also validate custom event files or schemas:
```bash
python validate.py /path/to/events.json --schema docs/events.schema.json
```

---

## Category Mapping Table

Every physical event is classified into one of six standardized categories required by `docs/events.schema.json`:

| Category | Description | Matching Rules & Trigger Keywords |
| :--- | :--- | :--- |
| `nightlife_music` | Concerts, DJ sets, club nights, parties, live music, jazz | `party`, `club`, `konzert`, `concert`, `jazz`, `live music`, `dj` |
| `sports` | Football, sports tournaments, fitness, yoga, running | `sport`, `fussball`, `football`, `match`, `turnier`, `lauf`, `yoga` |
| `culture` | Theatre, film screenings, cinema, art exhibitions, museums | `theater`, `kino`, `film`, `dokfilm`, `cinema@square`, `ausstellung`, `museum`, `kunst`, `bühne` |
| `talks_university`| Lectures, academic panels, symposiums, public talks | `vorlesung`, `antrittsvorlesung`, `symposium`, `tagung`, `kongress`, `kolloquium`, `workshop`, `lecture`, `talk` |
| `food_drinks` | Wine tastings, dinners, brunches, culinary events, apéros | `lunch`, `dinner`, `degustation`, `apéro`, `brunch`, `kulinarik`, `gastronomie`, `food`, `wine` |
| `other` | Miscellaneous physical events not matching above taxonomies | Fallback classification |

Online-only events (`webinar`, `zoom meeting`, `virtuell`) are automatically excluded from the dataset. Hybrid events with physical venues are retained.

---

## Configuration

All pipeline parameters are centralized in `PipelineConfig` within `src/st_gallen_events_kata/models.py`.

### Default Settings

| Parameter | Default Value | Description |
| :--- | :--- | :--- |
| `location_name` | `"St. Gallen"` | Center anchor city |
| `latitude` | `47.4245` | Geographic anchor latitude |
| `longitude` | `9.3767` | Geographic anchor longitude |
| `radius_km` | `15.0` | Event query radius in kilometers |
| `window_days` | `30` | Time horizon for upcoming events |
| `timezone` | `"Europe/Zurich"` | Timezone for ISO 8601 formatting |
| `schedule_cron` | `"0 5 * * 1"` | Scheduled cron expression (Monday 05:00 Zurich) |
| `output_path` | `"data/events.json"` | Default export path |

To adjust defaults, pass a custom `PipelineConfig` instance to `run_pipeline(config=custom_cfg)` in Python.

---

## Automated Refresh (GitHub Actions)

A production-ready GitHub Actions workflow is included at `.github/workflows/events.yml`.

- **Schedule**: Executes automatically every Monday at 05:00 Europe/Zurich (`0 4 * * 1` UTC).
- **Manual Trigger**: Supports on-demand execution via `workflow_dispatch`.
- **Workflow Steps**:
  1. Sets up Python 3.11 and installs pinned dependencies from `requirements.txt`.
  2. Runs `python run.py` using `EVENTFROG_API_KEY` from repository secrets.
  3. Validates the resulting `data/events.json` against `docs/events.schema.json`.
  4. Commits and pushes the updated dataset back to `main` if changes are detected.

### Setup in GitHub:
1. Push this repository to GitHub.
2. In your repository settings, navigate to **Settings > Secrets and variables > Actions**.
3. Create a **New repository secret**:
   - Name: `EVENTFROG_API_KEY`
   - Value: `[Your Eventfrog API Key]`

---

## How to Add a New Source

Adding a new upstream provider (e.g., Stadt St. Gallen city portal or a local venue calendar) requires 4 simple steps:

### 1. Register Source Enum
In `src/st_gallen_events_kata/models.py`, add the source identifier:
```python
class EventSource(StrEnum):
    EVENTFROG = "eventfrog"
    HSG_CALENDAR = "hsg_calendar"
    HSG_SQUARE = "hsg_square"
    MY_NEW_SOURCE = "my_new_source"  # Add this
```

### 2. Implement Collector / Parser
Create `src/st_gallen_events_kata/my_new_source.py`:
```python
from collections.abc import Sequence
from .models import Event, EventCategory, EventSource, to_zurich_iso
from .normalization import clean_text, map_category


def scrape_my_new_source() -> Sequence[Event]:
    # Fetch content and construct Event instances
    events: list[Event] = []
    # ... extraction logic ...
    return events
```

### 3. Register in Pipeline Loader
In `src/st_gallen_events_kata/pipeline.py`:
- Import your new scraper function.
- Add `EventSource.MY_NEW_SOURCE` to `_SOURCE_ORDER`.
- Register the loader in `_build_source_loaders`:
```python
loaders[EventSource.MY_NEW_SOURCE] = lambda: scrape_my_new_source()
```

### 4. Add Offline Fixture and Tests
- Save a sample response to `tests/fixtures/my_new_source.html`.
- Run `just sanitize-fixture tests/fixtures/my_new_source.html`.
- Add unit parser tests to `tests/test_parser.py`.

---

## Development & Verification

The project includes canonical verification recipes in `justfile`:

```bash
# Run complete verification (lint, typecheck, secret scanning, offline unit tests)
just check

# Auto-format source code and markdown
just fmt

# Run offline pytest suite
just test

# Scan for inadvertent secrets or tokens
just secrets
```

All tests execute completely offline without external network dependencies.
