"""Tests for outbound-call configuration helpers (no real phone calls)."""

from __future__ import annotations

import pytest

from pgai_voice_agent_tester.agent_config import LIVEKIT_AGENT_NAME
from pgai_voice_agent_tester.outbound import (
    DEFAULT_OUTBOUND_TRUNK_ID,
    DEFAULT_PGAI_CALLER_NUMBER,
    DEFAULT_PGAI_PHONE_NUMBER,
    load_outbound_config,
)
from pgai_voice_agent_tester.patient import encode_scenario_dispatch_metadata


def test_load_outbound_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LIVEKIT_OUTBOUND_TRUNK_ID", raising=False)
    monkeypatch.delenv("PGAI_PHONE_NUMBER", raising=False)
    monkeypatch.delenv("PGAI_CALLER_NUMBER", raising=False)
    monkeypatch.setenv("PGAI_SCENARIO_ID", "01_routine_appointment")

    config = load_outbound_config()
    assert config.trunk_id == DEFAULT_OUTBOUND_TRUNK_ID
    assert config.phone_number == DEFAULT_PGAI_PHONE_NUMBER
    assert config.caller_number == DEFAULT_PGAI_CALLER_NUMBER
    assert config.scenario_id == "01_routine_appointment"
    assert config.agent_name == LIVEKIT_AGENT_NAME
    assert config.room_name.startswith("pgai-01_routine_appointment-")


def test_load_outbound_config_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVEKIT_OUTBOUND_TRUNK_ID", "ST_custom")
    monkeypatch.setenv("PGAI_PHONE_NUMBER", "+15551234567")
    monkeypatch.setenv("PGAI_CALLER_NUMBER", "+15557654321")
    monkeypatch.setenv("PGAI_SCENARIO_ID", "02_rescheduling")

    config = load_outbound_config(room_name="pgai-fixed-room")
    assert config.trunk_id == "ST_custom"
    assert config.phone_number == "+15551234567"
    assert config.caller_number == "+15557654321"
    assert config.scenario_id == "02_rescheduling"
    assert config.room_name == "pgai-fixed-room"


def test_load_outbound_config_rejects_invalid_phone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PGAI_PHONE_NUMBER", raising=False)
    with pytest.raises(ValueError, match="E.164"):
        load_outbound_config(phone_number="8054398008")


def test_outbound_config_scenario_encodes_dispatch_metadata() -> None:
    config = load_outbound_config(scenario_id="01_routine_appointment")
    assert config.scenario_id == "01_routine_appointment"
    metadata = encode_scenario_dispatch_metadata(config.scenario_id)
    assert metadata == '{"scenario_id":"01_routine_appointment"}'
