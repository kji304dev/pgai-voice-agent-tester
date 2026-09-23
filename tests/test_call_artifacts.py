"""Tests for local call-artifact persistence helpers."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pgai_voice_agent_tester.call_artifacts import (
    build_call_metadata,
    persist_call_artifacts,
    prepare_session_report,
    render_transcript_md,
)


def test_transcript_contains_pgai_and_patient_in_order() -> None:
    history = SimpleNamespace(
        items=[
            SimpleNamespace(role="system", text_content="ignore me"),
            SimpleNamespace(role="user", text_content="Hello, clinic speaking."),
            SimpleNamespace(role="assistant", text_content="Hi, I need an appointment."),
            SimpleNamespace(role="developer", text_content="secret"),
            SimpleNamespace(role="user", text_content="What is your name?"),
            SimpleNamespace(role="assistant", text_content="Carl Smith."),
            SimpleNamespace(role="tool", text_content="not speech"),
        ]
    )

    transcript = render_transcript_md(history)
    assert "system" not in transcript.lower()
    assert "developer" not in transcript.lower()
    assert "secret" not in transcript
    assert "not speech" not in transcript

    assert transcript.index("PGAI:") < transcript.index("PATIENT:")
    assert "Hello, clinic speaking." in transcript
    assert "Hi, I need an appointment." in transcript
    assert "Carl Smith." in transcript

    # Chronological: first PGAI block before second PATIENT name answer.
    first_pgai = transcript.index("Hello, clinic speaking.")
    first_patient = transcript.index("Hi, I need an appointment.")
    second_pgai = transcript.index("What is your name?")
    second_patient = transcript.index("Carl Smith.")
    assert first_pgai < first_patient < second_pgai < second_patient


def test_metadata_contains_scenario_room_job() -> None:
    report = SimpleNamespace(
        room="pgai-01_routine_appointment-abc123",
        room_id="RM_test",
        job_id="AJ_test",
        audio_recording_started_at=100.0,
        started_at=90.0,
        timestamp=200.0,
    )
    metadata = build_call_metadata(
        report=report,
        scenario_id="01_routine_appointment",
        dispatch_id="AD_test",
        sip_call_id=None,
        caller_number="+19793252074",
        destination_number="+18054398008",
        recording_filename="audio.ogg",
    )
    payload = metadata.__dict__
    assert payload["scenario_id"] == "01_routine_appointment"
    assert payload["room_name"] == "pgai-01_routine_appointment-abc123"
    assert payload["room_id"] == "RM_test"
    assert payload["job_id"] == "AJ_test"
    assert payload["dispatch_id"] == "AD_test"
    assert payload["sip_call_id"] is None
    assert payload["recording_filename"] == "audio.ogg"


def test_persist_creates_directory_and_survives_missing_audio(tmp_path: Path) -> None:
    history = SimpleNamespace(
        items=[
            SimpleNamespace(role="user", text_content="Clinic hello"),
            SimpleNamespace(role="assistant", text_content="Patient hello"),
        ]
    )
    report = SimpleNamespace(
        room="pgai-01_routine_appointment-deadbeef",
        room_id="RM_x",
        job_id="AJ_x",
        chat_history=history,
        audio_recording_path=None,
        audio_recording_started_at=None,
        started_at=1.0,
        timestamp=2.0,
    )

    out_dir = persist_call_artifacts(
        report=report,
        scenario_id="01_routine_appointment",
        calls_root=tmp_path,
        dispatch_id="AD_x",
        sip_call_id=None,
        caller_number="+19793252074",
        destination_number="+18054398008",
    )

    assert out_dir == tmp_path / "pgai-01_routine_appointment-deadbeef"
    assert out_dir.is_dir()
    assert not (out_dir / "audio.ogg").exists()

    transcript = (out_dir / "transcript.md").read_text(encoding="utf-8")
    assert "PGAI:\nClinic hello" in transcript
    assert "PATIENT:\nPatient hello" in transcript

    metadata = json.loads((out_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["scenario_id"] == "01_routine_appointment"
    assert metadata["room_name"] == "pgai-01_routine_appointment-deadbeef"
    assert metadata["job_id"] == "AJ_x"
    assert metadata["dispatch_id"] == "AD_x"
    assert metadata["sip_call_id"] is None
    assert metadata["recording_filename"] is None


def test_persist_copies_existing_audio(tmp_path: Path) -> None:
    audio_src = tmp_path / "src-audio.ogg"
    audio_src.write_bytes(b"OggS-fake-audio")
    history = SimpleNamespace(items=[])
    report = SimpleNamespace(
        room="pgai-01_routine_appointment-audio",
        room_id="RM_a",
        job_id="AJ_a",
        chat_history=history,
        audio_recording_path=audio_src,
        audio_recording_started_at=10.0,
        started_at=9.0,
        timestamp=11.0,
    )

    out_dir = persist_call_artifacts(
        report=report,
        scenario_id="01_routine_appointment",
        calls_root=tmp_path / "calls",
    )
    dest = out_dir / "audio.ogg"
    assert dest.is_file()
    assert dest.read_bytes() == b"OggS-fake-audio"
    metadata = json.loads((out_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["recording_filename"] == "audio.ogg"


@pytest.mark.asyncio
async def test_prepare_session_report_closes_recorder_before_report() -> None:
    """RecorderIO must be closed before make_session_report when still recording."""
    events: list[str] = []

    class FakeRecorder:
        def __init__(self) -> None:
            self.recording = True

        async def aclose(self) -> None:
            events.append("aclose")
            self.recording = False

    class FakeCtx:
        def make_session_report(self, session: object | None = None) -> SimpleNamespace:
            events.append("make_session_report")
            recorder = getattr(session, "_recorder_io", None)
            if recorder is not None and getattr(recorder, "recording", False):
                raise RuntimeError(
                    "Cannot create the AgentSession report, the RecorderIO is still recording"
                )
            return SimpleNamespace(room="pgai-test-room", ok=True)

    session = SimpleNamespace(_recorder_io=FakeRecorder())
    report = await prepare_session_report(FakeCtx(), session)

    assert report.ok is True
    assert events == ["aclose", "make_session_report"]
    assert session._recorder_io.recording is False


@pytest.mark.asyncio
async def test_prepare_session_report_skips_aclose_when_not_recording() -> None:
    events: list[str] = []

    class FakeRecorder:
        recording = False

        async def aclose(self) -> None:
            events.append("aclose")

    class FakeCtx:
        def make_session_report(self, session: object | None = None) -> SimpleNamespace:
            events.append("make_session_report")
            return SimpleNamespace(ok=True)

    session = SimpleNamespace(_recorder_io=FakeRecorder())
    report = await prepare_session_report(FakeCtx(), session)

    assert report.ok is True
    assert events == ["make_session_report"]
