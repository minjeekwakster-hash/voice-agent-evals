"""
Layer 2: Agent Quality Evals
------------------------------
LLM-judge scoring across 13 dimensions. Only runs after Layer 1 passes.
Hard block evals must all pass to promote. Warning evals flag for human review.

Uses LiteLLM so you can swap in any model (Claude, GPT-4, Gemini, local via Ollama).

Usage:
    from evals.layer2_agent import run_layer2
    result = run_layer2(transcripts, config_path="config/pipeline.yaml")
"""

import json
import yaml
from dataclasses import dataclass, field
from typing import Optional


JUDGE_SYSTEM_PROMPT = """You are an expert evaluator for Voice AI agents.
Score call transcripts objectively. Be consistent and calibrated.
Return only valid JSON — no explanation outside the JSON object."""

JUDGE_PROMPT = """Evaluate this Voice AI call transcript on the dimension: "{dimension}"

Definition: {definition}

Transcript:
{transcript}

Score from 0.0 to 1.0 where:
- 1.0 = fully meets the definition
- 0.5 = partially meets it
- 0.0 = fails completely

Return JSON with exactly these keys:
{{
  "score": <float 0.0-1.0>,
  "reasoning": "<one sentence>",
  "confidence": "high" | "medium" | "low"
}}"""

EVAL_DEFINITIONS = {
    "prompt_conformance": "The agent followed its system prompt and stayed within its defined instructions throughout the call.",
    "escalation_accuracy": "The agent transferred to a human agent when appropriate and did not transfer when it was not necessary.",
    "query_handling": "The agent correctly understood and addressed the caller's question or request.",
    "loop_detection": "The agent did not repeat the same response or get stuck in a repetitive loop. Score 1.0 if no loops, 0.0 if any loop detected.",
    "hallucination_detection": "The agent did not state information that was not grounded in its context or knowledge base.",
    "task_completion": "The agent successfully completed the primary goal of the call or correctly escalated when it could not.",
    "context_retention": "The agent remembered and correctly used information from earlier in the conversation.",
    "conversation_quality": "The agent's tone was natural, professional, and appropriate for the caller's emotional state.",
    "objection_handling": "The agent addressed pushback, frustration, or objections from the caller in a constructive way.",
    "context_adherence": "The agent stayed within its defined knowledge boundary and did not speculate beyond its scope.",
    "response_conciseness": "The agent's responses were appropriately brief without omitting important information.",
    "greeting_quality": "The agent opened the call with a correct, professional, and complete greeting.",
    "turn_taking_flow": "The agent handled pauses, interruptions, and conversation turns naturally without awkward silences or talking over the caller."
}


@dataclass
class EvalScore:
    name: str
    score: float
    threshold: float
    gate: str
    passed: bool
    reasoning: str
    confidence: str


@dataclass
class Layer2Result:
    passed: bool                              # True if all hard blocks pass
    overall_score: float
    eval_scores: list[EvalScore] = field(default_factory=list)
    hard_block_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failure_reason: Optional[str] = None


def _score_transcript(transcript: str, eval_name: str, model: str, client) -> dict:
    """Score a single eval dimension on a single transcript."""
    definition = EVAL_DEFINITIONS.get(eval_name, eval_name)
    prompt = JUDGE_PROMPT.format(
        dimension=eval_name,
        definition=definition,
        transcript=transcript
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        temperature=0,
        max_tokens=256
    )
    raw = response.choices[0].message.content.strip()
    return json.loads(raw)


def run_layer2(
    transcripts: list[str],
    config_path: str = "config/pipeline.yaml"
) -> Layer2Result:
    """
    Run all Layer 2 agent quality evals across a list of transcripts.
    Aggregates scores per eval dimension, checks thresholds.

    Args:
        transcripts: list of call transcript strings
        config_path: path to pipeline.yaml

    Returns:
        Layer2Result with per-eval scores and overall pass/fail
    """
    with open(config_path) as f:
        config = yaml.safe_load(f)

    l2_config = config["layer2"]
    model = l2_config["llm_judge"]["model"]
    eval_configs = {e["name"]: e for e in l2_config["evals"]}

    try:
        import litellm
        client = litellm
    except ImportError:
        raise ImportError("litellm required: pip install litellm")

    n = len(transcripts)
    if n == 0:
        return Layer2Result(passed=False, overall_score=0.0, failure_reason="No transcripts provided")

    # Score each eval across all transcripts, then average
    eval_results: list[EvalScore] = []
    total_weighted = 0.0
    total_weight = len(eval_configs)

    for eval_name, eval_cfg in eval_configs.items():
        scores = []
        last_reasoning = ""
        last_confidence = "medium"

        for transcript in transcripts:
            try:
                result = _score_transcript(transcript, eval_name, model, client)
                scores.append(float(result["score"]))
                last_reasoning = result.get("reasoning", "")
                last_confidence = result.get("confidence", "medium")
            except Exception as e:
                print(f"  Warning: scoring failed for {eval_name}: {e}")
                scores.append(0.5)  # neutral fallback

        avg_score = sum(scores) / len(scores)
        threshold = eval_cfg["threshold"]
        passed = avg_score >= threshold

        eval_results.append(EvalScore(
            name=eval_name,
            score=round(avg_score, 3),
            threshold=threshold,
            gate=eval_cfg["gate"],
            passed=passed,
            reasoning=last_reasoning,
            confidence=last_confidence
        ))
        total_weighted += avg_score

    overall_score = round(total_weighted / total_weight, 3)
    hard_block_failures = [e.name for e in eval_results if e.gate == "hard_block" and not e.passed]
    warnings = [e.name for e in eval_results if e.gate == "warning" and not e.passed]

    passed = len(hard_block_failures) == 0
    failure_reason = None
    if hard_block_failures:
        failure_reason = f"Hard block failures: {hard_block_failures}"

    return Layer2Result(
        passed=passed,
        overall_score=overall_score,
        eval_scores=eval_results,
        hard_block_failures=hard_block_failures,
        warnings=warnings,
        failure_reason=failure_reason
    )
