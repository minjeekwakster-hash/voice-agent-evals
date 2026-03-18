"""
Voice Agent Ops — Pipeline Dashboard
Streamlit visual layer. Reads JSON reports from the CLI pipeline.

Run: streamlit run dashboard/app.py
"""

import json
import os
import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="Voice Agent Ops",
    page_icon="🎙️",
    layout="wide"
)

# ── Helpers ──────────────────────────────────────────────────────────────────

def load_report(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def status_badge(passed: bool, pass_label="PASS", fail_label="FAIL") -> str:
    if passed:
        return f"🟢 {pass_label}"
    return f"🔴 {fail_label}"


def warning_badge(passed: bool) -> str:
    return "🟢 OK" if passed else "🟡 WARN"


STAGE_ORDER = ["EDITING", "DEPLOYED_TO_TEST", "EVALS_IN_PROGRESS",
               "EVALS_PASSED", "EVALS_FAILED", "PROMOTED_TO_STAGING",
               "PROMOTED_TO_PREPROD", "PROMOTED_TO_PROD"]

STAGE_DISPLAY = {
    "EDITING":              "1 · Editing",
    "DEPLOYED_TO_TEST":     "2 · Test",
    "EVALS_IN_PROGRESS":    "3 · Evaluating",
    "EVALS_PASSED":         "4 · Evals Passed ✓",
    "EVALS_FAILED":         "4 · Evals Failed ✗",
    "PROMOTED_TO_STAGING":  "5 · Staging",
    "PROMOTED_TO_PREPROD":  "6 · Pre-Prod",
    "PROMOTED_TO_PROD":     "7 · Production ✓"
}

# ── Sidebar ───────────────────────────────────────────────────────────────────

st.sidebar.title("🎙️ Voice Agent Ops")
st.sidebar.markdown("---")

report_dir = st.sidebar.text_input("Reports directory", value="reports/")
report_files = []
if os.path.exists(report_dir):
    report_files = [f for f in os.listdir(report_dir) if f.endswith(".json") and "state" not in f]

if not report_files:
    st.sidebar.warning("No reports found. Run an eval first.")
    st.info("No reports found. Run the eval pipeline and point to your reports directory.")
    st.stop()

selected_file = st.sidebar.selectbox("Select report", sorted(report_files, reverse=True))
report = load_report(os.path.join(report_dir, selected_file))

st.sidebar.markdown("---")
st.sidebar.caption(f"Evaluated: {report.get('evaluated_at', 'unknown')}")

# ── Header ────────────────────────────────────────────────────────────────────

col1, col2, col3, col4 = st.columns([3, 2, 2, 2])

with col1:
    st.markdown(f"### {report.get('agent_name', 'Agent')} `v{report.get('agent_version', '?')}`")
    st.caption(f"Draft ID: `{report.get('draft_id', 'unknown')}`")

current_stage = report.get("current_stage", "EDITING")
with col2:
    st.metric("Pipeline Stage", STAGE_DISPLAY.get(current_stage, current_stage))

l1_passed = report.get("layer1", {}).get("passed", False)
l2_passed = report.get("layer2", {}).get("passed", False)
with col3:
    st.metric("Layer 1", "✓ Pass" if l1_passed else "✗ Fail")

with col4:
    st.metric("Layer 2", "✓ Pass" if l2_passed else "✗ Fail")

st.markdown("---")

# ── Layer 1: Platform Health ──────────────────────────────────────────────────

st.subheader("Layer 1 — Platform Health")
st.caption("Agent-agnostic. If this fails, stop — it's a platform issue, not a prompt issue.")

l1 = report.get("layer1", {})
l1_results = l1.get("eval_results", [])

if l1_results:
    rows = []
    for r in l1_results:
        rows.append({
            "Check": r["name"],
            "Status": status_badge(r["passed"]),
            "Pass Rate": f"{r['pass_rate']:.0%}" if r.get("pass_rate") else "—",
            "Failures": f"{r['failures']}/{r['total']}",
            "Gate": r["gate"],
            "Detail": r["detail"]
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

if not l1_passed and l1.get("failure_reason"):
    st.error(f"**Layer 1 blocked:** {l1['failure_reason']}")
    st.warning("Fix platform issues before reviewing agent quality scores.")
    st.stop()

st.markdown("---")

# ── Layer 2: Agent Quality ────────────────────────────────────────────────────

st.subheader("Layer 2 — Agent Quality")
st.caption("LLM-judge scores across 13 dimensions. Hard blocks must pass. Warnings flag for human review.")

l2 = report.get("layer2", {})
eval_scores = l2.get("eval_scores", {})

if eval_scores:
    hard_rows = []
    warn_rows = []

    for name, e in eval_scores.items():
        row = {
            "Eval": name,
            "Score": round(e["score"], 2),
            "Threshold": e["threshold"],
            "Status": status_badge(e["passed"]) if e["gate"] == "hard_block" else warning_badge(e["passed"]),
            "Gate": e["gate"],
            "Confidence": e.get("confidence", "—"),
            "Reasoning": e.get("reasoning", "—")
        }
        if e["gate"] == "hard_block":
            hard_rows.append(row)
        else:
            warn_rows.append(row)

    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("**Hard Blocks**")
        if hard_rows:
            df_hard = pd.DataFrame(hard_rows)
            st.dataframe(df_hard[["Eval", "Score", "Threshold", "Status", "Confidence"]], use_container_width=True, hide_index=True)

    with col_right:
        st.markdown("**Warnings**")
        if warn_rows:
            df_warn = pd.DataFrame(warn_rows)
            st.dataframe(df_warn[["Eval", "Score", "Threshold", "Status", "Confidence"]], use_container_width=True, hide_index=True)

    # Score chart
    st.markdown("**Score vs Threshold**")
    chart_data = {e: eval_scores[e]["score"] for e in eval_scores}
    threshold_data = {e: eval_scores[e]["threshold"] for e in eval_scores}
    df_chart = pd.DataFrame({"Score": chart_data, "Threshold": threshold_data})
    st.bar_chart(df_chart)

    # Warnings detail
    warnings = l2.get("warnings", [])
    if warnings:
        with st.expander(f"⚠️ {len(warnings)} warning(s) — review at staging"):
            for w in warnings:
                if w in eval_scores:
                    st.write(f"**{w}**: {eval_scores[w].get('reasoning', '')}")

if not l2_passed:
    failures = l2.get("hard_block_failures", [])
    st.error(f"**Layer 2 blocked:** Hard block failures: {failures}")

st.markdown("---")

# ── Regression ────────────────────────────────────────────────────────────────

st.subheader("Regression Check")
reg = report.get("regression", {})
reg_passed = reg.get("passed", True)
baseline = reg.get("baseline_version", "none")

col1, col2 = st.columns(2)
with col1:
    st.metric("Result", "✓ No regressions" if reg_passed else "✗ Regressions detected")
with col2:
    st.metric("Baseline version", baseline)

regressions = reg.get("regressions", [])
if regressions:
    rows = []
    for r in regressions:
        rows.append({
            "Eval": r["eval_name"],
            "Current": r["current_score"],
            "Baseline": r["baseline_score"],
            "Delta": r["delta"],
            "Tolerance": f"±{r['tolerance']}"
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.error(reg.get("failure_reason", "Regressions detected"))
else:
    st.success("All hard block evals stable vs baseline.")

st.markdown("---")

# ── Autorater Calibration ─────────────────────────────────────────────────────

st.subheader("Autorater Calibration")
st.caption("How well does the LLM judge agree with human reviewers? Below 80% = recalibrate thresholds.")

cal = report.get("calibration", {})
cal_passed = cal.get("passed", False)
match_rate = cal.get("overall_match_rate", 0)
sample_size = cal.get("sample_size", 0)

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Overall Match Rate", f"{match_rate:.0%}")
with col2:
    st.metric("Status", "✓ Calibrated" if cal_passed else "✗ Needs Recalibration")
with col3:
    st.metric("Sample Size", f"{sample_size} calls")

dim_results = cal.get("dimension_results", [])
if dim_results:
    rows = [{"Dimension": d["eval_name"], "Match Rate": f"{d['match_rate']:.0%}",
             "Human Avg": d["human_avg"], "LLM Avg": d["llm_avg"],
             "Bias": f"{'+' if d['bias'] >= 0 else ''}{d['bias']:.2f}",
             "Calibrated": "✓" if d["calibrated"] else "✗"} for d in dim_results]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

if cal.get("recommendation"):
    st.warning(cal["recommendation"])

st.markdown("---")

# ── Promotion Readiness ───────────────────────────────────────────────────────

st.subheader("Promotion Readiness")

scenario_count = report.get("scenario_count", 0)
staging_signoff = report.get("staging_signoff", False)
preprod_passed = report.get("preprod_passed", False)

checks = [
    ("Layer 1 platform pass",      l1_passed),
    ("Layer 2 hard blocks pass",   l2_passed),
    ("No regressions",             reg_passed),
    (f"Min 10 scenarios ({scenario_count} found)", scenario_count >= 10),
    ("Human QA sign-off",          staging_signoff),
    ("Pre-prod dry run complete",  preprod_passed),
]

cols = st.columns(3)
for i, (label, passed) in enumerate(checks):
    with cols[i % 3]:
        icon = "✅" if passed else "⬜"
        st.markdown(f"{icon} {label}")

overall_ready = all(p for _, p in checks)
if overall_ready:
    st.success("**Ready for production.** All gates passed.")
else:
    remaining = [label for label, passed in checks if not passed]
    st.info(f"**Not yet ready.** Outstanding: {', '.join(remaining)}")
