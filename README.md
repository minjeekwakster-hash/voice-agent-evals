# voice-agent-ops

**A framework for deploying Voice AI agents to production with confidence.**

Most teams ship voice agents the same way: build it, test it manually, cross their fingers. This framework gives you a structured eval pipeline — two-layer quality gates, golden set regression detection, LLM judge calibration, and a staged promotion process — so you know exactly why an agent passes or fails, and catch degradation before your users do.

Built from patterns used to run a production Voice AI platform at 200+ daily sessions.

---

## The problem

Shipping a voice agent without an eval pipeline means:

- No consistent way to know if a new version is better or worse than the last
- Human QA that doesn't scale and produces inconsistent results
- Platform failures (latency, dead air) confused with prompt failures
- No safety net when quality degrades silently in production
- Deployment decisions based on gut feel instead of data

---

## How it works

The pipeline has two eval layers that run **concurrently** on the same simulated calls — not sequentially. Layer 1 is a hard gate: if the platform is broken, stop. Don't debug the prompt when the voice stack is the problem.

```
                    ┌─────────────────────────────────┐
                    │         Simulated Calls          │
                    └──────────────┬──────────────────┘
                                   │
               ┌───────────────────┴───────────────────┐
               │                                       │
       Layer 1: Platform                      Layer 2: Agent Quality
       (Hard gate — blocks all)               (Only if Layer 1 passes)
               │                                       │
       • first_turn_latency              • 6 hard block evals
       • avg_call_latency                • 7 warning evals
       • dead_air_detection              • Regression check vs baseline
       • call_connection_success         • Autorater calibration
       • termination_handling
               │                                       │
               └───────────────────┬───────────────────┘
                                   │
                           PASS → Staging
                           FAIL → Iterate
```

### The 9-stage deployment pipeline

| Stage | What happens | Gate |
|-------|-------------|------|
| 1. Use case definition | Define personas, KPIs, escalation strategy | - |
| 2. Draft creation | Write prompt, configure voice settings | - |
| 3. Dataset preparation | Build 10+ eval scenarios (transcripts + synthetic) | Soft gate: min 10 scenarios |
| 4. Deploy to test | Deploy draft to test environment | - |
| 5. Automated evals | Run Layer 1 + Layer 2 on simulated calls | Hard gate: all Layer 1 + Layer 2 hard blocks |
| 5a. Regression check | Compare scores vs previous passing baseline | Hard gate: no hard block drops >5pp |
| 6. Deploy to staging | Promote after evals pass | Requires staging readiness gate |
| 7. Human QA | Manual review of 10+ scenarios + autorater calibration | 80% human sign-off required |
| 8. Pre-prod dry run | Full E2E integration test | Hard gate: no errors |
| 8a. Canary | 10% traffic to new version for 24hrs (updates only) | Monitor key metrics |
| 9. Production | Full rollout with monitoring | - |

---

## Layer 1 — Platform health evals

Run on every simulated call. If any hard block fails, **stop and fix the platform before touching the prompt**.

| Eval | What it checks | Threshold | Gate |
|------|---------------|-----------|------|
| `first_turn_latency` | Time from connect to agent first word | ≥90% calls <1200ms | Hard block |
| `avg_call_latency` | Average response latency per turn | ≥90% calls <1200ms | Hard block |
| `dead_air_detection` | >3s silence mid-conversation | 0 failures | Hard block |
| `call_connection_success` | Call connected and agent responded | 0 failures | Hard block |
| `termination_handling` | Agent correctly ended or transferred call | ≥90% pass rate | Hard block |

---

## Layer 2 — Agent quality evals

LLM-judge scoring across 13 dimensions. Only runs after Layer 1 passes.

| Eval | Threshold | Gate | Why |
|------|-----------|------|-----|
| `prompt_conformance` | ≥80% | Hard block | If the agent ignores its own prompt, nothing else is reliable |
| `escalation_accuracy` | ≥90% | Hard block | Wrong escalation = real business damage |
| `query_handling` | ≥80% | Hard block | Core competency |
| `loop_detection` | 100% | Hard block | A looping agent is a broken agent |
| `hallucination_detection` | ≥80% | Hard block | Fabricated information is a trust-killer |
| `task_completion` | ≥75% | Hard block | The agent's primary job |
| `context_retention` | ≥70% | Warning | Flag for human review at staging |
| `conversation_quality` | ≥70% | Warning | Subjective — human-validated at staging |
| `objection_handling` | ≥70% | Warning | Varies by scenario mix |
| `context_adherence` | ≥70% | Warning | Overlaps with hallucination — track separately |
| `response_conciseness` | ≥60% | Warning | Nice to have |
| `greeting_quality` | ≥80% | Warning | Sets the tone |
| `turn_taking_flow` | ≥80% | Warning | Voice-specific UX |

---

## Regression detection

Every eval run is compared against the last passing baseline. Hard block evals **cannot drop more than 5 percentage points** from their previous passing score — even if the absolute score is still above threshold.

A score of 0.82 looks fine. It doesn't look fine if the previous version scored 0.91. Absolute thresholds catch failures; regression detection catches degradation.

---

## Autorater calibration

LLM judges are fast and consistent but can drift from human judgment over time. The calibration module compares LLM scores against human reviewer scores across a sample of calls. If the match rate drops below 80%, your automated thresholds need recalibration.

Calibrate:
- Monthly in production
- Any time you change the judge model
- Any time human reviewers flag unexpected results

---

## Quickstart

```bash
git clone https://github.com/minjeekwakster-hash/voice-agent-evals
cd voice-agent-ops
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here   # or any LiteLLM-supported model
```

**1. Configure your agent**

Copy and edit `config/pipeline.yaml` with your agent details, thresholds, and personas.

**2. Run evals**

```python
from evals.layer1_platform import run_layer1
from evals.layer2_agent import run_layer2
from evals.regression import check_regression

# Layer 1 — platform health
l1 = run_layer1(call_metrics)          # list of call metric dicts
if not l1.passed:
    print(l1.failure_reason)           # fix platform, don't touch the prompt
    exit(1)

# Layer 2 — agent quality
l2 = run_layer2(transcripts)           # list of transcript strings
regression = check_regression(
    {e.name: e.score for e in l2.eval_scores},
    baseline_path="reports/baseline.json"
)
```

**3. Check promotion gate**

```bash
python pipeline/promote.py --report reports/eval_report.json --to staging
```

**4. Run the dashboard**

```bash
streamlit run dashboard/app.py
```

Point it at your `reports/` directory to see Layer 1/2 scores, regression deltas, calibration status, and promotion readiness.

**5. Track agent state**

```python
from pipeline.state_machine import AgentDraft

draft = AgentDraft.create("support-agent", "1.2.0")
draft.transition("DEPLOYED_TO_TEST")
draft.transition("EVALS_IN_PROGRESS")
draft.transition("EVALS_PASSED")
draft.save()
```

---

## Iterating when evals fail

Route your fix to the right layer — don't rewrite the prompt when the problem is in the voice config.

| Failing evals | Likely cause | Fix |
|---------------|-------------|-----|
| `hallucination_detection`, `prompt_conformance`, `context_adherence` | **Layer A — Prompt** | Rewrite failing section, add constraints |
| `query_handling`, `context_retention`, `task_completion` | **Layer B — Tool / RAG** | Update knowledge base, fix tool definitions |
| `escalation_accuracy`, `task_completion` | **Layer C — Routing** | Update escalation conditions |
| `turn_taking_flow`, `response_conciseness` + Layer 1 flags | **Layer D — Voice config** | STT model, TTS speed, end-of-turn detection, token budget |

Use `feedback/loop.py` for the LLM-assisted diagnosis prompt — paste your config, eval results, and failing transcripts to get a structured root cause analysis.

```python
from feedback.loop import get_diagnosis_prompt

# Pull eval results directly from a pipeline report
prompt = get_diagnosis_prompt(
    agent_config="[your system prompt + voice config]",
    transcripts=["transcript 1...", "transcript 2..."],
    report_path="reports/eval_report.json"   # auto-extracts failing evals
)
# Send `prompt` to Claude, GPT-4o, or any LLM
```

---

## Prompts

The `prompts/` directory contains production-hardened templates built from patterns used to achieve 26–30% conversion from connected calls.

**[`prompts/system_prompt_template.md`](prompts/system_prompt_template.md)** — A structured starter template for your agent's system prompt. Annotated with which Layer 2 eval dimensions each section protects, so when a score drops you know exactly where to look.

**[`prompts/voice_config_reference.md`](prompts/voice_config_reference.md)** — LLM and voice stack tuning guide. Covers `max_tokens` for interruption prevention, `temperature` for naturalness vs. script adherence, STT model selection, TTS evaluation criteria, and end-of-turn detection. Includes a diagnostic checklist for separating Layer D (config) failures from Layer A (prompt) failures.

---

## Project structure

```
voice-agent-evals/
├── config/
│   └── pipeline.yaml          # Agent config, eval thresholds, stage requirements
├── evals/
│   ├── layer1_platform.py     # Platform health checks
│   ├── layer2_agent.py        # 13 agent quality evals (LLM judge via LiteLLM)
│   ├── regression.py          # Golden set regression detection
│   └── calibration.py         # Autorater calibration (LLM vs human)
├── pipeline/
│   ├── state_machine.py       # EDITING → TEST → EVALS → STAGING → PROD
│   └── promote.py             # Gate enforcement per stage
├── prompts/
│   ├── system_prompt_template.md   # Starter template, annotated with eval dimensions
│   └── voice_config_reference.md  # LLM + STT/TTS tuning guide
├── scenarios/
│   ├── generate.py            # LLM-assisted scenario generation
│   └── golden_sets/           # Vetted eval scenarios
├── feedback/
│   └── loop.py                # Post-production failure categorization + golden set update
├── dashboard/
│   └── app.py                 # Streamlit pipeline dashboard
└── reports/
    └── example_report.json    # Sample report (use to test dashboard)
```

---

## LLM support

Layer 2 evals use [LiteLLM](https://github.com/BerriAI/litellm) — swap in any model by changing `model` in `pipeline.yaml`:

```yaml
layer2:
  llm_judge:
    model: "claude-3-5-sonnet-20241022"   # Anthropic
    # model: "gpt-4o"                     # OpenAI
    # model: "gemini/gemini-1.5-pro"      # Google
    # model: "ollama/llama3"              # Local via Ollama
```

---

## What this doesn't include

Bot-to-bot call simulation and canary traffic routing are intentionally out of scope — they depend on your voice platform. This framework assumes you can produce call transcripts and metrics from your own stack (Vapi, Bland, Retell, LiveKit, etc.) and feeds them into the eval pipeline.

---

## Built by

[Minji Gwak](https://github.com/minjeekwakster-hash) — Senior PM with engineering background. Built the production version of this pipeline at Mudflap, where it scaled a Voice AI platform to 200+ daily sessions and reduced agent deployment cycle time by 90%+.
