# AGENTS.md — st-gallen-events-kata (Modality B: Software Delivery)

Standalone public event aggregation package for St. Gallen, Switzerland.

## Operational Boundaries

- **Zero-Leakage Invariant:** This package is delivered to the client as source code. It must NEVER import, reference, or depend on internal engines (`extraction-infra`, `target-ops`). Dependencies are 100% public PyPI packages via `uv sync`.
- **Offline TDD Invariant:** All parser, normalizer, and pipeline tests execute strictly offline against static fixtures in `tests/fixtures/`. Never make live network requests during tests or `just check`.
- **JSON Schema Gate:** Output generated at `data/events.json` must validate 100% against `docs/events.schema.json` via `python validate.py`.

## Spec Workflow (Phase 2)

Before implementing code:
1. Read `docs/job_brief.md`, `docs/events.schema.json`, and sanitized fixtures in `tests/fixtures/`.
2. Follow `docs/specs/SPEC_TEMPLATE.md` to author `docs/specs/st_gallen_events.md` with `Status: DRAFT`.
3. Stop and request Operator review. Never implement unapproved code.
4. When Operator approves (`Status: APPROVED`), proceed to Red-State TDD.

## TDD Workflow (Phase 3 & 4)

1. Write failing unit test in `tests/test_parser.py` or `tests/test_pipeline.py`.
2. Run `just test`; confirm expected RED failure.
3. Implement minimal passing code in `src/st_gallen_events_kata/`.
4. Run `just test`; confirm GREEN pass.
5. Pass canonical verification gate `just check`.

## Standard Commands

- `just check`: Full canonical gate (ruff, basedpyright strict, pytest).
- `just test`: Run pytest suite.
- `just sanitize-fixture <file>`: Sanitize offline HTML fixtures in-place.
- `just run`: Run the event aggregation pipeline (`python run.py`).
- `just validate`: Validate `data/events.json` against `docs/events.schema.json`.
