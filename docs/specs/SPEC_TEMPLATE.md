# Engineering Specification Template

> Keep `Status: DRAFT` until Operator review is complete. Set `APPROVED` only after Operator sign-off.

- **Status:** DRAFT | APPROVED | COMPLETED | SUPERSEDED
- **Owner:** [Author Name / Agent]
- **Target Package(s):** `src/st_gallen_events_kata`
- **Inputs:** `docs/job_brief.md`, `docs/events.schema.json`, `tests/fixtures/`
- **Core Invariant:** Zero internal engine leakage; 100% public PyPI; offline deterministic tests.

---

## 1. Objective & Scope

[What this feature/pipeline delivers, sources covered, output format.]

---

## 2. Ingress & Transport Viability (Phase 0 Evidence)

[Document the HTTP status, headers, and anti-bot classification for each source from the live probe.]

---

## 3. Data Contracts & Schema Mapping

[Define the Pydantic models mapping directly to events.schema.json, enum definitions, ISO 8601 Zurich time formatting.]

---

## 4. Module Layout & Diff Boundaries

| Module Path | Action | Responsibility |
| :--- | :--- | :--- |
| `src/st_gallen_events_kata/models.py` | Create | Pydantic Event and EventList schemas |
| `src/st_gallen_events_kata/eventfrog.py` | Create | Eventfrog REST API client |
| `src/st_gallen_events_kata/typo3_scraper.py` | Create | Shared Unisg & HSG Square Lexbor parser |
| `src/st_gallen_events_kata/deduplicator.py` | Create | Canonical deduplication and priority |
| `src/st_gallen_events_kata/pipeline.py` | Create | Orchestration and file output |
| `run.py` | Create | Single CLI entry point |
| `validate.py` | Create | JSON Schema validation entry point |

---

## 5. Deduplication & Normalization Logic

[Exact deduplication rules: (title, start, venue) key, Eventfrog priority, category taxonomy mapping.]

---

## 6. Test Spec & Offline Fixture Contract

[Describe offline fixtures and unit tests in tests/test_*.py.]

---

## 7. Machine-Checkable Acceptance Criteria

| AC ID | Criterion | Verification Command |
| :--- | :--- | :--- |
| **AC-1** | Output validates against events.schema.json | `just validate` |
| **AC-2** | Deduplication merges same title/start/venue | `just test -k deduplicator` |
| **AC-3** | Static parser extracts >= 40 events from fixtures | `just test -k parser` |
| **AC-4** | Zero internal engine imports | `fish -c "not rg 'extraction_infra' src tests"` |
| **AC-5** | Canonical verification gate passes | `just check` |

---

## 8. Non-Goals & Out of Scope

[Explicitly state what is not built (no database, no paid services, no online-only events).]

---

## 9. Verification Gate Execution

[Commands to verify implementation.]
