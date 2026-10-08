"""Shared fixture data for agent tests."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def examples() -> dict:
    """Load the checked-in deterministic examples."""

    path = Path(__file__).resolve().parents[1] / "example_data.json"
    return json.loads(path.read_text(encoding="utf-8"))
