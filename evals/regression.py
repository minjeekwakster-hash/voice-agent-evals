"""
Regression Detection
---------------------
Compares current eval scores against a previous passing baseline.
Hard block evals cannot drop more than the configured tolerance (default 5pp).

This is the golden set regression check — run it every time you iterate on a draft.
If a hard block eval drops more than tolerance from its last passing score, promotion is blocked
even if the absolute score is still above threshold.

Usage:
    from evals.regression import check_regression
    result = check_regression(current_scores, baseline_path, config_path)
"""

import json
import yaml
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RegressionFlag:
    eval_name: str
    current_score: float
    baseline_score: float
    delta: float              # negative means regression (current < baseline)
    tolerance: float
    gate: str


@dataclass
class RegressionResult:
    passed: bool
    regressions: list[RegressionFlag] = field(default_factory=list)
    baseline_version: Optional[str] = None
    failure_reason: Optional[str] = None


def check_regression(
    current_scores: dict[str, float],
    baseline_path: Optional[str],
    config_path: str = "config/pipeline.yaml"
) -> RegressionResult:
    """
    Check current eval scores against a baseline report.

    Args:
        current_scores: dict of {eval_name: score} from the current run
        baseline_path:  path to a previous passing report JSON (or None to skip)
        config_path:    path to pipeline.yaml

    Returns:
        RegressionResult — passed=True if no hard block regressions exceed tolerance
    """
    if not baseline_path:
        return RegressionResult(
            passed=True,
            failure_reason=None,
            baseline_version="none (first run — current scores will become baseline)"
        )

    with open(config_path) as f:
        config = yaml.safe_load(f)

    tolerance = config["regression"]["tolerance"]
    hard_block_evals = {
        e["name"] for e in config["layer2"]["evals"]
        if e["gate"] == "hard_block"
    }

    try:
        with open(baseline_path) as f:
            baseline_report = json.load(f)
    except FileNotFoundError:
        return RegressionResult(
            passed=True,
            failure_reason=None,
            baseline_version="not found — treating as first run"
        )

    baseline_scores = baseline_report.get("layer2", {}).get("eval_scores", {})
    baseline_version = baseline_report.get("agent_version", "unknown")

    regressions = []

    for eval_name, current_score in current_scores.items():
        baseline_score = baseline_scores.get(eval_name)
        if baseline_score is None:
            continue

        delta = current_score - baseline_score  # negative = regression

        if eval_name in hard_block_evals and delta < -tolerance:
            regressions.append(RegressionFlag(
                eval_name=eval_name,
                current_score=round(current_score, 3),
                baseline_score=round(baseline_score, 3),
                delta=round(delta, 3),
                tolerance=tolerance,
                gate="hard_block"
            ))

    passed = len(regressions) == 0
    failure_reason = None
    if regressions:
        lines = [
            f"{r.eval_name}: {r.current_score} vs baseline {r.baseline_score} (dropped {abs(r.delta):.3f}, tolerance {r.tolerance})"
            for r in regressions
        ]
        failure_reason = "Regressions detected:\n" + "\n".join(lines)

    return RegressionResult(
        passed=passed,
        regressions=regressions,
        baseline_version=baseline_version,
        failure_reason=failure_reason
    )


def save_as_baseline(report: dict, output_path: str):
    """
    Save a passing eval report as the new baseline for future regression checks.
    Call this after a successful promotion to staging.
    """
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Baseline saved: {output_path}")
