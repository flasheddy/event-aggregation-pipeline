"""CLI entry point for the multi-source event aggregation pipeline."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

logger = logging.getLogger("event_aggregation_pipeline.run")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect, normalize, deduplicate, and validate multi-source physical events."
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use sanitized fixtures in tests/fixtures instead of network requests.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path (default: data/events.json).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Logging verbosity (default: INFO).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from event_aggregation_pipeline.pipeline import run_pipeline

    try:
        event_list = run_pipeline(offline=args.offline, output_path=args.output)
    except Exception:
        logger.exception("Event pipeline failed")
        return 1

    print(f"Wrote {len(event_list.events)} events (generated_at={event_list.generated_at})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
