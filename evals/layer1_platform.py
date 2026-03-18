"""
Layer 1: Platform Health Evals
-------------------------------
Checks if the voice platform was healthy during simulated calls.
These are agent-agnostic. If Layer 1 fails, stop — it's a platform issue, not a prompt issue.

Input: list of call metric dicts (from your voice platform's call logs)
Output: Layer1Result with pass/fail per check and an overall gate decision

Expected call metric format:
{
    "call_id": "abc123",
    "first_turn_latency_ms": 850,
    "avg_latency_ms": 1050,
    "dead_air_detected": false,
    "call_connected": true,
    "termination_handled": true
}
"""

from dataclasses import dataclass, field
from typing import Optional
import yaml


@dataclass
class EvalResult:
    name: str
    passed: bool
    pass_rate: Optional[float]
    failures: int
    total: int
    threshold: Optional[float]
    gate: str
    detail: str


@dataclass
class Layer1Result:
    passed: bool                          # True only if ALL hard blocks pass
    eval_results: list[EvalResult] = field(default_factory=list)
    failure_reason: Optional[str] = None


def run_layer1(calls: list[dict], config_path: str = "config/pipeline.yaml") -> Layer1Result:
    """
    Run all Layer 1 platform health checks against a list of call metrics.
    Returns Layer1Result. If passed=False, do not proceed to Layer 2.
    """
    with open(config_path) as f:
        config = yaml.safe_load(f)

    eval_configs = {e["name"]: e for e in config["layer1"]["evals"]}
    results = []
    n = len(calls)

    if n == 0:
        return Layer1Result(passed=False, failure_reason="No calls provided")

    # first_turn_latency
    cfg = eval_configs["first_turn_latency"]
    passing = [c for c in calls if c.get("first_turn_latency_ms", 9999) <= cfg["threshold_ms"]]
    pass_rate = len(passing) / n
    passed = pass_rate >= cfg["pass_rate_required"]
    results.append(EvalResult(
        name="first_turn_latency",
        passed=passed,
        pass_rate=round(pass_rate, 3),
        failures=n - len(passing),
        total=n,
        threshold=cfg["pass_rate_required"],
        gate=cfg["gate"],
        detail=f"{len(passing)}/{n} calls under {cfg['threshold_ms']}ms"
    ))

    # avg_call_latency
    cfg = eval_configs["avg_call_latency"]
    passing = [c for c in calls if c.get("avg_latency_ms", 9999) <= cfg["threshold_ms"]]
    pass_rate = len(passing) / n
    passed = pass_rate >= cfg["pass_rate_required"]
    results.append(EvalResult(
        name="avg_call_latency",
        passed=passed,
        pass_rate=round(pass_rate, 3),
        failures=n - len(passing),
        total=n,
        threshold=cfg["pass_rate_required"],
        gate=cfg["gate"],
        detail=f"{len(passing)}/{n} calls at acceptable latency"
    ))

    # dead_air_detection
    cfg = eval_configs["dead_air_detection"]
    failures = [c for c in calls if c.get("dead_air_detected", False)]
    allowed = cfg.get("allowed_failures", 0)
    passed = len(failures) <= allowed
    results.append(EvalResult(
        name="dead_air_detection",
        passed=passed,
        pass_rate=round(1 - len(failures) / n, 3),
        failures=len(failures),
        total=n,
        threshold=None,
        gate=cfg["gate"],
        detail=f"{len(failures)} dead air events (allowed: {allowed})"
    ))

    # call_connection_success
    cfg = eval_configs["call_connection_success"]
    failures = [c for c in calls if not c.get("call_connected", True)]
    allowed = cfg.get("allowed_failures", 0)
    passed = len(failures) <= allowed
    results.append(EvalResult(
        name="call_connection_success",
        passed=passed,
        pass_rate=round(1 - len(failures) / n, 3),
        failures=len(failures),
        total=n,
        threshold=None,
        gate=cfg["gate"],
        detail=f"{len(failures)} connection failures (allowed: {allowed})"
    ))

    # termination_handling
    cfg = eval_configs["termination_handling"]
    passing = [c for c in calls if c.get("termination_handled", True)]
    pass_rate = len(passing) / n
    passed = pass_rate >= cfg["pass_rate_required"]
    results.append(EvalResult(
        name="termination_handling",
        passed=passed,
        pass_rate=round(pass_rate, 3),
        failures=n - len(passing),
        total=n,
        threshold=cfg["pass_rate_required"],
        gate=cfg["gate"],
        detail=f"{len(passing)}/{n} calls handled termination correctly"
    ))

    # Overall: all hard blocks must pass
    hard_failures = [r for r in results if r.gate == "hard_block" and not r.passed]
    overall_passed = len(hard_failures) == 0
    failure_reason = None
    if hard_failures:
        failure_reason = f"Layer 1 hard block failures: {[r.name for r in hard_failures]}. Fix platform issues before checking agent quality."

    return Layer1Result(
        passed=overall_passed,
        eval_results=results,
        failure_reason=failure_reason
    )
