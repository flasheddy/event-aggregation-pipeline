Summary
We are building an early-stage app that suggests activities to existing groups of
friends in St. Gallen, Switzerland. We need a small, reliable Python pipeline that
collects upcoming public events and writes them into one JSON file with a fixed
schema (attached: events.schema.json). We integrate the file into our app ourselves.

SOURCES
1. Eventfrog Public API (api.eventfrog.net) – primary source. Please use your own
   free Public API key for development; in production we use ours.
2. University of St. Gallen public event calendar
   (unisg.ch/de/news/veranstaltungen/veranstaltungskalender/) and HSG SQUARE
   programme (hsg-square.ch/de/programm/) – scraping.
Respect robots.txt, terms of use and rate limits (Eventfrog: max. 30 requests/min).

SCOPE
- All event types, except online-only events. Map every event to one category:
  nightlife_music | sports | culture | talks_university | food_drinks | other
- Location, radius, time window and refresh interval configurable in ONE config
  file (defaults: St. Gallen, 15 km, next 30 days, weekly on Monday 05:00
  Europe/Zurich).
- Python only, no paid services, no database, no hosting.

DELIVERABLES (as ZIP file)
- Python 3.11+ project, runnable with one command: python run.py
- requirements.txt with pinned versions and .env.example (no keys in code)
- Output: data/events.json, validating against the attached JSON Schema
- A validation step (python validate.py) that checks the output against the
  schema; the workflow runs it after every run
- Ready-to-use GitHub Actions workflow (.github/workflows/events.yml) that runs
  the pipeline on the configured schedule and commits the updated file, reading
  the API key from GitHub Secrets
- README: setup, how to run, how to change the config, how to add a source,
  category mapping table
- With each milestone: a real events.json from your last run and a short screen
  recording (max. 3 min) of a full run

EVENT SCHEMA (full definition in the attached events.schema.json)
The file is one JSON object with two keys: "generated_at" (ISO 8601 timestamp of
the run) and "events" (a list of event objects).
Each event:
- id              string   source name + colon + source_id, e.g. eventfrog:12345;
                           stable across runs
- source          string   eventfrog | hsg_calendar | hsg_square
- source_id       string   ID or URL slug from the source
- source_url      string   link to the event page
- title           string
- description     string   plain text, max. 500 characters, nullable
- category        string   one of the six categories above
- start           string   ISO 8601 with offset, Europe/Zurich
- end             string   ISO 8601, nullable
- all_day         boolean
- venue_name      string
- address         string   street, ZIP, city
- latitude        number   nullable
- longitude       number   nullable
- price_min_chf   number   nullable, 0 = free
- price_max_chf   number   nullable
- ticket_url      string   nullable
- language        string   de | en | null
- image_url       string   nullable
- last_seen_at    string   ISO 8601 timestamp of the run

ACCEPTANCE CRITERIA
- events.json validates 100% against the attached JSON Schema
- No duplicate ids; the same event from several sources (same title, start,
  venue) appears only once. When duplicates are merged, keep the Eventfrog version.
- At least 80 unique upcoming events in the 30-day window (we will adjust if the
  sources genuinely have fewer)
- If one source fails, the others still run; the error is logged and the last
  valid file is kept
- Clean, commented code; all code and rights are transferred to us on payment

MILESTONES (fixed price)
- M1 – Friday, 20 November: Eventfrog integration, valid events.json,
  screen recording (50%)
- M2 – Wednesday, 25 November: HSG sources, validation step, GitHub Actions
  workflow, README, final ZIP (50%)
Short status update every 2 days via Upwork chat.
Confidentiality: the project description, code and data must not be shared or reused.
