"""Load and select healthcare patient conversation scenarios."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = (
    "id",
    "name",
    "goal",
    "patient",
    "conversation_beats",
    "observations",
    "metadata",
)


class ScenarioError(Exception):
    """Raised when a scenario cannot be loaded or is invalid."""


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    goal: str
    patient: dict[str, Any]
    conversation_beats: list[str]
    observations: list[Any]
    metadata: dict[str, Any]

    @property
    def patient_name(self) -> str:
        name = self.patient.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ScenarioError(f"Scenario {self.id!r} is missing patient.name")
        return name.strip()


def scenarios_dir() -> Path:
    """Return the project-root ``scenarios/`` directory."""
    return Path(__file__).resolve().parents[2] / "scenarios"


def _validate_scenario_data(data: Any, *, source: str) -> Scenario:
    if not isinstance(data, dict):
        raise ScenarioError(f"Scenario JSON must be an object ({source})")

    missing = [field for field in REQUIRED_FIELDS if field not in data]
    if missing:
        raise ScenarioError(
            f"Scenario is missing required fields {missing} ({source})"
        )

    scenario_id = data["id"]
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise ScenarioError(f"Scenario id must be a non-empty string ({source})")

    if not isinstance(data["name"], str) or not data["name"].strip():
        raise ScenarioError(f"Scenario name must be a non-empty string ({source})")

    if not isinstance(data["goal"], str) or not data["goal"].strip():
        raise ScenarioError(f"Scenario goal must be a non-empty string ({source})")

    patient = data["patient"]
    if not isinstance(patient, dict) or not patient:
        raise ScenarioError(f"Scenario patient must be a non-empty object ({source})")

    beats = data["conversation_beats"]
    if not isinstance(beats, list) or not beats:
        raise ScenarioError(
            f"Scenario conversation_beats must be a non-empty list ({source})"
        )
    if not all(isinstance(beat, str) and beat.strip() for beat in beats):
        raise ScenarioError(
            f"Scenario conversation_beats must contain non-empty strings ({source})"
        )

    if not isinstance(data["observations"], list):
        raise ScenarioError(f"Scenario observations must be a list ({source})")

    if not isinstance(data["metadata"], dict):
        raise ScenarioError(f"Scenario metadata must be an object ({source})")

    return Scenario(
        id=scenario_id.strip(),
        name=data["name"].strip(),
        goal=data["goal"].strip(),
        patient=patient,
        conversation_beats=[beat.strip() for beat in beats],
        observations=data["observations"],
        metadata=data["metadata"],
    )


def load_scenario_file(path: Path) -> Scenario:
    """Load and validate a single scenario JSON file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ScenarioError(f"Could not read scenario file {path}: {exc}") from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ScenarioError(f"Invalid JSON in {path}: {exc}") from exc

    return _validate_scenario_data(data, source=str(path))


def list_scenarios(directory: Path | None = None) -> list[Scenario]:
    """Load all valid scenario JSON files from ``directory``."""
    root = directory or scenarios_dir()
    if not root.is_dir():
        raise ScenarioError(f"Scenarios directory not found: {root}")

    scenarios: list[Scenario] = []
    for path in sorted(root.glob("*.json")):
        scenarios.append(load_scenario_file(path))
    return scenarios


def load_scenario(scenario_id: str, directory: Path | None = None) -> Scenario:
    """Load a scenario by its ``id`` field (or matching filename stem)."""
    if not scenario_id or not scenario_id.strip():
        raise ScenarioError("Scenario ID must be a non-empty string")

    scenario_id = scenario_id.strip()
    root = directory or scenarios_dir()
    if not root.is_dir():
        raise ScenarioError(f"Scenarios directory not found: {root}")

    direct = root / f"{scenario_id}.json"
    if direct.is_file():
        scenario = load_scenario_file(direct)
        if scenario.id != scenario_id:
            raise ScenarioError(
                f"Scenario file {direct.name} has id {scenario.id!r}, "
                f"expected {scenario_id!r}"
            )
        return scenario

    matches = [s for s in list_scenarios(root) if s.id == scenario_id]
    if not matches:
        available = ", ".join(s.id for s in list_scenarios(root)) or "(none)"
        raise ScenarioError(
            f"Scenario ID {scenario_id!r} not found. Available: {available}"
        )
    if len(matches) > 1:
        raise ScenarioError(f"Multiple scenarios found with id {scenario_id!r}")
    return matches[0]
