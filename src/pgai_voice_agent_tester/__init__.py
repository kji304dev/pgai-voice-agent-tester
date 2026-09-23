"""Minimal LiveKit Agents pipeline: Silero VAD → Deepgram STT → OpenAI LLM → Cartesia TTS."""

import logging
import os

from dotenv import load_dotenv
from livekit.agents import AgentServer, AgentSession, JobContext, cli, inference
from livekit.plugins import deepgram, openai, silero

from pgai_voice_agent_tester.agent_config import LIVEKIT_AGENT_NAME
from pgai_voice_agent_tester.call_artifacts import (
    persist_call_artifacts,
    prepare_session_report,
)
from pgai_voice_agent_tester.patient import (
    create_patient_agent_from_selection,
    resolve_scenario_selection,
)

load_dotenv()

logger = logging.getLogger("pgai-voice-agent-tester")

server = AgentServer()


@server.rtc_session(agent_name=LIVEKIT_AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    selection = resolve_scenario_selection(job_metadata=ctx.job.metadata)
    logger.info(
        "Resolved patient scenario_id=%s source=%s job_id=%s room=%s",
        selection.scenario_id or "(Jordan Hale fallback)",
        selection.source,
        ctx.job.id,
        ctx.room.name,
    )
    agent = create_patient_agent_from_selection(selection)

    session = AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(model="nova-3", language="en-US"),
        llm=openai.LLM(model="gpt-4.1"),
        tts=inference.TTS(
            model="cartesia/sonic-3",
            voice="9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",
            language="en",
        ),
    )

    async def _persist_call_artifacts(_reason: str) -> None:
        try:
            report = await prepare_session_report(ctx, session)
        except Exception:
            logger.exception("Unable to build SessionReport for local call artifacts")
            return

        try:
            out_dir = persist_call_artifacts(
                report=report,
                scenario_id=selection.scenario_id,
                dispatch_id=getattr(ctx.job, "dispatch_id", None) or None,
                sip_call_id=None,
                caller_number=(os.getenv("PGAI_CALLER_NUMBER") or "").strip() or None,
                destination_number=(os.getenv("PGAI_PHONE_NUMBER") or "").strip() or None,
            )
            logger.info("Persisted local call artifacts under %s", out_dir)
        except Exception:
            logger.exception("Failed to persist local call artifacts")

    ctx.add_shutdown_callback(_persist_call_artifacts)

    await session.start(
        agent=agent,
        room=ctx.room,
        record=True,
    )


def main() -> None:
    cli.run_app(server)
