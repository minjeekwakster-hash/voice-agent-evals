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

LLM_DIAGNOSIS_PROMPT = """You are a voice AI agent operations expert specializing in production voice agent quality.
Diagnose failures in my voice agent and recommend specific fixes.

## Current agent configuration
{agent_config}

## Eval results summary
{eval_summary}

## Failing call transcripts
{transcripts}

## What I need

1. ROOT CAUSE ANALYSIS: For each failing eval, identify whether the root cause is:
   - Layer A (Prompt): agent said the wrong thing, hallucinated, didn't follow instructions, or went off-brand
   - Layer B (Tool/RAG): wrong tool call, stale knowledge base, bad retrieval, incorrect data mapping
   - Layer C (Routing): wrong escalation decision — transferred when it shouldn't have, or didn't transfer when it should have
   - Layer D (Voice config): latency, STT transcription error, TTS naturalness, end-of-turn detection, token budget

   Cite the specific transcript evidence that supports each diagnosis.

2. SPECIFIC FIXES: For each root cause, provide the exact change — not "strengthen the prompt" but:
   - Layer A: the actual text to add, modify, or remove from the system prompt
   - Layer B: the specific tool definition or knowledge base entry to update
   - Layer C: the exact escalation condition to add or modify
   - Layer D: the specific config parameter and recommended value (e.g., max_tokens: 260, temperature: 0.32)

3. REGRESSION RISK: For each fix, flag which existing passing evals might be affected. Which golden set scenarios should be re-run after this change?

4. PRIORITY ORDER: If there are multiple fixes, rank them by:
   - Hard-block eval failures first
   - Fixes that address multiple failing evals at once
   - Fixes with lowest regression risk last

Return as structured JSON with keys: root_causes, specific_fixes, regression_risks, priority_order."""


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


def get_diagnosis_prompt(
    agent_config: str,
    transcripts: list[str],
    eval_summary: Optional[str] = None,
    report_path: Optional[str] = None,
) -> str:
    """
    Returns the filled LLM diagnosis prompt for use with your LLM of choice.
    Paste the output into Claude, GPT-4o, or run programmatically via LiteLLM.

    Args:
        agent_config:  The agent's full system prompt and voice config (paste as string)
        transcripts:   List of failing call transcript strings (3-5 recommended)
        eval_summary:  Eval results as a string (optional if report_path is provided)
        report_path:   Path to a pipeline eval report JSON — if provided, extracts
                       failing evals automatically and formats the summary

    Returns:
        Filled prompt string ready to send to an LLM
    """
    if eval_summary is None and report_path is not None:
        with open(report_path) as f:
            report = json.load(f)
        eval_summary = _format_report_summary(report)
    elif eval_summary is None:
        eval_summary = "[No eval summary provided]"

    return LLM_DIAGNOSIS_PROMPT.format(
        agent_config=agent_config,
        eval_summary=eval_summary,
        transcripts="\n\n---\n\n".join(transcripts[:5])
    )


def _format_report_summary(report: dict) -> str:
    """Format a pipeline eval report JSON into a readable diagnosis summary."""
    lines = []
    lines.append(f"Agent: {report.get('agent_name')} v{report.get('agent_version')}")
    lines.append(f"Stage: {report.get('current_stage')}")

    l1 = report.get("layer1", {})
    lines.append(f"\nLayer 1 (Platform): {'PASS' if l1.get('passed') else 'FAIL'}")
    for r in l1.get("eval_results", []):
        if not r["passed"]:
            lines.append(f"  FAIL {r['name']}: {r['detail']}")

    l2 = report.get("layer2", {})
    lines.append(f"\nLayer 2 (Agent Quality): {'PASS' if l2.get('passed') else 'FAIL'}")
    lines.append(f"Overall score: {l2.get('overall_score')}")
    for name, e in l2.get("eval_scores", {}).items():
        status = "FAIL" if not e["passed"] else ("WARN" if e["gate"] == "warning" else "PASS")
        lines.append(f"  {status} {name}: score={e['score']} threshold={e['threshold']} — {e.get('reasoning', '')}")

    reg = report.get("regression", {})
    if not reg.get("passed"):
        lines.append(f"\nRegression: FAIL vs baseline {reg.get('baseline_version')}")
        for r in reg.get("regressions", []):
            lines.append(f"  {r['eval_name']}: {r['current_score']} vs {r['baseline_score']} (delta {r['delta']})")

    return "\n".join(lines)


def print_layer_guide():
    """Print the failure layer reference guide."""
    print("\n=== FAILURE LAYER DIAGNOSTIC GUIDE ===\n")
    for layer_id, info in FAILURE_LAYERS.items():
        print(f"Layer {layer_id}: {info['name']}")
        print(f"  What it is: {info['description']}")
        print(f"  Fix:        {info['fix']}")
        print(f"  Signals:    {', '.join(info['evals_that_signal_this'])}")
        print()
