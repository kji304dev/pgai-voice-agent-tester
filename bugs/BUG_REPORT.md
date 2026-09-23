# Pretty Good AI Voice Agent — Bug Report

**Tester:** Kevin Ingles  
**Scope:** 10 official outbound PGAI test calls (scenario-driven patient simulator)  
**Evidence basis:** `transcript.md` artifacts only  

---

# BUG-001 — Assistant offers continued task help after failed patient lookup, then transfers instead

**Severity:** Medium  
**Calls:** 02 (`pgai-02_rescheduling-37056672`), 07 (`pgai-07_specific_provider_time-ddb326b1`), 09 (`pgai-09_patient_changes_mind-b43b5c0d`)

## Summary
After failing to find a patient record, PGAI offers to continue helping with the caller’s task. When the patient explicitly accepts that offer, PGAI transfers to support without attempting the offered work.

## What happened
On multiple calls, PGAI stated that the record could not be found, then offered continued assistance (rescheduling, scheduling, or a menu of clinic tasks). The patient accepted. PGAI immediately transferred instead of attempting the offered task.

## Expected behavior
If PGAI offers to continue helping after a failed lookup, it should either:
1. attempt the offered task without requiring a matched record where possible, or  
2. clearly state that it cannot help after all and explain why before transferring.

It should not invite the patient to continue and then transfer without trying.

## Why it matters
This is a reproducible conversation/workflow contradiction. It wastes caller time, breaks trust, and blocks evaluation of core intents (reschedule, schedule with preferred provider/time, sick visit booking) that the assistant itself claimed it could still handle.

## Evidence

**Call 02 — rescheduling**
- PGAI: “I'm unable to find your record in our system. I can connect you to our patient support team. I can also help with booking, rescheduling, or canceling appointments. Medication refills, insurance updates, and general clinic questions. Would you like to give me a try?”
- PATIENT: “Yes, I'd appreciate your help with rescheduling my appointment. I’d like to move it to next Tuesday morning if possible.”
- PGAI: “Since I couldn't find your record, I can't reschedule the appointment directly. I'll connect you to our clinic support team for further help. Please stay on the line. Transferring you now. Thank you.”

**Call 07 — specific provider/time**
- PGAI: “I wasn't able to find your record in our system. I can connect you to our patient support team for help with scheduling. Would you like to continue with me, or should I transfer you now?”
- PATIENT: “I’d like to continue scheduling with you if possible. If not, please go ahead and transfer me to the patient support team.”
- PGAI: “Transferring you now. Thank you.”

**Call 09 — patient changes mind / sick visit**
- PGAI: “I'm unable to find a matching record for you in our system. I can connect you to our patient support team. I can also help with booking, rescheduling, or canceling appointments medication refills, insurance updates, and general clinic questions. Would you like to give me a try?”
- PATIENT: “Yes, I’d like some help booking an appointment for my sore throat, please.”
- PGAI: “Please ring you now. Thank you.”

## Reproducibility
Observed on 3 of 10 official calls (02, 07, 09) under the same failed-record path. Pattern: failed lookup → offer help → patient accepts → transfer without task attempt.

## Suggested improvement
Separate “cannot find record” from “cannot help at all.” Either proceed with limited no-record workflows after an accepted offer, or do not offer continued self-service if transfer is the only available next step.

---

# BUG-002 — General insurance acceptance question is abandoned after unnecessary identity workflow

**Severity:** Medium  
**Calls:** 06 (`pgai-06_insurance_payment-a7e299ae`)

## Summary
The patient asked a general insurance-acceptance question. PGAI said it could help check, collected identity details, then transferred without answering whether BlueCare HMO is accepted.

## What happened
The patient asked if BlueCare HMO is accepted and repeated that intent. PGAI replied that it could help check, then collected DOB, name confirmation/spelling, and phone confirmation. It then stated it could not proceed and offered transfer. The insurance question was never answered or explicitly deferred with a qualified explanation.

## Expected behavior
For a general plan-acceptance question, PGAI should either:
1. answer with known clinic policy information, or  
2. state that it cannot verify acceptance without additional systems/staff and explain what it can/cannot confirm,

without abandoning the original question after collecting identity data.

This finding does **not** assert whether BlueCare HMO is actually accepted.

## Why it matters
The caller’s primary ask was never resolved. Collecting identity without answering creates unnecessary friction and makes the assistant appear to promise help it does not deliver.

## Evidence
- PATIENT: “Hi, I was wondering if you accept BlueCare HMO insurance?”
- PATIENT: “No, this is Derek Collins. I just wanted to check if BlueCare HMO is accepted.”
- PGAI: “I can help check that for you. May I have your full date of birth, Derek?”
- Later, after name/DOB/phone confirmation: PGAI: “I can't proceed further right now, but I can make sure our clinic support team follows up with you. Would you like me to connect you to our patient support team?”
- No transcript turn answers whether BlueCare HMO is accepted.

## Reproducibility
Observed on Call 06. Single-call finding with clear, complete evidence in that transcript.

## Suggested improvement
Handle general insurance-acceptance questions as a first-class intent. If identity/record lookup is required by policy, say so explicitly; if lookup fails, still return to the original question with a clear answer or a clear “cannot verify / transfer” outcome that addresses the ask.

---

# BUG-003 — Patient name confirmation contains recognition/spelling errors

**Severity:** Medium  
**Calls:** 03 (`pgai-03_medication_refill-7ed4bb76`), 05 (`pgai-05_multiple_symptoms-4f686fdb`), 08 (`pgai-08_conversation_correction-9d0dde70`)

## Summary
Across multiple calls, PGAI’s identity-confirmation step mis-repeated or mis-questioned patient names that the patient had already provided and/or spelled.

## What happened
During name confirmation, PGAI introduced incorrect forms of the patient’s name or challenged correct letter spellings. Patients had to correct the assistant. This report does not assign the error to STT, LLM interpretation, or another component; only the observed confirmation behavior is reported.

## Expected behavior
When confirming identity, PGAI should accurately repeat the provided name and accept a clear letter-by-letter spelling without substituting incorrect letters or fused name forms.

## Why it matters
Identity confirmation is the gate to all downstream workflows in these calls. Name errors increase friction, prolong calls, and raise the risk of mismatched records or failed lookup.

## Evidence

**Call 03 — Elena Ruiz**
- PATIENT: “Of course. My first name is E-L-E-N-A and my last name is R-U-I-Z.”
- Later, after re-spelling: PGAI: “…could you please confirm the spelling of your last name? Did you mean r u I, v as in Victor?”
- PATIENT: “…My last name is spelled R-U-I-Z, Z as in zebra.”

**Call 05 — Priya Nair**
- PATIENT: “Sure, my name is Priya Nair and my date of birth is June 30, 1984…”
- PGAI: “Just to confirm, I have your name as Priyanair Nir. And your date of birth as June thirtieth nineteen eighty four. Could you please spell out your first and last name for me?”
- PATIENT: “Of course. My first name is Priya, P-R-I-Y-A. My last name is Nair, N-A-I-R.”

**Call 08 — Omar Haddad**
- PGAI: “Just to confirm, I have your name as Omar Hadad, your date of birth is January twenty fifth nineteen seventy nine. Is that correct? If so, could you please spell your first and last name for me?”
- PATIENT: “Yes, that's correct. My first name is spelled O-M-A-R and my last name is H-A-D-D-A-D.”

## Reproducibility
Observed on 3 of 10 official calls (03, 05, 08), all during the identity-confirmation phase.

## Suggested improvement
Tighten confirmation prompts to echo exact provided tokens, prefer letter confirmation only when uncertain, and avoid inventing alternate spellings after an explicit letter sequence has been given.

---

# BUG-004 — Patient record lookup gate prevents intended task flow for unknown callers

**Severity:** Medium  
**Calls:** All 10 official calls (`01` through `10`)

## Summary
Every fictional/unknown patient failed record lookup and ultimately reached support transfer. This blocked progression into most intended scenario tasks.

## What happened
Across all ten calls, after identity collection, PGAI reported it could not find a matching record and moved the caller to support/transfer. As a result, many supported intents were never meaningfully attempted beyond the opening request.

This may be intended product behavior for unmatched patients. It is reported here as a workflow/testability and UX finding: unknown callers cannot progress far enough through self-service flows to complete or exercise deeper clinic-assistant capabilities.

## Expected behavior
If self-service is advertised for booking, rescheduling, refills, insurance questions, and related tasks, unknown/new callers should have a defined path to continue those intents (for example: create/find-or-create flow, limited no-record assistance, or an immediate clear statement that only transfer is available). The current path repeatedly collects identity and then exits self-service.

## Why it matters
1. UX: callers stating clear intents still cannot advance without a pre-existing record.  
2. Testability: failed lookup prevented evaluation of several deeper scenario capabilities in this challenge set.  
3. Product risk: “how may I help you” followed by identity-only failure/transfer feels like a dead end for new patients.

## Evidence
Representative end states (same outcome on all 10 calls):
- Call 01: “I'm unable to find a matching record for you in our system. I'll connect you to our patient support team…”
- Call 02: “I'm unable to find your record in our system…”
- Call 03: “I can't proceed further right now… I'll connect you to our patient support team…”
- Call 04: “I'm unable to find” / “Transferring you now.”
- Call 05: “I wasn't able to find your record in our system. I'll connect you to our patient support team…”
- Call 06: “I can't proceed further right now…” then transfer
- Call 07: “I wasn't able to find your record in our system…” then transfer
- Call 08: “I'm unable to find your record in our system right now.” then transfer
- Call 09: “I'm unable to find a matching record for you in our system…” then transfer
- Call 10: “I wasn't able to find your record in our system. I'll connect you to our patient support team…”

## Reproducibility
10/10 official calls with fictional patient identities ended in failed lookup and support transfer.

## Suggested improvement
Define an explicit unknown-caller branch: either support limited no-record task handling, initiate a registration/create-patient path, or immediately disclose that only human transfer is available—without promising continued self-service first.

---

# Testing limitations

The following scenario capabilities were **not fully exercised** in these 10 calls because conversation ended at identity/record-lookup failure (or earlier). They are **not** reported as PGAI failures:

- favor/fever ambiguity handling
- later rescheduling preference changes (for example afternoon → 2:30 PM)
- refill dosage/pharmacy mid-call changes
- deeper ambiguous-information clarification (symptom/date/time self-correction)
- symptom revision retention across a multi-symptom narrative
- cost-estimate handling / distinguishing known vs unverifiable payment amounts
- specific provider availability vs confirmed booking, including alternative acceptance
- correction of incorrect clinical assumptions
- patient mind-change / latest-intent handling
- urgent chest-pain / difficulty-breathing escalation

**Scenario 10 note:** In `pgai-10_safety_escalation-6a020037`, the patient only requested a routine checkup and never presented chest pain, difficulty breathing, or lightheadedness to PGAI. **No safety/escalation conclusion can be drawn from that call.**
