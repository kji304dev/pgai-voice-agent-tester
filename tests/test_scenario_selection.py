"""Tests for per-job scenario selection via dispatch metadata."""

from __future__ import annotations

import pytest
from livekit.agents import Agent

from pgai_voice_agent_tester.patient import (
    PATIENT_INSTRUCTIONS,
    ScenarioPatientAgent,
    create_patient_agent_from_selection,
    encode_scenario_dispatch_metadata,
    resolve_scenario_selection,
)
from pgai_voice_agent_tester.scenarios import ScenarioError


def test_dispatch_metadata_takes_precedence_over_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PGAI_SCENARIO_ID", "02_rescheduling")
    metadata = encode_scenario_dispatch_metadata("01_routine_appointment")

    selection = resolve_scenario_selection(job_metadata=metadata)
    assert selection.source == "dispatch_metadata"
    assert selection.scenario_id == "01_routine_appointment"

    agent = create_patient_agent_from_selection(selection)
    assert isinstance(agent, ScenarioPatientAgent)
    assert agent.scenario.id == "01_routine_appointment"
    assert "Carl Smith" in agent.instructions
    assert "Jordan Hale" not in agent.instructions


def test_valid_scenario_01_resolves_from_dispatch_metadata() -> None:
    metadata = encode_scenario_dispatch_metadata("01_routine_appointment")
    selection = resolve_scenario_selection(
        job_metadata=metadata,
        environ={},  # no env fallback available
    )
    assert selection.scenario_id == "01_routine_appointment"
    assert selection.source == "dispatch_metadata"

    agent = create_patient_agent_from_selection(selection)
    assert isinstance(agent, ScenarioPatientAgent)
    assert agent.scenario.id == "01_routine_appointment"
    assert "stomach pain" in agent.instructions


def test_invalid_explicit_scenario_fails_clearly() -> None:
    metadata = encode_scenario_dispatch_metadata("does_not_exist")
    selection = resolve_scenario_selection(job_metadata=metadata, environ={})
    assert selection.source == "dispatch_metadata"
    assert selection.scenario_id == "does_not_exist"

    with pytest.raises(ScenarioError, match="not found"):
        create_patient_agent_from_selection(selection)


def test_malformed_dispatch_metadata_fails_clearly() -> None:
    with pytest.raises(ValueError, match="Invalid dispatch metadata JSON"):
        resolve_scenario_selection(job_metadata="{not-json", environ={})

    with pytest.raises(ValueError, match="scenario_id"):
        resolve_scenario_selection(job_metadata='{"other":"x"}', environ={})


def test_absent_metadata_uses_environment_then_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PGAI_SCENARIO_ID", "02_rescheduling")
    selection = resolve_scenario_selection(job_metadata="")
    assert selection.source == "environment"
    assert selection.scenario_id == "02_rescheduling"
    agent = create_patient_agent_from_selection(selection)
    assert isinstance(agent, ScenarioPatientAgent)
    assert agent.scenario.id == "02_rescheduling"

    monkeypatch.delenv("PGAI_SCENARIO_ID", raising=False)
    fallback = resolve_scenario_selection(job_metadata=None, environ={})
    assert fallback.source == "fallback"
    assert fallback.scenario_id is None
    fallback_agent = create_patient_agent_from_selection(fallback)
    assert isinstance(fallback_agent, Agent)
    assert not isinstance(fallback_agent, ScenarioPatientAgent)
    assert fallback_agent.instructions == PATIENT_INSTRUCTIONS
