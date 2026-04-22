"""
monceai.Synthax — deep-reasoning flagship. $12/query, unlimited tokens.

Synthax is an orchestrated chain — not a race. A specialist's output becomes
the next specialist's input. Every job is a mini CI pipeline for answers:
recall → plan → draft → render → adversary → revise → verify → arbiter →
notify. Each stage is an artifact. The whole run is replayable, auditable,
budget-capped.

    from monceai import Synthax

    s = Synthax("design an auth layer for a glass factory portal")

    str(s)              # TL;DR (≤ 3 lines, Haiku-compacted)
    s.answer            # exhaustive arbitrated answer (Sonnet)
    s.job.stages        # [Stage(name, source, text, ms, cost_usd)]
    s.job.artifacts     # {"draft": "...", "schema": "...", "adversary": "...", ...}
    s.job.cost_usd      # 3.42
    s.job.elapsed_ms    # 47210
    s.job.confidence    # 0.92
    s.job.doubts        # residual concerns the adversary found
    s.replay(from_="revise", with_extra="also consider session rotation")

Default budget: $12. Hard cap, no overruns. Soft warning at $10. Planner
stage chooses the pipeline per prompt — math questions skip Architect,
architecture skips SAT, glass prompts insert Moncey + Matching.
"""

from __future__ import annotations

import json as _json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .llm import (
    LLMResult, _chat, _report_usage, _resolve_model,
    DEFAULT_ENDPOINT, Architect, Concierge,
)


# ─────────────────────────────────────────────────────────────────────────────
# Cost model — USD per call, rough averages. Used for the $12 accumulator.
# These are not meant to be billing-exact; they exist to cap runaway jobs.
# ─────────────────────────────────────────────────────────────────────────────

_COST_USD: Dict[str, float] = {
    "haiku":             0.003,
    "sonnet":            0.015,
    "sonnet4":           0.015,
    "charles":           0.010,
    "charles-science":   0.012,
    "charles-json":      0.010,
    "charles-architect": 0.010,
    "charles-auma":      0.003,
    "concise":           0.008,
    "cc":                0.020,
    "moncey":            0.003,
    "concierge":         0.005,
    "matching":          0.000,    # CPU, free
    "calc":              0.000,    # CPU, free
    "snake":             0.050,    # Lambda classifier
    "sat":               0.100,    # Lambda SAT solver
}


def _cost_for(source: str) -> float:
    """Look up marginal cost for a stage source tag."""
    return _COST_USD.get(source, 0.010)


# ─────────────────────────────────────────────────────────────────────────────
# Stage + Job — the typed record of every step
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Stage:
    """One step in a Synthax pipeline."""
    name: str                      # "recall", "draft", "adversary", ...
    source: str                    # "haiku" / "sonnet" / "charles-science" / …
    prompt: str = ""
    text: str = ""
    elapsed_ms: int = 0
    cost_usd: float = 0.0
    skipped: bool = False
    reason: str = ""               # why skipped / notes
    meta: dict = field(default_factory=dict)

    def __repr__(self):
        if self.skipped:
            return f"Stage({self.name}: SKIPPED — {self.reason})"
        preview = self.text[:60].replace("\n", " ")
        return (f"Stage({self.name} via {self.source}, "
                f"{self.elapsed_ms}ms, ${self.cost_usd:.3f}, "
                f"text={preview!r})")


@dataclass
class SynthaxJob:
    """Full pipeline state + audit trail."""
    prompt: str
    budget_usd: float = 12.0
    stages: List[Stage] = field(default_factory=list)
    cost_usd: float = 0.0
    elapsed_ms: int = 0
    confidence: float = 0.0
    doubts: List[str] = field(default_factory=list)
    tldr: str = ""
    answer: str = ""
    arbiter_rationale: str = ""
    over_budget: bool = False

    @property
    def artifacts(self) -> Dict[str, str]:
        """Map stage name → text, for easy lookup."""
        return {s.name: s.text for s in self.stages if not s.skipped}

    @property
    def sources_used(self) -> List[str]:
        return [s.source for s in self.stages if not s.skipped]

    def ref(self, stage_name: str) -> str:
        """Resolve a '$stage' reference into its text. Empty str if missing."""
        for s in self.stages:
            if s.name == stage_name and not s.skipped:
                return s.text
        return ""

    def _record(self, stage: Stage):
        self.stages.append(stage)
        self.cost_usd += stage.cost_usd

    def _has_budget(self, next_cost: float = 0.0) -> bool:
        return (self.cost_usd + next_cost) <= self.budget_usd


# ─────────────────────────────────────────────────────────────────────────────
# Low-level helpers — one call → one Stage
# ─────────────────────────────────────────────────────────────────────────────

def _run_llm_stage(job: SynthaxJob, name: str, source: str,
                   prompt: str, endpoint: str, timeout: int = 90) -> Stage:
    """Fire one /v1/chat call tagged as a named stage. Budget-guarded."""
    cost = _cost_for(source)
    if not job._has_budget(cost):
        st = Stage(name=name, source=source, prompt=prompt,
                   skipped=True, reason=f"budget_exhausted "
                                        f"(${job.cost_usd:.2f}/${job.budget_usd:.2f})")
        job._record(st)
        job.over_budget = True
        return st

    t = time.time()
    r = _chat(text=prompt, model=_resolve_model(source),
              endpoint=endpoint, timeout=timeout)
    elapsed = int((time.time() - t) * 1000)

    st = Stage(
        name=name, source=source, prompt=prompt,
        text=r.text, elapsed_ms=elapsed, cost_usd=cost,
        meta={
            "model": r.model,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "sat_memory": r.sat_memory,
        },
    )
    job._record(st)
    return st


# ─────────────────────────────────────────────────────────────────────────────
# The planner — Haiku classifies the prompt → picks the pipeline
# ─────────────────────────────────────────────────────────────────────────────

_PLANNER_PROMPT = """You are the planner for Synthax — a deep-reasoning pipeline.
Classify the user prompt into exactly one bucket and return STRICT JSON.

Buckets:
- "math"          : arithmetic, factoring, roots, optimization, proofs.
- "architecture"  : system design, schemas, diagrams, code organization.
- "glass"         : glass industry, Monce factories, verre/intercalaire,
                    client names, quotes, devis.
- "classify"      : does X belong to class Y? labeling, binary decisions.
- "logic"         : SAT-like, 3-coloring, scheduling, combinatorial.
- "reasoning"     : everything else — explain, compare, decide.

Return JSON with keys:
  bucket        — one of the strings above.
  need_memory   — true if Concierge/Charles memory would help.
  need_render   — true if an ASCII diagram clarifies the answer.
  need_verify   — true if a deterministic check (Calc/SAT/Snake) applies.
  need_glass    — true if the answer depends on factory/glass data.
  factory_id    — integer 1/3/4/9/10/13 if a specific factory is implied,
                  else 0.

User prompt:
<<<
{prompt}
>>>

Return ONLY the JSON object, no commentary."""


def _plan(job: SynthaxJob, endpoint: str) -> dict:
    """Haiku planner. Returns {bucket, need_*, factory_id}."""
    st = _run_llm_stage(
        job, "plan", "haiku",
        _PLANNER_PROMPT.format(prompt=job.prompt),
        endpoint, timeout=20,
    )
    if st.skipped:
        return {"bucket": "reasoning", "need_memory": True,
                "need_render": False, "need_verify": False,
                "need_glass": False, "factory_id": 0}

    text = st.text.strip()
    # Try to extract JSON even if Haiku wraps it in prose
    try:
        if "{" in text:
            text = text[text.find("{"):text.rfind("}") + 1]
        plan = _json.loads(text)
    except Exception:
        plan = {}

    return {
        "bucket":       plan.get("bucket", "reasoning"),
        "need_memory":  bool(plan.get("need_memory", True)),
        "need_render":  bool(plan.get("need_render", False)),
        "need_verify":  bool(plan.get("need_verify", False)),
        "need_glass":   bool(plan.get("need_glass", False)),
        "factory_id":   int(plan.get("factory_id") or 0),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Recall — Concierge search, cheap, surfaces prior jobs on the same topic
# ─────────────────────────────────────────────────────────────────────────────

def _recall(job: SynthaxJob) -> Stage:
    """Search Concierge memory for hits relevant to the prompt."""
    cost = _cost_for("concierge")
    if not job._has_budget(cost):
        st = Stage(name="recall", source="concierge", skipped=True,
                   reason="budget_exhausted")
        job._record(st)
        return st

    t = time.time()
    hits = Concierge.search(job.prompt, limit=5)
    elapsed = int((time.time() - t) * 1000)

    if not hits:
        text = ""
        reason = "no_hits"
    else:
        text = "\n".join(f"- {h[:200]}" for h in hits if h)
        reason = f"{len(hits)}_hits"

    st = Stage(
        name="recall", source="concierge",
        prompt=job.prompt, text=text,
        elapsed_ms=elapsed, cost_usd=cost,
        reason=reason, meta={"hits": len(hits)},
    )
    job._record(st)
    return st


# ─────────────────────────────────────────────────────────────────────────────
# Verify — deterministic backstop (Calc / Snake / SAT)
# Right now we fire Calc on numeric expressions; Snake/SAT wire-up comes with
# api key plumbing on the server side.
# ─────────────────────────────────────────────────────────────────────────────

def _verify(job: SynthaxJob, draft_text: str, endpoint: str) -> Stage:
    """Extract numeric expressions from the draft and Calc-verify them.
    Cheap, deterministic, 0 tokens. Future: dispatch SAT/Snake claims too."""
    import re
    # Any pattern like '12x34', '44.2 * 16' → run through Calc endpoint.
    pattern = re.compile(r"\b(\d+(?:\.\d+)?)\s*([x\*/%+\-])\s*(\d+(?:\.\d+)?)\b")
    exprs = list({f"{m.group(1)}{m.group(2)}{m.group(3)}"
                  for m in pattern.finditer(draft_text)})[:10]

    if not exprs:
        st = Stage(name="verify", source="calc", skipped=True,
                   reason="no_numeric_claims")
        job._record(st)
        return st

    results = []
    import requests
    t = time.time()
    for e in exprs:
        try:
            r = requests.post(f"{endpoint}/v1/calc",
                              json={"expression": e}, timeout=10)
            if r.status_code == 200:
                results.append(f"{e} = {r.json().get('result')}")
        except Exception:
            pass
    elapsed = int((time.time() - t) * 1000)

    text = "\n".join(results) if results else ""
    st = Stage(
        name="verify", source="calc",
        prompt=f"verify: {len(exprs)} expressions",
        text=text, elapsed_ms=elapsed, cost_usd=0.0,
        meta={"expressions": exprs, "verified": len(results)},
    )
    job._record(st)
    return st


# ─────────────────────────────────────────────────────────────────────────────
# Synthax class — the public face
# ─────────────────────────────────────────────────────────────────────────────

class Synthax(str):
    """Deep-reasoning flagship. ``str(s)`` is the TL;DR, ``s.answer`` the full one.

    Examples
    --------
    >>> s = Synthax("design auth for a glass factory portal")
    >>> str(s)                     # TL;DR
    >>> s.answer                   # exhaustive
    >>> s.job.cost_usd             # ≤ 12.0
    >>> s.job.stages               # full timeline
    >>> s.job.artifacts["draft"]   # specific stage output
    """

    def __new__(cls, prompt: str = None, budget_usd: float = 12.0,
                endpoint: str = None, timeout: int = 300,
                notify: bool = True):
        if prompt is None:
            client = object.__new__(_SynthaxClient)
            client._endpoint = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
            client._budget_usd = budget_usd
            client._timeout = timeout
            client._notify = notify
            return client

        job = _run_pipeline(prompt, budget_usd,
                            (endpoint or DEFAULT_ENDPOINT).rstrip("/"),
                            timeout=timeout, notify=notify)

        instance = super().__new__(cls, job.tldr or job.answer)
        instance.job = job
        instance._endpoint = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
        instance._timeout = timeout
        return instance

    @property
    def answer(self) -> str:
        """Full Sonnet-arbitrated answer (not compacted)."""
        return self.job.answer

    @property
    def tldr(self) -> str:
        """Haiku TL;DR — same as ``str(self)``."""
        return self.job.tldr

    @property
    def cost_usd(self) -> float:
        return self.job.cost_usd

    @property
    def elapsed_ms(self) -> int:
        return self.job.elapsed_ms

    def replay(self, from_: str, with_extra: str = "") -> "Synthax":
        """Re-run the pipeline from a given stage, optionally adding a hint.

        The existing stages up to ``from_`` (exclusive) are inherited as-is,
        and a fresh pipeline continues from that point. Costs and elapsed
        time accumulate across the resumed portion only.
        """
        return _replay_from(self, from_, with_extra=with_extra)

    def report(self) -> str:
        """Human-readable stage-by-stage audit."""
        lines = [
            "═" * 72,
            f"SYNTHAX  prompt: {self.job.prompt[:60]}...",
            f"cost: ${self.job.cost_usd:.2f} / ${self.job.budget_usd:.2f}"
            f"   elapsed: {self.job.elapsed_ms}ms"
            f"   confidence: {self.job.confidence:.2f}",
            "─" * 72,
        ]
        for s in self.job.stages:
            if s.skipped:
                lines.append(f"  · {s.name:<10} SKIPPED ({s.reason})")
            else:
                preview = s.text[:80].replace("\n", " ")
                lines.append(f"  · {s.name:<10} {s.source:<18} "
                             f"{s.elapsed_ms:>5}ms ${s.cost_usd:.3f}  {preview}")
        lines += [
            "─" * 72,
            f"TL;DR: {self.job.tldr}",
            "─" * 72,
            "ANSWER:", self.job.answer,
        ]
        if self.job.doubts:
            lines += ["─" * 72, "DOUBTS:"]
            for d in self.job.doubts:
                lines.append(f"  ? {d}")
        lines.append("═" * 72)
        return "\n".join(lines)

    def __repr__(self):
        return (f"Synthax(prompt={self.job.prompt[:40]!r}, "
                f"cost=${self.job.cost_usd:.2f}, "
                f"stages={len(self.job.stages)})")


class _SynthaxClient:
    """Reusable client: ``Synthax()`` with no args, then call repeatedly."""

    def __call__(self, prompt: str, **kw) -> Synthax:
        return Synthax(
            prompt,
            budget_usd=kw.get("budget_usd", self._budget_usd),
            endpoint=self._endpoint,
            timeout=kw.get("timeout", self._timeout),
            notify=kw.get("notify", self._notify),
        )

    def __repr__(self):
        return (f"Synthax(endpoint={self._endpoint!r}, "
                f"budget_usd={self._budget_usd})")


# ─────────────────────────────────────────────────────────────────────────────
# The pipeline — recall → plan → draft → render → adversary → revise →
#                verify → arbiter → notify
# ─────────────────────────────────────────────────────────────────────────────

def _run_pipeline(prompt: str, budget_usd: float, endpoint: str,
                  timeout: int = 300, notify: bool = True) -> SynthaxJob:
    """Execute one Synthax job. Returns the fully-populated SynthaxJob."""
    t0 = time.time()
    job = SynthaxJob(prompt=prompt, budget_usd=budget_usd)

    # 1. Recall — Concierge search (cheap, always run)
    _recall(job)

    # 2. Plan — Haiku picks the pipeline
    plan = _plan(job, endpoint)

    # Map bucket → draft source
    draft_source = {
        "math":         "charles-auma",
        "logic":        "charles-science",
        "classify":     "charles-science",
        "architecture": "charles-science",
        "glass":        "moncey",
        "reasoning":    "charles",
    }.get(plan["bucket"], "charles")

    # 3. Draft — specialist produces the first pass
    recall_ctx = job.ref("recall")
    recall_block = (f"\n\n[prior memories surfaced by Concierge]\n{recall_ctx}\n"
                    if recall_ctx else "")
    draft_prompt = f"{prompt}{recall_block}"
    _run_llm_stage(job, "draft", draft_source, draft_prompt,
                   endpoint, timeout=timeout)

    # 4. Render — Architect diagrams the draft (when useful)
    if plan["need_render"] and job._has_budget(_cost_for("charles-architect")):
        render_prompt = (
            f"Draw an ASCII diagram that captures the structure of this answer.\n\n"
            f"QUESTION: {prompt}\n\nANSWER:\n{job.ref('draft')}"
        )
        _run_llm_stage(job, "render", "charles-architect",
                       render_prompt, endpoint, timeout=timeout)
    else:
        job._record(Stage(name="render", source="charles-architect",
                          skipped=True,
                          reason="not_requested_by_plan"))

    # 5. Adversary — cold Sonnet, no memory, attacks the draft
    adv_prompt = (
        f"You are a cold-start adversarial reviewer. You have NOT seen this "
        f"question before. Find at most 3 specific weaknesses in the proposed "
        f"answer below — unjustified assumptions, missing edge cases, factual "
        f"drift, or logical holes. Be terse. Use a bullet list.\n\n"
        f"QUESTION: {prompt}\n\n"
        f"PROPOSED ANSWER:\n{job.ref('draft')}\n\n"
        f"WEAKNESSES (up to 3 bullets):"
    )
    _run_llm_stage(job, "adversary", "sonnet", adv_prompt,
                   endpoint, timeout=timeout)

    # 6. Revise — charles-json patches the draft using the adversary's notes
    revise_prompt = (
        f"Revise the draft to address the adversary's weaknesses. Output a "
        f"single improved answer as STRICT JSON with keys:\n"
        f"  answer       — the revised full answer (string)\n"
        f"  confidence   — float 0..1\n"
        f"  residual_doubts — list of remaining concerns (strings)\n\n"
        f"QUESTION: {prompt}\n\n"
        f"DRAFT:\n{job.ref('draft')}\n\n"
        f"ADVERSARY NOTES:\n{job.ref('adversary')}"
    )
    revise_st = _run_llm_stage(job, "revise", "charles-json",
                               revise_prompt, endpoint, timeout=timeout)

    # Parse revise JSON eagerly so downstream stages can use it
    revised_answer = revise_st.text
    confidence = 0.7
    residual_doubts: List[str] = []
    try:
        t = revise_st.text.strip()
        if "{" in t:
            t = t[t.find("{"):t.rfind("}") + 1]
        payload = _json.loads(t)
        if isinstance(payload, dict):
            revised_answer = str(payload.get("answer") or revised_answer)
            confidence = float(payload.get("confidence") or confidence)
            rd = payload.get("residual_doubts") or []
            if isinstance(rd, list):
                residual_doubts = [str(x) for x in rd if x]
    except Exception:
        pass

    # 7. Verify — deterministic check on numeric claims
    if plan["need_verify"]:
        _verify(job, revised_answer, endpoint)
    else:
        job._record(Stage(name="verify", source="calc", skipped=True,
                          reason="not_requested_by_plan"))

    # 8. Arbiter — Sonnet synthesizes TL;DR + confidence + final answer
    verify_block = ""
    v = job.ref("verify")
    if v:
        verify_block = f"\n\nDETERMINISTIC CHECKS:\n{v}"

    render_block = ""
    r = job.ref("render")
    if r:
        render_block = f"\n\nSTRUCTURAL RENDER:\n{r}"

    arb_prompt = (
        f"You are the arbiter for Synthax. Return STRICT JSON with:\n"
        f"  tldr         — a concise summary (≤ 3 sentences, ≤ 280 chars total)\n"
        f"  answer       — the final exhaustive answer\n"
        f"  confidence   — float 0..1\n"
        f"  doubts       — list of residual doubts (strings, may be empty)\n"
        f"  rationale    — one sentence on why you chose this synthesis\n\n"
        f"Base the answer on the revised draft. Prefer the deterministic "
        f"checks (Calc/SAT/Snake) over LLM claims where they disagree.\n\n"
        f"QUESTION: {prompt}\n\n"
        f"REVISED DRAFT:\n{revised_answer}"
        f"{verify_block}{render_block}\n\n"
        f"ADVERSARY NOTES (for context, not gospel):\n{job.ref('adversary')}"
    )
    arb_st = _run_llm_stage(job, "arbiter", "sonnet", arb_prompt,
                            endpoint, timeout=timeout)

    # Parse arbiter JSON
    tldr = ""
    answer = revised_answer
    rationale = ""
    doubts = residual_doubts[:]
    try:
        t = arb_st.text.strip()
        if "{" in t:
            t = t[t.find("{"):t.rfind("}") + 1]
        payload = _json.loads(t)
        if isinstance(payload, dict):
            tldr = str(payload.get("tldr") or "").strip()
            answer = str(payload.get("answer") or answer)
            confidence = float(payload.get("confidence") or confidence)
            rationale = str(payload.get("rationale") or "")
            d = payload.get("doubts") or []
            if isinstance(d, list):
                doubts = [str(x) for x in d if x]
    except Exception:
        pass

    if not tldr:
        # Haiku fallback to guarantee a TL;DR even if the arbiter misbehaves
        tldr_prompt = (
            f"Compact this answer to at most 3 sentences, max 280 chars "
            f"total. Plain text, no markdown, no preamble.\n\n{answer}"
        )
        tldr_st = _run_llm_stage(job, "tldr", "haiku", tldr_prompt,
                                 endpoint, timeout=30)
        tldr = tldr_st.text.strip()

    job.tldr = tldr
    job.answer = answer
    job.confidence = max(0.0, min(1.0, confidence))
    job.doubts = doubts
    job.arbiter_rationale = rationale

    # 9. Notify — log this verdict to Concierge so next Synthax recalls it
    if notify and job._has_budget(_cost_for("concierge")):
        try:
            summary = (f"[synthax {plan['bucket']}] Q: {prompt[:120]} | "
                       f"A: {tldr[:200]} | conf={job.confidence:.2f}")
            Concierge.remember(summary, source="synthax",
                               tags=["synthax", plan["bucket"]])
            job._record(Stage(
                name="notify", source="concierge",
                text="remembered", cost_usd=_cost_for("concierge"),
                meta={"bucket": plan["bucket"]},
            ))
        except Exception as e:
            job._record(Stage(name="notify", source="concierge",
                              skipped=True, reason=f"error:{e}"))
    else:
        job._record(Stage(name="notify", source="concierge", skipped=True,
                          reason="disabled" if not notify else "budget_exhausted"))

    job.elapsed_ms = int((time.time() - t0) * 1000)

    # Best-effort usage report — piggybacks on the existing /usage sink
    try:
        fake_result = LLMResult(
            text=job.tldr, model="synthax",
            elapsed_ms=job.elapsed_ms,
            sat_memory={
                "bucket": plan.get("bucket"),
                "sources": job.sources_used,
                "cost_usd": round(job.cost_usd, 4),
                "confidence": round(job.confidence, 3),
                "over_budget": job.over_budget,
                "winner": "synthax",
            },
        )
        _report_usage(endpoint, f"synthax:{prompt[:80]}", fake_result)
    except Exception:
        pass

    return job


def _replay_from(orig: Synthax, from_stage: str,
                 with_extra: str = "") -> Synthax:
    """Resume the pipeline from ``from_stage`` with an optional hint.

    Cheap approximation: we re-run the pipeline with a spiked prompt
    that includes the original draft as context and the extra hint as
    a new constraint. The inherited stages are not literally reused —
    they're summarised as context. This keeps the API simple without
    introducing a second cached-stage code path.
    """
    prior_artifacts = orig.job.artifacts
    context_blocks = []
    for stage_name in ("recall", "draft", "render", "adversary", "revise"):
        if stage_name == from_stage:
            break
        if stage_name in prior_artifacts and prior_artifacts[stage_name]:
            context_blocks.append(
                f"[prior {stage_name}]\n{prior_artifacts[stage_name]}"
            )

    spiked = orig.job.prompt
    if context_blocks:
        spiked += "\n\n" + "\n\n".join(context_blocks)
    if with_extra:
        spiked += f"\n\n[additional constraint]\n{with_extra}"

    remaining_budget = max(0.5, orig.job.budget_usd - orig.job.cost_usd)
    return Synthax(spiked, budget_usd=remaining_budget,
                   endpoint=orig._endpoint, timeout=orig._timeout)
