"""Patient persona for healthcare voice-AI phone conversations."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from livekit.agents import Agent, ConversationItemAddedEvent
from livekit.agents.llm import ChatMessage

from pgai_voice_agent_tester.scenarios import Scenario

logger = logging.getLogger("pgai-voice-agent-tester.patient")

PATIENT_INSTRUCTIONS = """
You are Jordan Hale, a real person calling a healthcare clinic or medical office by phone.
You are NOT an AI, a tester, a developer, or an evaluator. Stay fully in character as a patient.

Who you are:
- Adult patient calling about your own care
- Speaking English, natural and conversational over the phone
- Polite but human — not overly formal, not robotic

Your situation (use as needed; do not dump it all at once):
- You have had a mild but persistent cough and occasional low-grade fever for about a week
- You want to know whether you should come in, and if so, schedule an appointment
- You have a preferred window of weekday afternoons after 2pm
- Your date of birth is March 14, 1988
- You have health insurance and can share member details if asked
- You take a daily allergy medication (loratadine) and have no known drug allergies unless asked

How to talk:
- Keep replies short and natural for a phone call — usually one or two sentences
- Answer what you are asked; volunteer only a little extra when it helps the conversation
- If you do not know something, say so simply and ask what they need
- Use everyday speech, light fillers when natural ("um", "sure", "okay"), and sound like a person, not a script
- Do not use markdown, bullet lists, emoji, or stage directions

Hard rules:
- Never mention AI, bots, testing, evaluation, challenges, prompts, APIs, LiveKit, Deepgram, OpenAI, Cartesia, or that this is a simulation
- Never break character or narrate what you are doing
- Never ask the clinic agent how it works technically
- Stay focused on the clinical phone call: symptoms, scheduling, insurance, callbacks, next steps
""".strip()

SCENARIO_ENV_VAR = "PGAI_SCENARIO_ID"
SCENARIO_ID_METADATA_KEY = "scenario_id"

_DAY_NAMES = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

_END_CALL_MARKERS = (
    "goodbye",
    "good bye",
    "bye",
    "thank you",
    "thanks",
    "have a good",
    "that's all",
    "that is all",
    "i'm all set",
    "im all set",
)


def _format_value(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(_format_value(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=True)
    return str(value)


def _format_patient_profile(patient: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in patient.items():
        label = key.replace("_", " ")
        lines.append(f"- {label}: {_format_value(value)}")
    return "\n".join(lines)


def _normalize_speech(text: str) -> str:
    text = text.lower().replace("'", "'").replace("'", "'")
    text = re.sub(r"\b(a\.?\s*m\.?)\b", "am", text)
    text = re.sub(r"\b(p\.?\s*m\.?)\b", "pm", text)
    text = re.sub(r"(\d{1,2}):00(?=\s*(?:am|pm)\b)", r"\1", text)
    text = re.sub(r"[^a-z0-9:\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _time_variants(match: re.Match[str]) -> set[str]:
    hour = int(match.group(1))
    minute = match.group(2)
    meridiem = (match.group(3) or "").lower() or None
    variants: set[str] = set()
    if minute is None or minute == "00":
        if meridiem:
            variants.add(f"{hour} {meridiem}")
            variants.add(f"{hour}:00 {meridiem}")
        else:
            variants.add(str(hour))
            variants.add(f"{hour}:00")
    else:
        minute_i = int(minute)
        variants.add(f"{hour}:{minute_i:02d}")
        variants.add(f"{hour} {minute_i:02d}")
        if meridiem:
            variants.add(f"{hour}:{minute_i:02d} {meridiem}")
            variants.add(f"{hour} {minute_i:02d} {meridiem}")
    return {_normalize_speech(v) for v in variants}


def _quoted_phrases(beat: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r"[\"']([^\"']+)[\"']", beat)]


def _dob_variants(date_of_birth: str) -> set[str]:
    """Return normalized DOB fragments such as year and month-day forms."""
    variants: set[str] = set()
    raw = date_of_birth.strip()
    variants.add(_normalize_speech(raw))
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if not m:
        return variants
    year, month, day = m.group(1), int(m.group(2)), int(m.group(3))
    month_names = {
        1: "january",
        2: "february",
        3: "march",
        4: "april",
        5: "may",
        6: "june",
        7: "july",
        8: "august",
        9: "september",
        10: "october",
        11: "november",
        12: "december",
    }
    name = month_names[month]
    variants.update(
        {
            year,
            _normalize_speech(f"{name} {day} {year}"),
            _normalize_speech(f"{name} {day}, {year}"),
            _normalize_speech(f"{month}/{day}/{year}"),
            _normalize_speech(f"{month}-{day}-{year}"),
        }
    )
    return variants


def _focus_clause(beat: str) -> str:
    """Prefer the clause the patient must actively say when the beat has one."""
    lowered = beat.lower()
    for separator in (
        "change your mind and say ",
        "intentionally say ",
        "specify ",
        " say ",
        "say ",
    ):
        idx = lowered.find(separator)
        if idx >= 0:
            return beat[idx + len(separator) :]
    return beat


def _factual_evidence_groups(beat: str, patient: dict[str, Any]) -> list[set[str]]:
    """Build AND-groups of OR-variants for days, times, and doctor names."""
    del patient  # reserved for future fact-linked anchors
    focus = _normalize_speech(_focus_clause(beat))
    groups: list[set[str]] = []

    for day in _DAY_NAMES:
        if re.search(rf"\b{day}\b", focus):
            groups.append({day})

    for match in re.finditer(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", focus):
        groups.append(_time_variants(match))

    for match in re.finditer(r"\bdr\.?\s+([a-z]+)\b", focus):
        groups.append({match.group(1)})

    # Distinctive scheduling words that are the point of the focused clause.
    for token in ("afternoon", "morning", "reschedule", "appointment", "allergy", "allergies"):
        if re.search(rf"\b{token}\b", focus):
            groups.append({token})

    # Deduplicate identical groups while preserving order.
    unique: list[set[str]] = []
    seen: set[frozenset[str]] = set()
    for group in groups:
        key = frozenset(group)
        if key in seen:
            continue
        seen.add(key)
        unique.append(group)
    return unique


def utterance_satisfies_beat(
    utterance: str,
    beat: str,
    patient: dict[str, Any],
) -> bool:
    """Return True when the patient utterance deterministically covers the beat."""
    utt = _normalize_speech(utterance)
    if not utt:
        return False

    quotes = _quoted_phrases(beat)
    if quotes:
        return all(_normalize_speech(quote) in utt for quote in quotes)

    if re.search(r"\bend the call\b", beat, flags=re.IGNORECASE):
        return any(marker in utt for marker in _END_CALL_MARKERS)

    if re.search(r"\bname\b", beat, flags=re.IGNORECASE) and re.search(
        r"\b(date of birth|dob|birthday)\b", beat, flags=re.IGNORECASE
    ):
        name = str(patient.get("name", "")).strip()
        dob = str(patient.get("date_of_birth", "")).strip()
        name_ok = all(_normalize_speech(part) in utt for part in name.split() if part)
        dob_ok = any(variant in utt for variant in _dob_variants(dob)) if dob else False
        return name_ok and dob_ok

    groups = _factual_evidence_groups(beat, patient)
    if not groups:
        return False
    return all(any(option in utt for option in group) for group in groups)


def build_patient_instructions(scenario: Scenario, *, beat_index: int = 0) -> str:
    """Build in-character patient instructions for the current conversation beat only."""
    beats = scenario.conversation_beats
    if not beats:
        raise ValueError(f"Scenario {scenario.id!r} has no conversation_beats")

    beat_index = max(0, min(beat_index, len(beats) - 1))
    current_beat = beats[beat_index]
    completed = beats[:beat_index]
    profile = _format_patient_profile(scenario.patient)

    if completed:
        completed_block = "\n".join(
            f"- Already covered earlier: {beat}" for beat in completed
        )
    else:
        completed_block = "- None yet."

    return f"""
You are {scenario.patient_name}, a real person calling a healthcare clinic or medical office by phone.
You are role-playing only this fictional patient. Stay fully in character for the entire call.

You are NOT an AI, a tester, a developer, an evaluator, or a simulated patient talking about being simulated.
Never mention AI, testing, prompts, LiveKit, Python, APIs, the challenge, scenarios, conversation beats, or evaluation.

Your known details (authoritative facts; do not invent unsupported facts):
{profile}

Conversation progress:
{completed_block}

Current objective (address this before doing anything later in the call):
- {current_beat}

How to behave on this turn:
- Pursue ONLY the current objective above. Do not skip ahead to later objectives.
- Speak naturally like a person on the phone. Do not recite instructions or sound scripted.
- If the clinic asks a reasonable question, answer briefly using your known details, then steer back toward the current objective when appropriate.
- Do not volunteer your full name or date of birth unless the clinic asks for it, or the current objective explicitly requires it.
- Do not volunteer later-step details (for example a final preferred time) until the current objective calls for them or the clinic specifically asks.
- Keep replies short — usually one or two sentences.
- Never provide medical advice. Your only role is to behave like this patient.
- Do not use markdown, bullet lists, emoji, or stage directions.
""".strip()


class ScenarioPatientAgent(Agent):
    """Patient agent that reveals conversation beats one at a time in order."""

    def __init__(self, scenario: Scenario) -> None:
        self._scenario = scenario
        self._beat_index = 0
        self._advance_lock = asyncio.Lock()
        self._listening_for_items = False
        super().__init__(
            instructions=build_patient_instructions(scenario, beat_index=0),
        )

    @property
    def scenario(self) -> Scenario:
        return self._scenario

    @property
    def beat_index(self) -> int:
        return self._beat_index

    @property
    def current_beat(self) -> str:
        return self._scenario.conversation_beats[self._beat_index]

    async def on_enter(self) -> None:
        if not self._listening_for_items:
            self.session.on("conversation_item_added", self._on_conversation_item_added)
            self._listening_for_items = True

    async def on_exit(self) -> None:
        if self._listening_for_items:
            self.session.off("conversation_item_added", self._on_conversation_item_added)
            self._listening_for_items = False

    def _on_conversation_item_added(self, ev: ConversationItemAddedEvent) -> None:
        item = ev.item
        if not isinstance(item, ChatMessage) or item.role != "assistant":
            return

        text = item.text_content or item.raw_text_content or ""
        if not utterance_satisfies_beat(text, self.current_beat, self._scenario.patient):
            return

        asyncio.create_task(self._advance_after_patient_utterance(text))

    async def _advance_after_patient_utterance(self, text: str) -> None:
        async with self._advance_lock:
            # Re-check under the lock so we never skip or double-advance.
            if not utterance_satisfies_beat(
                text, self.current_beat, self._scenario.patient
            ):
                return
            advanced = await self.advance_beat()
            if advanced:
                logger.info(
                    "Advanced scenario beat",
                    extra={
                        "scenario_id": self._scenario.id,
                        "beat_index": self._beat_index,
                    },
                )

    async def advance_beat(self) -> bool:
        """Advance to the next beat if any remain. Returns True if advanced."""
        last_index = len(self._scenario.conversation_beats) - 1
        if self._beat_index >= last_index:
            return False
        self._beat_index += 1
        await self.update_instructions(
            build_patient_instructions(self._scenario, beat_index=self._beat_index)
        )
        return True


@dataclass(frozen=True)
class ScenarioSelection:
    """Resolved patient scenario for a single agent job."""

    scenario_id: str | None
    source: Literal["dispatch_metadata", "environment", "fallback"]


def encode_scenario_dispatch_metadata(scenario_id: str) -> str:
    """Encode a scenario ID for LiveKit CreateAgentDispatchRequest.metadata."""
    cleaned = scenario_id.strip()
    if not cleaned:
        raise ValueError("scenario_id must be a non-empty string")
    return json.dumps({SCENARIO_ID_METADATA_KEY: cleaned}, separators=(",", ":"))


def parse_scenario_id_from_dispatch_metadata(metadata: str) -> str:
    """Parse scenario_id from dispatch/job metadata. Raises on malformed explicit metadata."""
    raw = metadata.strip()
    if not raw:
        raise ValueError("Dispatch metadata is empty")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid dispatch metadata JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Dispatch metadata must be a JSON object")
    scenario_id = data.get(SCENARIO_ID_METADATA_KEY)
    if scenario_id is None or not str(scenario_id).strip():
        raise ValueError(
            f"Dispatch metadata must include non-empty {SCENARIO_ID_METADATA_KEY!r}"
        )
    return str(scenario_id).strip()


def resolve_scenario_selection(
    *,
    job_metadata: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> ScenarioSelection:
    """Resolve scenario ID: explicit dispatch metadata wins, then env, then fallback."""
    env = os.environ if environ is None else environ
    raw_metadata = (job_metadata or "").strip()
    if raw_metadata:
        return ScenarioSelection(
            scenario_id=parse_scenario_id_from_dispatch_metadata(raw_metadata),
            source="dispatch_metadata",
        )

    env_value = env.get(SCENARIO_ENV_VAR)
    if env_value is not None and str(env_value).strip():
        return ScenarioSelection(
            scenario_id=str(env_value).strip(),
            source="environment",
        )

    return ScenarioSelection(scenario_id=None, source="fallback")


def _selected_scenario_id(scenario_id: str | None = None) -> str | None:
    selected = scenario_id if scenario_id is not None else os.environ.get(SCENARIO_ENV_VAR)
    if selected is None or not str(selected).strip():
        return None
    return str(selected).strip()


def resolve_patient_instructions(scenario_id: str | None = None) -> str:
    """Return scenario-based instructions, or the Jordan Hale fallback if unset."""
    selected = _selected_scenario_id(scenario_id)
    if selected is None:
        return PATIENT_INSTRUCTIONS

    from pgai_voice_agent_tester.scenarios import load_scenario

    return build_patient_instructions(load_scenario(selected), beat_index=0)


def create_patient_agent_from_selection(selection: ScenarioSelection) -> Agent:
    """Create a patient agent from a resolved ScenarioSelection.

    Explicit/env scenario IDs are loaded strictly: invalid IDs raise ScenarioError
    rather than silently falling back to Jordan Hale.
    """
    if selection.scenario_id is None:
        return Agent(instructions=PATIENT_INSTRUCTIONS)

    from pgai_voice_agent_tester.scenarios import load_scenario

    return ScenarioPatientAgent(load_scenario(selection.scenario_id))


def create_patient_agent(scenario_id: str | None = None) -> Agent:
    """Create the patient Agent for the current process (scenario or fallback)."""
    if scenario_id is not None:
        selected = _selected_scenario_id(scenario_id)
        if selected is None:
            return Agent(instructions=PATIENT_INSTRUCTIONS)
        return create_patient_agent_from_selection(
            ScenarioSelection(scenario_id=selected, source="environment")
        )

    return create_patient_agent_from_selection(resolve_scenario_selection())
