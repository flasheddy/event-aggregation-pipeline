"""Validate data/events.json against docs/events.schema.json."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, FormatChecker

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_SCHEMA_PATH = PROJECT_ROOT / "docs" / "events.schema.json"
DEFAULT_EVENTS_PATH = PROJECT_ROOT / "data" / "events.json"


class ValidationFailure(ValueError):
    """Raised when the output document violates the JSON Schema."""


def load_schema(schema_path: Path | str = DEFAULT_SCHEMA_PATH) -> dict[str, object]:
    """Load and self-check the Draft 2020-12 schema."""

    path = Path(schema_path)
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValidationFailure(f"schema at {path} must be a JSON object")
    schema = cast(dict[str, object], raw)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_document(
    document: object,
    schema: dict[str, object] | None = None,
) -> None:
    """Raise ValidationFailure if the document does not match the schema."""

    active_schema = schema if schema is not None else load_schema()
    validator = Draft202012Validator(
        active_schema,
        format_checker=FormatChecker(),
    )
    validation_errors = validator.iter_errors(  # pyright: ignore[reportUnknownMemberType]
        cast(dict[str, Any], document)
    )
    errors = sorted(validation_errors, key=lambda error: error.json_path)
    if errors:
        first = errors[0]
        raise ValidationFailure(f"{first.json_path}: {first.message}") from first


def validate_file(
    events_path: Path | str = DEFAULT_EVENTS_PATH,
    schema_path: Path | str = DEFAULT_SCHEMA_PATH,
) -> dict[str, object]:
    """Load, parse, and validate an events document; return it on success."""

    path = Path(events_path)
    document = _load_json_object(path)
    validate_document(document, load_schema(schema_path))
    return document


def _load_json_object(path: Path) -> dict[str, object]:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationFailure(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValidationFailure(f"{path} must contain a JSON object")
    return cast(dict[str, object], raw)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate an events.json file against docs/events.schema.json."
    )
    parser.add_argument(
        "events",
        nargs="?",
        default=str(DEFAULT_EVENTS_PATH),
        help="events JSON file to validate (default: data/events.json)",
    )
    parser.add_argument(
        "--schema",
        default=str(DEFAULT_SCHEMA_PATH),
        help="JSON Schema file (default: docs/events.schema.json)",
    )
    args = parser.parse_args(argv)

    try:
        document = validate_file(args.events, args.schema)
    except (OSError, ValidationFailure) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    events = document.get("events")
    count = len(cast(list[object], events)) if isinstance(events, list) else 0
    print(f"OK: {count} events validated against {args.schema}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
