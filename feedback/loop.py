"""
Post-Production Feedback Loop
------------------------------
Closes the loop from production back to the eval pipeline.
Run weekly: sample production calls, categorize failures, update golden set, re-run evals.

The four failure layers — route your fix to the right place:
    Layer A — Prompt:        Agent says wrong thing, doesn't follow instructions
    Layer B — Tool/RAG:      Agent calls wrong tool, retrieves wrong context
    Layer C — Routing:       Agent escalates wrong, doesn't route correctly
    Layer D — Voice config:  Latency, dead air, STT accuracy, interruption handling

Usage:
    from feedback.loop import categorize_failure, update_golden_set
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


FAILURE_LAYERS = {
    "A": {
        "name": "Prompt",
        "description": "Agent said wrong thing, hallucinated, didn't follow instructions, or was off-brand",
        "fix": "Edit system prompt — rewrite failing section, add constraints, or add examples",
        "evals_that_signal_this": ["prompt_conformance", "hallucination_detection", "context_adherence", "response_conciseness"]
    },
    "B": {
        "name": "Tool / RAG",
        "description": "Agent called wrong tool, retrieved wrong context, or knowledge base is stale",
        "fix": "Update knowledge base, fix tool definitions, or improve retrieval chunking",
        "evals_that_signal_this": ["query_handling", "context_retention", "task_completion"]
    },
    "C": {
        "name": "Routing",
        "description": "Agent escalated when it shouldn't have, didn't escalate when it should, or routed to wrong queue",
        "fix": "Update escalation conditions in prompt or routing config",
        "evals_that_signal_this": ["escalation_accuracy", "task_completion"]
    },
    "D": {
        "name": "Voice Config",
        "description": "Latency too high, dead air, STT misheard caller, interruptions handled wrong",
        "fix": "Adjust voice provider config: STT model, TTS speed, end-of-turn detection, token budget",
        "evals_that_signal_this": ["turn_taking_flow", "greeting_quality", "response_conciseness"]
    }
}

LLM_DIAGNOSIS_PROMPT = """You are a voice AI agent operations expert.
Diagnose failures in my voice agent and recommend specific fixes.

## Agent configuration
{agent_config}

## Eval results summary
{eval_summary}

## Failing call transcripts
{transcripts}

## What I need:

1. ROOT CAUSE ANALYSIS: For each failing eval, identify whether the root cause is:
   - Layer A (Prompt): agent says wrong thing, doesn't follow instructions
   - Layer B (Tool/RAG): wrong tool call, stale knowledge, bad retrieval
   - Layer C (Routing): wrong escalation decision
   - Layer D (Voice config): latency, STT, interruption, dead air

2. PRIORITY ORDER: Which failure to fix first (highest impact)

3. SPECIFIC FIX: Exact change to make for the top 2-3 failures

4. REGRESSION RISK: Which other evals might be affected by each fix

Return as structured JSON."""


@dataclass
class FailureCategorization:
    call_id: str
    transcript_snippet: str
    failing_evals: list[str]
    layer: str                    # A, B, C, or D
    layer_name: str
    proposed_fix: str
    reviewed_at: str


@dataclass
class FeedbackSession:
    session_id: str
    week_of: str
    production_calls_sampled: int
    failures_found: int
    categorizations: list[FailureCategorization] = field(default_factory=list)
    top_themes: list[str] = field(default_factory=list)
    golden_set_updates: list[str] = field(default_factory=list)
    ready_for_new_draft: bool = False


def categorize_failure(
    call_id: str,
    transcript: str,
    failing_evals: list[str],
    layer: str,
    proposed_fix: str
) -> FailureCategorization:
    """
    Record a manually categorized failure from production.

    Args:
        call_id:       ID of the production call
        transcript:    relevant snippet of the transcript
        failing_evals: which evals this call failed
        layer:         "A", "B", "C", or "D"
        proposed_fix:  what to change
    """
    if layer not in FAILURE_LAYERS:
        raise ValueError(f"Layer must be one of: {list(FAILURE_LAYERS.keys())}")

    layer_info = FAILURE_LAYERS[layer]
    print(f"\nLayer {layer} — {layer_info['name']}")
    print(f"Typical fix: {layer_info['fix']}")

    return FailureCategorization(
        call_id=call_id,
        transcript_snippet=transcript[:500],
        failing_evals=failing_evals,
        layer=layer,
        layer_name=layer_info["name"],
        proposed_fix=proposed_fix,
        reviewed_at=datetime.now(timezone.utc).isoformat()
    )


def update_golden_set(
    new_scenario: dict,
    golden_set_dir: str = "scenarios/golden_sets/",
    source: str = "production_failure"
) -> str:
    """
    Add a production failure as a new golden set scenario.
    This is how your eval set grows over time — failures in prod become test cases.

    Args:
        new_scenario: scenario dict with transcript, persona, expected_outcome
        golden_set_dir: where to save golden sets
        source: how this scenario was generated (production_failure, sme_interview, synthetic)

    Returns:
        path to saved scenario
    """
    os.makedirs(golden_set_dir, exist_ok=True)

    new_scenario["metadata"] = {
        "source": source,
        "added_at": datetime.now(timezone.utc).isoformat(),
        "human_vetted": True if source == "production_failure" else False
    }

    scenario_id = f"scenario_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    path = os.path.join(golden_set_dir, f"{scenario_id}.json")

    with open(path, "w") as f:
        json.dump(new_scenario, f, indent=2)

    print(f"Golden set updated: {path} (source: {source})")
    return path


def get_diagnosis_prompt(agent_config: str, eval_summary: str, transcripts: list[str]) -> str:
    """
    Returns the filled LLM diagnosis prompt for use with your LLM of choice.
    Paste the output into Claude, GPT-4, or run programmatically.
    """
    return LLM_DIAGNOSIS_PROMPT.format(
        agent_config=agent_config,
        eval_summary=eval_summary,
        transcripts="\n\n---\n\n".join(transcripts[:5])
    )


def print_layer_guide():
    """Print the failure layer reference guide."""
    print("\n=== FAILURE LAYER DIAGNOSTIC GUIDE ===\n")
    for layer_id, info in FAILURE_LAYERS.items():
        print(f"Layer {layer_id}: {info['name']}")
        print(f"  What it is: {info['description']}")
        print(f"  Fix:        {info['fix']}")
        print(f"  Signals:    {', '.join(info['evals_that_signal_this'])}")
        print()
