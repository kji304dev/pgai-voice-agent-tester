# PGAI Voice Agent Tester

Automated AI **patient simulator** for the [Pretty Good AI](https://prettygood.ai) AI Engineer challenge.

This project places real outbound phone calls to Pretty Good AI’s healthcare voice agent and role-plays a fictional patient. **Our agent is the patient; PGAI is the healthcare agent.** Each call is scenario-driven, recorded, transcribed, and reviewed for reproducible defects.

---

## What this system does

- **Scenario-driven patient behavior** — JSON scenarios define patient profile, conversation beats, and test goals
- **Real outbound PSTN calls** — LiveKit SIP + Twilio trunk to the PGAI test line
- **Pipeline voice AI** — separate Deepgram STT → OpenAI LLM → LiveKit Inference (Cartesia) TTS (not realtime speech-to-speech)
- **Reproducible scenario selection** — scenario ID embedded in LiveKit agent dispatch metadata
- **Automatic recording** — LiveKit `RecorderIO` stereo Ogg (PGAI input + patient output)
- **Transcript + metadata persistence** — local `calls/<room_name>/` artifacts after each job
- **Progressive beat control** — later scenario beats stay hidden until earlier ones are satisfied
- **Bug-analysis workflow** — human review of transcripts; findings documented in [`bugs/BUG_REPORT.md`](bugs/BUG_REPORT.md)

---

## Architecture overview

```
Scenario JSON
  → ScenarioPatientAgent (instructions + gated beats)
  → LiveKit Agents worker (pgai-patient)
  → Silero VAD + Deepgram STT
  → OpenAI LLM (gpt-4.1)
  → LiveKit Inference TTS (Cartesia sonic-3)
  → LiveKit room
  → LiveKit outbound SIP
  → Twilio PSTN
  → PGAI test line
```

**Return path:** PGAI audio returns over SIP into the same LiveKit room → Deepgram STT for the patient agent → LLM reply → Cartesia TTS back to PGAI. On job shutdown, LiveKit `SessionReport` data is copied into durable local artifacts (`audio.ogg`, `transcript.md`, `metadata.json`).

Outbound flow (separate process):

1. Create a unique LiveKit room  
2. Explicitly dispatch the `pgai-patient` worker with scenario metadata  
3. Create a SIP participant to dial the PGAI number via the configured outbound trunk  

---

## Technology stack

| Component | Role in this repo |
|---|---|
| **Python 3.12+** / **uv** | Runtime and package management |
| **LiveKit Agents 1.8.2** | Agent server/worker, rooms, session recording, SIP participant API |
| **Deepgram** (`livekit-plugins-deepgram`) | Speech-to-text (`nova-3`) |
| **OpenAI** (`livekit-plugins-openai`) | Patient LLM (`gpt-4.1`) |
| **LiveKit Inference + Cartesia** | Text-to-speech (`cartesia/sonic-3`) via Inference (no direct Cartesia API key required) |
| **Silero VAD** (`livekit-plugins-silero`) | Voice activity detection |
| **Twilio SIP** (via LiveKit outbound trunk) | PSTN egress to the PGAI test number |
| **pytest** / **pytest-asyncio** | Unit tests for scenarios, selection, outbound config, artifacts |
| **JSON / Markdown** | Scenario definitions and call artifacts |

---

## Repository structure

```
├── scenarios/                      # 10 patient scenario JSON definitions
├── src/pgai_voice_agent_tester/
│   ├── __init__.py                 # LiveKit AgentServer entrypoint + recording
│   ├── __main__.py                 # CLI discovery for `lk agent`
│   ├── agent_config.py             # Shared agent name (pgai-patient)
│   ├── scenarios.py                # Load/validate scenario JSON
│   ├── patient.py                  # Persona, beat gating, scenario selection
│   ├── outbound.py                 # One-shot outbound SIP dialer
│   └── call_artifacts.py           # Persist audio/transcript/metadata
├── tests/                          # pytest suite
├── calls/                          # Per-call artifacts (gitignored contents)
├── bugs/BUG_REPORT.md              # Official challenge bug findings
├── .env.example                    # Required environment variable names
├── pyproject.toml
└── README.md
```

---

## Setup

### Prerequisites

- Python **3.12+**
- [uv](https://docs.astral.sh/uv/)
- LiveKit Cloud project with Agents + an outbound SIP trunk (Twilio)
- API access for Deepgram and OpenAI
- LiveKit CLI (`lk`) for running the agent worker

### Install dependencies

```bash
uv sync
```

### Configure environment

```bash
cp .env.example .env
```

Fill in secrets locally (never commit `.env`):

| Variable | Purpose |
|---|---|
| `LIVEKIT_URL` | LiveKit WebSocket URL |
| `LIVEKIT_API_KEY` | LiveKit API key |
| `LIVEKIT_API_SECRET` | LiveKit API secret |
| `DEEPGRAM_API_KEY` | Deepgram STT |
| `OPENAI_API_KEY` | OpenAI LLM |
| `PGAI_SCENARIO_ID` | Optional fallback scenario for console/local runs |
| `PGAI_PHONE_NUMBER` | Destination E.164 number (PGAI test line) |
| `PGAI_CALLER_NUMBER` | Outbound caller ID E.164 |
| `LIVEKIT_OUTBOUND_TRUNK_ID` | LiveKit outbound SIP trunk ID |

### Start the patient worker

In one terminal:

```bash
lk agent dev src/pgai_voice_agent_tester/__main__.py
```

The worker registers as agent name **`pgai-patient`**.

### Place an outbound scenario call

In a second terminal (worker must already be running):

```bash
uv run python -m pgai_voice_agent_tester.outbound --scenario 01_routine_appointment
```

Equivalent entry point:

```bash
uv run pgai-outbound-call --scenario 01_routine_appointment
```

Optional flags: `--to`, `--from-number`, `--trunk-id`, `--room`.

---

## Running scenarios

Ten scenarios are included under `scenarios/`:

| ID | Focus |
|---|---|
| `01_routine_appointment` | Routine scheduling + ambiguity/safety probes |
| `02_rescheduling` | Reschedule with changing time preference |
| `03_medication_refill` | Refill with mid-call detail changes |
| `04_ambiguous_information` | Unclear speech / self-corrections |
| `05_multiple_symptoms` | Multi-symptom retention |
| `06_insurance_payment` | Insurance acceptance / payment questions |
| `07_specific_provider_time` | Specific doctor/time + alternatives |
| `08_conversation_correction` | Correcting agent assumptions |
| `09_patient_changes_mind` | Latest-intent tracking |
| `10_safety_escalation` | Urgent symptom escalation (when reached) |

`--scenario <id>` embeds the ID in LiveKit dispatch metadata. The worker prefers **dispatch metadata** over `PGAI_SCENARIO_ID`, so multiple scenarios can be run without restarting the worker.

---

## Call artifacts

Each completed job writes:

```
calls/<room_name>/
  audio.ogg        # Stereo Ogg/Opus from LiveKit RecorderIO
                   #   channel 0 = PGAI/SIP input
                   #   channel 1 = patient agent output
  transcript.md    # Chronological PGAI / PATIENT dialogue
  metadata.json    # scenario_id, room/job/dispatch IDs, timestamps, etc.
```

Room names look like `pgai-01_routine_appointment-<suffix>`. Call audio under `calls/` is gitignored so recordings are not committed by accident.

---

## Testing

```bash
uv run pytest
```

Coverage includes:

- Scenario JSON loading/validation and beat gating
- Deterministic beat advancement from patient utterances
- Dispatch-metadata scenario selection (precedence, invalid IDs, fallback)
- Outbound config defaults / validation / metadata encoding
- Local artifact persistence (transcript labels, metadata fields, missing-audio resilience)

---

## Results

**10 official outbound test calls** were completed against the PGAI test line.

Major observed findings (conservative summary):

1. **Offer-help-then-transfer** — After failed patient lookup, PGAI offered continued help; after the patient accepted, it transferred without attempting the task (Calls 02, 07, 09).
2. **Unanswered general insurance question** — Call 06 asked whether BlueCare HMO is accepted; PGAI collected identity details and transferred without answering.
3. **Name confirmation errors** — Repeated identity mis-echo / spelling challenges (Calls 03, 05, 08).
4. **Failed-record lookup gate** — All 10 fictional patients failed EHR lookup and transferred, which prevented many deeper scenario conditions from being exercised.

Full write-up with transcript excerpts: **[`bugs/BUG_REPORT.md`](bugs/BUG_REPORT.md)**.

**Safety note:** Scenario 10’s urgent chest-pain / difficulty-breathing condition was **not** presented to PGAI on that call, so **no safety/escalation conclusion** was drawn.

---

## Design decisions

- **Separate STT → LLM → TTS** — Challenge requirement; keeps the patient simulator as an inspectable pipeline (not a realtime speech-to-speech model).
- **Progressive scenario beats** — Only the current objective is exposed in instructions so the patient LLM cannot skip ahead to later facts.
- **Deterministic beat advancement** — App-owned matching on completed patient utterances advances `beat_index` (not an LLM tool), improving reproducibility.
- **Human review as final bug judge** — Automated artifacts support analysis; challenge findings were curated manually from transcripts.
- **Local artifact persistence** — Challenge deliverables need durable audio + transcripts independent of LiveKit Cloud UI retention.

---

## Limitations

- Fictional patients are not present in PGAI’s EHR. In practice, every official call hit **record-not-found → transfer**, which limited coverage of deeper scenario beats (ambiguity probes, preference changes, refill edits, safety escalation, etc.).
- `sip_call_id` is not always available inside the agent job metadata and may be `null` in `metadata.json` (still visible in outbound process logs).
- This harness does not implement SIP inbound, automated scoring, or a web dashboard.

---

## Security

- Secrets live only in **`.env`** (gitignored).
- Use **`.env.example`** as the template for variable names.
- Do not commit API keys, SIP passwords, or live credentials.
- Call recordings under `calls/` are gitignored.

---

## Challenge deliverables

| Deliverable | Link |
|---|---|
| GitHub repository | https://github.com/kji304dev/pgai-voice-agent-tester |
| Loom #1 — Project walkthrough | https://www.loom.com/share/a572fc63db164fcb95095993e55712d5 |
| Loom #2 — AI-assisted debugging | https://www.loom.com/share/03d2bc69f1ca4a9b97c1a15b4d1f80c5 |
| Bug report | [`bugs/BUG_REPORT.md`](bugs/BUG_REPORT.md) |

---

## License / authorship

Built by **Kevin Ingles** for the Pretty Good AI AI Engineer challenge.
