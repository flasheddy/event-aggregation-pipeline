"""Offline tests for St. Gallen event parsing and fixtures."""

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_offline_fixtures_available() -> None:
    assert (FIXTURES_DIR / "unisg_calendar.html").is_file()
    assert (FIXTURES_DIR / "hsg_square.html").is_file()
    assert (FIXTURES_DIR / "eventfrog_events.json").is_file()
