"""Persist local call artifacts from LiveKit SessionReport data."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("pgai-voice-agent-tester.call_artifacts")

SPEAKER_LABELS = {
    "user": "PGAI",
    "assistant": "PATIENT",
}


def calls_dir() -> Path:
    """Project-root ``calls/`` directory for durable per-call artifacts."""
    return Path(__file__).resolve().parents[2] / "calls"


async def prepare_session_report(ctx: Any, session: Any) -> Any:
    """Finalize RecorderIO if needed, then build a LiveKit SessionReport.

    LiveKit's ``make_session_report`` raises if RecorderIO is still recording.
    Shutdown can reach persistence before the recorder has been marked closed;
    close it first so a completed call's artifacts are not dropped entirely.
    """
    recorder_io = getattr(session, "_recorder_io", None) if session is not None else None
    if recorder_io is not None and getattr(recorder_io, "recording", False):
        logger.info("RecorderIO still recording at persist time; closing before session report")
        await recorder_io.aclose()
    return ctx.make_session_report(session)


def render_transcript_md(chat_history: Any) -> str:
    """Render chronological PGAI/PATIENT transcript from a ChatContext-like object."""
    items = getattr(chat_history, "items", None)
    if items is None:
        items = getattr(chat_history, "messages", [])

    blocks: list[str] = []
    for item in items:
        role = getattr(item, "role", None)
        if role not in SPEAKER_LABELS:
            continue
        text = getattr(item, "text_content", None)
        if text is None:
            raw = getattr(item, "content", None)
            if isinstance(raw, list):
                text = "\n".join(part for part in raw if isinstance(part, str))
            elif isinstance(raw, str):
                text = raw
        text = (text or "").strip()
        if not text:
            continue
        blocks.append(f"{SPEAKER_LABELS[role]}:\n{text}")

    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n"


@dataclass
class CallMetadata:
    scenario_id: str | None
    room_name: str
    room_id: str
    job_id: str
    dispatch_id: str | None
    sip_call_id: str | None
    caller_number: str | None
    destination_number: str | None
    recording_filename: str | None
    recording_started_at: float | None
    session_started_at: float | None
    session_ended_at: float | None


def build_call_metadata(
    *,
    report: Any,
    scenario_id: str | None,
    dispatch_id: str | None = None,
    sip_call_id: str | None = None,
    caller_number: str | None = None,
    destination_number: str | None = None,
    recording_filename: str | None = None,
) -> CallMetadata:
    return CallMetadata(
        scenario_id=scenario_id,
        room_name=str(getattr(report, "room", "") or ""),
        room_id=str(getattr(report, "room_id", "") or ""),
        job_id=str(getattr(report, "job_id", "") or ""),
        dispatch_id=dispatch_id,
        sip_call_id=sip_call_id,
        caller_number=caller_number,
        destination_number=destination_number,
        recording_filename=recording_filename,
        recording_started_at=getattr(report, "audio_recording_started_at", None),
        session_started_at=getattr(report, "started_at", None),
        session_ended_at=getattr(report, "timestamp", None),
    )


def persist_call_artifacts(
    *,
    report: Any,
    scenario_id: str | None,
    calls_root: Path | None = None,
    dispatch_id: str | None = None,
    sip_call_id: str | None = None,
    caller_number: str | None = None,
    destination_number: str | None = None,
) -> Path:
    """Write audio/transcript/metadata under ``calls/<room_name>/``.

    Missing audio or other optional artifacts produce warnings, not hard failures.
    """
    root = calls_root or calls_dir()
    call_id = str(getattr(report, "room", "") or "").strip() or str(
        getattr(report, "job_id", "") or "unknown-call"
    )
    out_dir = root / call_id
    out_dir.mkdir(parents=True, exist_ok=True)

    recording_filename: str | None = None
    audio_src = getattr(report, "audio_recording_path", None)
    if audio_src is not None:
        src_path = Path(audio_src)
        if src_path.is_file():
            dest = out_dir / "audio.ogg"
            try:
                shutil.copy2(src_path, dest)
                recording_filename = "audio.ogg"
                logger.info("Saved call audio to %s", dest)
            except OSError:
                logger.exception("Failed to copy call audio from %s", src_path)
        else:
            logger.warning("Session report audio path missing or not a file: %s", src_path)
    else:
        logger.warning("No audio_recording_path on session report; skipping audio.ogg")

    try:
        transcript = render_transcript_md(getattr(report, "chat_history", None))
        (out_dir / "transcript.md").write_text(transcript, encoding="utf-8")
        logger.info("Saved transcript to %s", out_dir / "transcript.md")
    except Exception:
        logger.exception("Failed to write transcript.md")

    try:
        metadata = build_call_metadata(
            report=report,
            scenario_id=scenario_id,
            dispatch_id=dispatch_id,
            sip_call_id=sip_call_id,
            caller_number=caller_number,
            destination_number=destination_number,
            recording_filename=recording_filename,
        )
        (out_dir / "metadata.json").write_text(
            json.dumps(asdict(metadata), indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        logger.info("Saved metadata to %s", out_dir / "metadata.json")
    except Exception:
        logger.exception("Failed to write metadata.json")

    return out_dir
