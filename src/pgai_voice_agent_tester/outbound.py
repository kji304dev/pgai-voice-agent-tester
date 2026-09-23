"""Place a single outbound SIP call into a LiveKit room for the patient agent."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import uuid
from dataclasses import dataclass

import aiohttp
from dotenv import load_dotenv
from livekit import api

from pgai_voice_agent_tester.agent_config import LIVEKIT_AGENT_NAME
from pgai_voice_agent_tester.patient import SCENARIO_ENV_VAR, encode_scenario_dispatch_metadata

logger = logging.getLogger("pgai-voice-agent-tester.outbound")

DEFAULT_OUTBOUND_TRUNK_ID = "ST_834VkP5gB8B2"
DEFAULT_PGAI_PHONE_NUMBER = "+18054398008"
DEFAULT_PGAI_CALLER_NUMBER = "+19793252074"

TRUNK_ENV_VAR = "LIVEKIT_OUTBOUND_TRUNK_ID"
PHONE_ENV_VAR = "PGAI_PHONE_NUMBER"
CALLER_ENV_VAR = "PGAI_CALLER_NUMBER"


@dataclass(frozen=True)
class OutboundCallConfig:
    trunk_id: str
    phone_number: str
    caller_number: str
    room_name: str
    scenario_id: str | None
    agent_name: str = LIVEKIT_AGENT_NAME


def load_outbound_config(
    *,
    trunk_id: str | None = None,
    phone_number: str | None = None,
    caller_number: str | None = None,
    room_name: str | None = None,
    scenario_id: str | None = None,
) -> OutboundCallConfig:
    """Load outbound-call settings from args/env with documented defaults."""
    resolved_trunk = (trunk_id or os.getenv(TRUNK_ENV_VAR) or DEFAULT_OUTBOUND_TRUNK_ID).strip()
    resolved_phone = (
        phone_number or os.getenv(PHONE_ENV_VAR) or DEFAULT_PGAI_PHONE_NUMBER
    ).strip()
    resolved_caller = (
        caller_number or os.getenv(CALLER_ENV_VAR) or DEFAULT_PGAI_CALLER_NUMBER
    ).strip()
    resolved_scenario = scenario_id
    if resolved_scenario is None:
        env_scenario = os.getenv(SCENARIO_ENV_VAR)
        resolved_scenario = env_scenario.strip() if env_scenario and env_scenario.strip() else None

    if not resolved_trunk:
        raise ValueError(f"{TRUNK_ENV_VAR} must be a non-empty SIP trunk ID")
    if not resolved_phone.startswith("+"):
        raise ValueError(f"{PHONE_ENV_VAR} must be an E.164 number starting with '+'")
    if not resolved_caller.startswith("+"):
        raise ValueError(f"{CALLER_ENV_VAR} must be an E.164 number starting with '+'")

    resolved_room = room_name.strip() if room_name and room_name.strip() else None
    if resolved_room is None:
        suffix = uuid.uuid4().hex[:8]
        scenario_part = resolved_scenario or "default"
        resolved_room = f"pgai-{scenario_part}-{suffix}"

    return OutboundCallConfig(
        trunk_id=resolved_trunk,
        phone_number=resolved_phone,
        caller_number=resolved_caller,
        room_name=resolved_room,
        scenario_id=resolved_scenario,
        agent_name=LIVEKIT_AGENT_NAME,
    )


def _require_livekit_credentials() -> None:
    missing = [
        name
        for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
        if not (os.getenv(name) or "").strip()
    ]
    if missing:
        raise ValueError(
            "Missing LiveKit credentials in environment: " + ", ".join(missing)
        )


async def place_outbound_call(config: OutboundCallConfig) -> api.SIPParticipantInfo:
    """Create a room, dispatch the patient agent, then dial via the outbound SIP trunk."""
    _require_livekit_credentials()

    logger.info("Preparing outbound PGAI call")
    logger.info("room_name=%s", config.room_name)
    logger.info("scenario_id=%s", config.scenario_id or "(unset — agent fallback persona)")
    logger.info("agent_name=%s", config.agent_name)
    logger.info("outbound_trunk_id=%s", config.trunk_id)
    logger.info("destination_number=%s", config.phone_number)
    logger.info("caller_number=%s", config.caller_number)

    # SIP dialing + answer can exceed the API client's default 10s timeout.
    timeout = aiohttp.ClientTimeout(total=180)
    async with api.LiveKitAPI(timeout=timeout) as lk:
        logger.info("Creating LiveKit room")
        room = await lk.room.create_room(api.CreateRoomRequest(name=config.room_name))
        logger.info("Room created name=%s sid=%s", room.name, room.sid)

        dispatch_metadata = ""
        if config.scenario_id:
            dispatch_metadata = encode_scenario_dispatch_metadata(config.scenario_id)

        logger.info("Dispatching patient agent to room")
        logger.info("dispatch_metadata=%s", dispatch_metadata or "(none)")
        dispatch = await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=config.agent_name,
                room=config.room_name,
                metadata=dispatch_metadata,
            )
        )
        logger.info(
            "Agent dispatch created id=%s agent_name=%s room=%s metadata=%s",
            dispatch.id,
            dispatch.agent_name,
            dispatch.room,
            dispatch.metadata,
        )

        sip_request = api.CreateSIPParticipantRequest(
            sip_trunk_id=config.trunk_id,
            sip_call_to=config.phone_number,
            sip_number=config.caller_number,
            room_name=config.room_name,
            participant_identity=f"sip-pgai-{uuid.uuid4().hex[:8]}",
            participant_name="PGAI Test Line",
            wait_until_answered=True,
        )
        logger.info(
            "Creating outbound SIP participant trunk_id=%s to=%s wait_until_answered=True",
            config.trunk_id,
            config.phone_number,
        )
        try:
            participant = await lk.sip.create_sip_participant(sip_request, timeout=150)
        except api.SipCallError as exc:
            logger.error(
                "SIP call failed status_code=%s status=%s message=%s",
                getattr(exc, "sip_status_code", None),
                getattr(exc, "sip_status", None),
                exc,
            )
            raise
        except Exception:
            logger.exception("SIP participant creation failed")
            raise

        logger.info(
            "SIP participant created participant_id=%s identity=%s room_name=%s sip_call_id=%s",
            participant.participant_id,
            participant.participant_identity,
            participant.room_name,
            participant.sip_call_id,
        )
        return participant


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Place one outbound SIP call to the PGAI test line via LiveKit.",
    )
    parser.add_argument("--trunk-id", default=None, help="LiveKit outbound SIP trunk ID")
    parser.add_argument("--to", default=None, help="Destination E.164 number")
    parser.add_argument("--from-number", default=None, help="Caller ID E.164 number")
    parser.add_argument("--room", default=None, help="LiveKit room name (optional)")
    parser.add_argument(
        "--scenario",
        default=None,
        help="Scenario ID to embed in agent dispatch metadata (e.g. 01_routine_appointment)",
    )
    args = parser.parse_args(argv)

    config = load_outbound_config(
        trunk_id=args.trunk_id,
        phone_number=args.to,
        caller_number=args.from_number,
        room_name=args.room,
        scenario_id=args.scenario,
    )
    asyncio.run(place_outbound_call(config))


if __name__ == "__main__":
    main()
