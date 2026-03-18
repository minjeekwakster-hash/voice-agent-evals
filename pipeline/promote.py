"""
Promotion Gate Enforcer
------------------------
Checks all gate requirements before allowing an agent to move to the next stage.
Reads the eval report + state machine and enforces the rules defined in pipeline.yaml.

Usage:
    python pipeline/promote.py --report reports/eval_report.json --to staging
"""

import argparse
import json
import sys
import yaml
from dataclasses import dataclass
from typing import Optional


@dataclass
class GateCheck:
    name: str
    passed: bool
    detail: str


@dataclass
class PromotionResult:
    approved: bool
    from_stage: str
    to_stage: str
    checks: list[GateCheck]
    blocking_failures: list[str]


def load_report(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def check_gate(report: dict, to_stage: str, config: dict) -> PromotionResult:
    """Evaluate all gate checks for promoting to the given stage."""

    stage_config = next(
        (s for s in config["promotion"]["stages"] if s["name"] == to_stage), None
    )
    if not stage_config:
        raise ValueError(f"Stage '{to_stage}' not found in config")

    current_stage = report.get("current_stage", "test")
    checks = []
    blocking = []

    requirements = stage_config.get("requires", [])

    # Layer 1 pass
    if "layer1_pass" in requirements:
        passed = report.get("layer1", {}).get("passed", False)
        check = GateCheck("layer1_pass", passed, "All platform health checks passed" if passed else report.get("layer1", {}).get("failure_reason", "Layer 1 failed"))
        checks.append(check)
        if not passed:
            blocking.append("layer1_pass")

    # Layer 2 hard blocks
    if "layer2_hard_blocks_pass" in requirements:
        passed = report.get("layer2", {}).get("passed", False)
        failures = report.get("layer2", {}).get("hard_block_failures", [])
        check = GateCheck(
            "layer2_hard_blocks_pass",
            passed,
            "All hard block evals passed" if passed else f"Hard block failures: {failures}"
        )
        checks.append(check)
        if not passed:
            blocking.append("layer2_hard_blocks_pass")

    # Regression check
    if "regression_pass" in requirements:
        passed = report.get("regression", {}).get("passed", True)
        detail = "No regressions detected" if passed else report.get("regression", {}).get("failure_reason", "Regression detected")
        check = GateCheck("regression_pass", passed, detail)
        checks.append(check)
        if not passed:
            blocking.append("regression_pass")

    # Minimum scenario count
    if "min_10_scenarios" in requirements:
        scenario_count = report.get("scenario_count", 0)
        passed = scenario_count >= 10
        check = GateCheck(
            "min_10_scenarios",
            passed,
            f"{scenario_count}/10 scenarios evaluated"
        )
        checks.append(check)
        if not passed:
            blocking.append("min_10_scenarios")

    # Human staging sign-off
    if "staging_human_signoff" in requirements:
        passed = report.get("staging_signoff", False)
        check = GateCheck(
            "staging_human_signoff",
            passed,
            "Human QA sign-off recorded" if passed else "Awaiting human QA sign-off at staging"
        )
        checks.append(check)
        if not passed:
            blocking.append("staging_human_signoff")

    # Preprod pass
    if "preprod_pass" in requirements:
        passed = report.get("preprod_passed", False)
        check = GateCheck(
            "preprod_pass",
            passed,
            "Pre-prod dry run passed" if passed else "Pre-prod dry run not completed"
        )
        checks.append(check)
        if not passed:
            blocking.append("preprod_pass")

    approved = len(blocking) == 0

    return PromotionResult(
        approved=approved,
        from_stage=current_stage,
        to_stage=to_stage,
        checks=checks,
        blocking_failures=blocking
    )


def print_result(result: PromotionResult, agent_name: str, version: str):
    print(f"\n{'='*60}")
    print(f"PROMOTION GATE: {result.from_stage.upper()} -> {result.to_stage.upper()}")
    print(f"Agent: {agent_name} v{version}")
    print(f"{'-'*60}")
    for check in result.checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"  [{status}] {check.name}: {check.detail}")
    print(f"{'-'*60}")
    print(f"DECISION: {'APPROVED' if result.approved else 'BLOCKED'}")
    if result.blocking_failures:
        print(f"Blocking: {result.blocking_failures}")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Check promotion gate before advancing stages")
    parser.add_argument("--report", required=True, help="Path to eval report JSON")
    parser.add_argument("--to", required=True, choices=["staging", "preprod", "prod"], dest="to_stage")
    parser.add_argument("--config", default="config/pipeline.yaml")
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)

    report = load_report(args.report)
    result = check_gate(report, args.to_stage, config)
    print_result(result, config["agent"]["name"], config["agent"]["version"])

    sys.exit(0 if result.approved else 1)


if __name__ == "__main__":
    main()
