"""
Autorater Calibration
----------------------
Measures how well your LLM judge agrees with human scores.
Run this at staging after human QA to validate your automated thresholds.

If match rate drops below the configured minimum (default 80%), your LLM judge
thresholds need recalibration — the automated scores are drifting from human judgment.

Calibration should be run:
- Monthly in production
- Any time you change the LLM judge model
- Any time human reviewers flag unexpected pass/fail patterns

Usage:
    from evals.calibration import run_calibration
    result = run_calibration(human_scores, llm_scores, config_path)
"""

import yaml
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DimensionCalibration:
    eval_name: str
    match_rate: float           # % of calls where human and LLM agreed (within tolerance)
    human_avg: float
    llm_avg: float
    bias: float                 # positive = LLM scores higher than human
    sample_size: int
    calibrated: bool            # True if match_rate >= min_match_rate


@dataclass
class CalibrationResult:
    passed: bool                # True if all calibrated dims meet min_match_rate
    overall_match_rate: float
    dimension_results: list[DimensionCalibration] = field(default_factory=list)
    uncalibrated_dims: list[str] = field(default_factory=list)
    sample_size: int = 0
    recommendation: Optional[str] = None


def _scores_agree(human: float, llm: float, tolerance: float = 0.15) -> bool:
    """Two scores agree if they're within tolerance of each other."""
    return abs(human - llm) <= tolerance


def run_calibration(
    human_scores: dict[str, list[float]],
    llm_scores: dict[str, list[float]],
    config_path: str = "config/pipeline.yaml",
    agreement_tolerance: float = 0.15
) -> CalibrationResult:
    """
    Compare human annotation scores against LLM judge scores.

    Args:
        human_scores: {eval_name: [score_call1, score_call2, ...]}
        llm_scores:   {eval_name: [score_call1, score_call2, ...]}
        config_path:  path to pipeline.yaml
        agreement_tolerance: how close scores must be to count as agreement (default 0.15)

    Returns:
        CalibrationResult with per-dimension match rates and overall pass/fail
    """
    with open(config_path) as f:
        config = yaml.safe_load(f)

    cal_config = config["calibration"]
    min_match_rate = cal_config["min_match_rate"]
    min_sample = cal_config["sample_size"]
    calibrate_on = set(cal_config["calibrate_on"])

    dimension_results = []
    uncalibrated = []
    total_agreements = 0
    total_comparisons = 0

    for eval_name in calibrate_on:
        h_scores = human_scores.get(eval_name, [])
        l_scores = llm_scores.get(eval_name, [])

        # Align to same length
        pairs = list(zip(h_scores, l_scores))
        if len(pairs) < min_sample:
            uncalibrated.append(eval_name)
            continue

        agreements = sum(1 for h, l in pairs if _scores_agree(h, l, agreement_tolerance))
        match_rate = round(agreements / len(pairs), 3)

        human_avg = round(sum(h for h, _ in pairs) / len(pairs), 3)
        llm_avg = round(sum(l for _, l in pairs) / len(pairs), 3)
        bias = round(llm_avg - human_avg, 3)

        total_agreements += agreements
        total_comparisons += len(pairs)

        calibrated = match_rate >= min_match_rate
        if not calibrated:
            uncalibrated.append(eval_name)

        dimension_results.append(DimensionCalibration(
            eval_name=eval_name,
            match_rate=match_rate,
            human_avg=human_avg,
            llm_avg=llm_avg,
            bias=bias,
            sample_size=len(pairs),
            calibrated=calibrated
        ))

    overall_match_rate = round(total_agreements / total_comparisons, 3) if total_comparisons > 0 else 0.0
    passed = len(uncalibrated) == 0 and total_comparisons > 0

    recommendation = None
    if uncalibrated:
        biased = [d for d in dimension_results if abs(d.bias) > 0.15]
        if biased:
            dims = [f"{d.eval_name} (LLM bias: {'+' if d.bias > 0 else ''}{d.bias})" for d in biased]
            recommendation = (
                f"LLM judge is consistently off on: {', '.join(dims)}. "
                f"Consider adjusting thresholds or rewriting judge prompts for these dimensions."
            )
        else:
            recommendation = (
                f"Match rate below {min_match_rate} on: {uncalibrated}. "
                f"Collect more labeled examples and re-run calibration."
            )

    return CalibrationResult(
        passed=passed,
        overall_match_rate=overall_match_rate,
        dimension_results=dimension_results,
        uncalibrated_dims=uncalibrated,
        sample_size=total_comparisons,
        recommendation=recommendation
    )
