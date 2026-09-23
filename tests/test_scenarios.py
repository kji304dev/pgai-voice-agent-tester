"""Tests for scenario loading and patient instruction generation."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from livekit.agents import Agent
from livekit.agents.llm import ChatMessage

from pgai_voice_agent_tester.patient import (
    PATIENT_INSTRUCTIONS,
    ScenarioPatientAgent,
    build_patient_instructions,
    create_patient_agent,
    resolve_patient_instructions,
    utterance_satisfies_beat,
)
from pgai_voice_agent_tester.scenarios import ScenarioError, load_scenario, scenarios_dir


def test_load_valid_scenario() -> None:
    scenario = load_scenario("01_routine_appointment")
    assert scenario.id == "01_routine_appointment"
    assert scenario.patient["name"] == "Carl Smith"
    assert scenario.goal
    assert scenario.conversation_beats
    assert "stomach pain" in scenario.conversation_beats[0]


def test_invalid_scenario_id_raises_clear_error() -> None:
    with pytest.raises(ScenarioError, match="not found") as exc_info:
        load_scenario("does_not_exist")
    message = str(exc_info.value)
    assert "does_not_exist" in message
    assert "Available:" in message


def test_patient_instructions_include_scenario_details() -> None:
    scenario = load_scenario("01_routine_appointment")
    instructions = build_patient_instructions(scenario, beat_index=0)
    assert "Carl Smith" in instructions
    assert "1999-08-01" in instructions
    assert "stomach pain" in instructions
    assert "Ask to make an appointment because of stomach pain." in instructions
    assert "never mention" in instructions.lower()
    assert "Jordan Hale" not in instructions
    # Later beats must not be visible yet.
    assert "Only cocaine" not in instructions
    assert "I have a favor" not in instructions
    assert "mark_current_beat_complete" not in instructions


def test_later_beats_are_gated_until_advanced() -> None:
    scenario = load_scenario("02_rescheduling")
    beat0 = build_patient_instructions(scenario, beat_index=0)
    beat1 = build_patient_instructions(scenario, beat_index=1)
    beat3 = build_patient_instructions(scenario, beat_index=3)

    assert "Friday at 10 AM with Dr. Patel" in beat0
    assert "next Tuesday morning" not in beat0
    assert "2:30 PM as the preferred time" not in beat0

    assert "next Tuesday morning" in beat1
    assert "Already covered earlier" in beat1
    assert "2:30 PM as the preferred time" not in beat1

    assert "2:30 PM as the preferred time" in beat3
    assert "Tuesday morning" in beat3  # completed beat referenced


def test_utterance_satisfies_current_beat_only() -> None:
    scenario = load_scenario("02_rescheduling")
    patient = scenario.patient
    beats = scenario.conversation_beats

    assert utterance_satisfies_beat(
        "I already have an appointment this Friday at 10 AM with Dr. Patel and need to reschedule.",
        beats[0],
        patient,
    )
    assert not utterance_satisfies_beat(
        "My date of birth is April 22, 1987.",
        beats[0],
        patient,
    )
    assert not utterance_satisfies_beat(
        "Can we do Tuesday morning instead?",
        beats[0],
        patient,
    )

    assert utterance_satisfies_beat(
        "I'd like to move it to next Tuesday morning.",
        beats[1],
        patient,
    )
    assert not utterance_satisfies_beat(
        "Afternoon works better for me.",
        beats[1],
        patient,
    )

    assert utterance_satisfies_beat(
        "Actually afternoon works better.",
        beats[2],
        patient,
    )
    assert utterance_satisfies_beat(
        "Let's make it 2:30 PM.",
        beats[3],
        patient,
    )
    assert not utterance_satisfies_beat(
        "Let's make it 2:30 PM.",
        beats[0],
        patient,
    )


@pytest.mark.asyncio
async def test_scenario_patient_agent_advances_from_patient_utterances() -> None:
    scenario = load_scenario("02_rescheduling")
    agent = ScenarioPatientAgent(scenario)
    assert agent.beat_index == 0
    assert "Friday at 10 AM with Dr. Patel" in agent.instructions
    assert "2:30 PM as the preferred time" not in agent.instructions

    # Unrelated profile answer must not advance.
    agent._on_conversation_item_added(
        SimpleNamespace(
            item=ChatMessage(
                role="assistant",
                content=["My date of birth is April 22, 1987."],
            )
        )
    )
    await asyncio_sleep_briefly()
    assert agent.beat_index == 0

    # Matching patient utterance advances exactly one beat.
    agent._on_conversation_item_added(
        SimpleNamespace(
            item=ChatMessage(
                role="assistant",
                content=[
                    "I already have an appointment Friday at 10 AM with Dr. Patel "
                    "and need to reschedule."
                ],
            )
        )
    )
    await asyncio_sleep_briefly()
    assert agent.beat_index == 1
    assert "next Tuesday morning" in agent.instructions
    assert "2:30 PM as the preferred time" not in agent.instructions

    # Same later-beat content still cannot skip ahead.
    agent._on_conversation_item_added(
        SimpleNamespace(
            item=ChatMessage(role="assistant", content=["Let's do 2:30 PM."])
        )
    )
    await asyncio_sleep_briefly()
    assert agent.beat_index == 1

    agent._on_conversation_item_added(
        SimpleNamespace(
            item=ChatMessage(
                role="assistant",
                content=["Please move it to next Tuesday morning."],
            )
        )
    )
    await asyncio_sleep_briefly()
    assert agent.beat_index == 2


@pytest.mark.asyncio
async def test_advance_beat_caps_at_final_index() -> None:
    scenario = load_scenario("02_rescheduling")
    agent = ScenarioPatientAgent(scenario)
    while await agent.advance_beat():
        pass
    assert agent.beat_index == len(scenario.conversation_beats) - 1
    assert await agent.advance_beat() is False


def test_fallback_when_no_scenario_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PGAI_SCENARIO_ID", raising=False)
    instructions = resolve_patient_instructions()
    assert instructions == PATIENT_INSTRUCTIONS
    assert "Jordan Hale" in instructions

    agent = create_patient_agent()
    assert isinstance(agent, Agent)
    assert not isinstance(agent, ScenarioPatientAgent)
    assert agent.instructions == PATIENT_INSTRUCTIONS


def test_resolve_uses_env_scenario(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PGAI_SCENARIO_ID", "02_rescheduling")
    instructions = resolve_patient_instructions()
    assert "Maya Thompson" in instructions
    assert "Jordan Hale" not in instructions

    agent = create_patient_agent()
    assert isinstance(agent, ScenarioPatientAgent)
    assert agent.scenario.id == "02_rescheduling"
    assert agent.beat_index == 0


def test_all_scenario_json_files_validate() -> None:
    root = scenarios_dir()
    paths = sorted(root.glob("*.json"))
    assert len(paths) == 10
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        scenario = load_scenario(data["id"])
        assert scenario.id == data["id"]
        assert Path(path).stem.startswith(scenario.id.split("_")[0]) or scenario.id in path.stem


async def asyncio_sleep_briefly() -> None:
    import asyncio

    await asyncio.sleep(0.05)
