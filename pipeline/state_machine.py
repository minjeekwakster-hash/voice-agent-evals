"""
Agent Draft State Machine
--------------------------
Tracks an agent version through its deployment lifecycle.
draft_id is the cross-system join key: links your voice platform, eval tool, and observability tool.

States:
    EDITING -> DEPLOYED_TO_TEST -> EVALS_IN_PROGRESS -> EVALS_PASSED | EVALS_FAILED
    EVALS_PASSED -> PROMOTED_TO_STAGING -> PROMOTED_TO_PREPROD -> PROMOTED_TO_PROD
    EVALS_FAILED -> EDITING  (iterate on draft, version stays the same until re-deployed)

Usage:
    from pipeline.state_machine import AgentDraft
    draft = AgentDraft.create("support-agent", "1.0.0")
    draft.transition("DEPLOYED_TO_TEST")
    draft.save()
"""

import json
import os
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional


VALID_TRANSITIONS = {
    "EDITING":               ["DEPLOYED_TO_TEST"],
    "DEPLOYED_TO_TEST":      ["EVALS_IN_PROGRESS"],
    "EVALS_IN_PROGRESS":     ["EVALS_PASSED", "EVALS_FAILED"],
    "EVALS_FAILED":          ["EDITING"],
    "EVALS_PASSED":          ["PROMOTED_TO_STAGING"],
    "PROMOTED_TO_STAGING":   ["PROMOTED_TO_PREPROD"],
    "PROMOTED_TO_PREPROD":   ["PROMOTED_TO_PROD"],
    "PROMOTED_TO_PROD":      []          # terminal state
}

STATES = list(VALID_TRANSITIONS.keys())


@dataclass
class StateEvent:
    from_state: str
    to_state: str
    timestamp: str
    notes: Optional[str] = None


@dataclass
class AgentDraft:
    draft_id: str
    agent_name: str
    agent_version: str
    current_state: str
    created_at: str
    updated_at: str
    history: list[StateEvent] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @classmethod
    def create(cls, agent_name: str, agent_version: str, metadata: dict = None) -> "AgentDraft":
        """Create a new draft in EDITING state."""
        ts = _now()
        draft_id = f"{agent_name}-v{agent_version}-{ts[:10]}"
        return cls(
            draft_id=draft_id,
            agent_name=agent_name,
            agent_version=agent_version,
            current_state="EDITING",
            created_at=ts,
            updated_at=ts,
            metadata=metadata or {}
        )

    @classmethod
    def load(cls, path: str) -> "AgentDraft":
        """Load a draft from a JSON file."""
        with open(path) as f:
            data = json.load(f)
        history = [StateEvent(**e) for e in data.pop("history", [])]
        return cls(**data, history=history)

    def transition(self, new_state: str, notes: str = None) -> "AgentDraft":
        """
        Move to a new state. Raises ValueError if transition is not allowed.
        """
        allowed = VALID_TRANSITIONS.get(self.current_state, [])
        if new_state not in allowed:
            raise ValueError(
                f"Cannot transition from {self.current_state} to {new_state}. "
                f"Allowed: {allowed}"
            )

        event = StateEvent(
            from_state=self.current_state,
            to_state=new_state,
            timestamp=_now(),
            notes=notes
        )
        self.history.append(event)
        self.current_state = new_state
        self.updated_at = event.timestamp

        _print_transition(self.draft_id, event)
        return self

    def fail_evals(self, reason: str = None) -> "AgentDraft":
        """Shorthand: mark evals as failed and return to editing."""
        self.transition("EVALS_FAILED", notes=reason)
        self.transition("EDITING", notes="Returning to editing for iteration")
        return self

    def save(self, output_dir: str = "reports/") -> str:
        """Persist state to JSON. Returns the file path."""
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, f"{self.draft_id}.state.json")
        data = asdict(self)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return path

    def status(self) -> str:
        stage_num = STATES.index(self.current_state) + 1
        return (
            f"Draft: {self.draft_id}\n"
            f"State: {self.current_state} ({stage_num}/{len(STATES)})\n"
            f"Updated: {self.updated_at}"
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _print_transition(draft_id: str, event: StateEvent):
    print(f"[{draft_id}] {event.from_state} -> {event.to_state}"
          + (f" ({event.notes})" if event.notes else ""))
