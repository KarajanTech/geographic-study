"""Logs are structured events."""

from __future__ import annotations

import json

import pytest

from app.core.logging import configure_logging, get_logger, is_configured


def test_json_logs_are_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO", json_logs=True)

    get_logger("test").info("viewshed_computed", candidate_id=7, visible_cells=1234)

    payload = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert payload["event"] == "viewshed_computed"
    assert payload["candidate_id"] == 7
    assert payload["visible_cells"] == 1234
    assert payload["level"] == "info"
    assert "timestamp" in payload


def test_level_filters_lower_severity(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="WARNING", json_logs=True)

    logger = get_logger("test")
    logger.info("ignored_event")
    logger.warning("kept_event")

    lines = [line for line in capsys.readouterr().err.strip().splitlines() if line]
    events = [json.loads(line)["event"] for line in lines]
    assert "ignored_event" not in events
    assert "kept_event" in events


def test_configuration_is_idempotent() -> None:
    configure_logging(level="INFO", json_logs=True)
    configure_logging(level="INFO", json_logs=False)

    assert is_configured()
