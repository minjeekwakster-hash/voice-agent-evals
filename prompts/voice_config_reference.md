# Voice Config Reference

Configuration parameters that affect agent behavior at the platform level.
When Layer 1 evals fail or Layer 2 `turn_taking_flow` / `response_conciseness` scores drop, check here before touching the prompt.

These are Layer D failures. The prompt is not the problem.

---

## The Config–Eval Connection

| Config parameter | What it affects | Eval signal |
|-----------------|-----------------|-------------|
| `max_tokens` (LLM output) | Response length, interruption risk | `response_conciseness`, `turn_taking_flow` |
| `temperature` (LLM) | Naturalness vs. script adherence | `prompt_conformance`, `conversation_quality` |
| STT model | Transcription accuracy, latency | `query_handling`, `first_turn_latency` (Layer 1) |
| TTS voice / speed | Naturalness, perceived latency | `conversation_quality`, `turn_taking_flow` |
| End-of-turn detection | Whether agent talks over caller | `turn_taking_flow`, `dead_air_detection` (Layer 1) |

---

## LLM Parameters

### max_tokens

**Recommended: ~260 tokens for conversational turns.**

The single most common cause of an agent speaking over a customer is a response that's too long. Voice is not chat — a 400-token response that looks fine on screen takes 12–15 seconds to speak. If the caller starts talking at second 8, the agent either interrupts or produces dead air while it finishes.

Keep max_tokens tight. If your agent needs to convey more information, break it into two turns — the prompt's short sentences rule handles this at the instruction level, but max_tokens enforces it as a hard cap.

**When to adjust:**
- If `response_conciseness` scores drop and the prompt already has short sentence guidance → lower max_tokens
- If the agent is cutting off mid-sentence on complex answers → raise slightly (280–320) and audit which answers are too long

### temperature

**Recommended: 0.3–0.35**

This range keeps responses natural (not robotic) while staying close enough to the script that `prompt_conformance` scores remain high. It's the practical tradeoff between creative variation and instruction-following.

- **Below 0.2:** Responses become repetitive and mechanical. Callers notice. `conversation_quality` scores drop.
- **0.3–0.35:** Natural variation in phrasing while staying on-script. This is the production sweet spot.
- **Above 0.5:** The agent starts improvising. Value props get rephrased in ways that aren't accurate. `hallucination_detection` and `prompt_conformance` both degrade.

**When to adjust:**
- `prompt_conformance` failing → move toward 0.2–0.3
- `conversation_quality` or `turn_taking_flow` failing (sounds robotic) → move toward 0.35–0.4

---

## Speech-to-Text (STT)

### What to evaluate

STT accuracy directly affects `query_handling`. If the agent misunderstands the caller, it's often the STT layer, not the prompt.

**Dimensions to test:**
- **Accuracy on your caller population** — accents, background noise (especially for field-based callers like drivers, construction, warehouse)
- **Latency** — time from end of speech to transcript delivery. High STT latency causes `first_turn_latency` failures in Layer 1.
- **Filler word handling** — some STT models strip "um" and "uh" from transcripts, which can cause the agent to respond before the caller has actually finished

**Reference point:** Deepgram's Nova-3 / Flux models perform well on general English with background noise. If your callers have strong regional accents or speak in domain-specific vocabulary (e.g., industry jargon, product names), test accuracy explicitly on a sample before committing.

**Platform equivalents:**
| Platform | STT config location |
|----------|-------------------|
| Vapi | `transcriber` object in assistant config |
| Retell | `speech_to_text` in agent config |
| Bland | `voice` settings panel |
| LiveKit | STT plugin in agent pipeline |

---

## Text-to-Speech (TTS)

### What to evaluate

TTS affects perceived naturalness (`conversation_quality`) and turn-taking feel (`turn_taking_flow`). It does not affect factual accuracy evals.

**Dimensions to test:**

| Dimension | What to listen for |
|-----------|-------------------|
| **Naturalness** | Does it sound like a person? Prosody, emphasis, breath patterns |
| **Latency** | Time from LLM output to first audio byte. High TTS latency causes awkward pauses that callers interpret as dead air. |
| **Cloning viability** | If using a cloned voice, does it hold up under stress, questions, and long responses? Cloned voices often degrade on unusual phrasing. |
| **Consistency** | Does quality hold across 5–10 min calls? Some providers degrade on long sessions. |

**Tradeoff to know:** Higher naturalness providers typically add 100–300ms latency per turn. At 10 turns per call, that's 1–3 seconds of accumulated latency. For high-volume outbound calls, this tradeoff matters. Test with real call lengths, not just short demos.

**Voice options to test (in rough order of setup effort):**
1. Platform defaults — lowest latency, quickest to test, less natural
2. Off-the-shelf voices (ElevenLabs, Cartesia, PlayHT) — more natural, some latency cost
3. Voice cloning — highest naturalness if source audio is high quality, but degrades on unusual phrasing and adds setup complexity

**When to switch TTS:**
- `conversation_quality` scores below 0.70 and prompt/tone guidelines are already correct → TTS is the likely cause
- `turn_taking_flow` showing interruption patterns AND max_tokens is already tuned → check TTS latency

---

## End-of-Turn Detection

End-of-turn (EOT) detection determines when the agent decides the caller has finished speaking. It's one of the highest-impact and least-documented config parameters.

**What goes wrong:**
- **Too aggressive (short timeout):** Agent cuts in while caller is mid-sentence. Shows up as `turn_taking_flow` failures and caller frustration.
- **Too conservative (long timeout):** Awkward silence after caller finishes. Callers interpret this as dead air and repeat themselves or hang up. Shows up in `dead_air_detection` (Layer 1) and `turn_taking_flow`.

**Tuning approach:** Start with the platform default. If you see turn-taking failures in your transcripts, check whether the agent is interrupting (shorten response, not EOT) or whether there's silence before the agent responds (adjust EOT timeout). These are different problems with different fixes.

**Platform equivalents:**
| Platform | EOT config |
|----------|-----------|
| Vapi | `endCallPhrases`, `silenceTimeoutSeconds`, `responsiveness` in assistant config |
| Retell | `end_call_after_silence_ms` |
| Bland | Endpoint detection settings in voice config |

---

## Diagnosing Layer D vs. Layer A Failures

Before changing any voice config, confirm the failure is actually Layer D. A common mistake: seeing `turn_taking_flow` or `response_conciseness` fail and immediately adjusting TTS or max_tokens — when the real cause is a prompt instruction that's generating long responses.

**Check order:**
1. Read the failing transcripts. Is the agent saying too much (prompt fix) or saying the right amount but still getting cut off (config fix)?
2. Is `dead_air_detection` (Layer 1) also failing? If yes, this is almost certainly Layer D.
3. Is `prompt_conformance` also failing? If yes, fix the prompt first. Config changes won't help if the agent isn't following instructions.
4. If Layer 1 passes and only `turn_taking_flow` / `response_conciseness` are failing → try max_tokens adjustment first, then EOT.
