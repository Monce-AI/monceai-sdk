# MonceOS — Manifest

One constructor. Bricks consume verbs, not primitives.

```python
from monceai import MonceOS
os = MonceOS(factory_id=4, tenant="riou", framework_id="field_riou_test")
```

---

## Why this exists

The SDK primitives (`LLM`, `Json`, `Matching`, `Calc`, `Concierge`, `Moncey`,
`Architect`, `Extraction`, `Outlook`, `Snake`, `SAT`) are complete and
composable. Bricks (Field, Orders, Quotes, Concierge app) need **composition**,
not more primitives. MonceOS is that composition layer:

- binds `factory_id` · `tenant` · `framework_id` · `session_id` once
- routes every verb through proprietary Monce models (`charles-json`,
  `moncey`, `concierge`) — never bare Haiku/Sonnet
- returns typed dataclasses (`CR`, `Action`, `Contact`, `NextStep`, `Brief`)
  so brick code stops reshaping dicts

It does **not** replace the primitives. `monceai.monceos` is an additive
subpackage. `llm.py`, `matching.py`, `extraction.py`, `outlook.py`, `snake.py`,
`sat.py`, `report.py` are untouched.

---

## Scope

| In scope | Out of scope |
|----------|--------------|
| Factory-scoped AI verbs (capture, match, verify, brief, route, export) | Postgres / RDS schema |
| S3 persistence + audit log (via `os.store`) | Cognito / auth pools (OS accepts pre-authed tenant) |
| Session state + multi-turn | PWA / React / Next.js |
| Typed data contracts between bricks | ERP write-backs (Orders brick owns) |
| STT cost/latency logging | Route optimization, photos, planograms (V2/V3) |

---

## Guarantees

- **Proprietary first.** Default models: `charles-json` for extraction,
  `moncey` for glass domain, `concierge` for account memory Q&A.
  Raw Bedrock only when the caller passes `model=` explicitly.
- **Enum-clamped outputs.** `owner_team` ∈ `{sales_ops, service, quoting,
  logistics}`; `priority` ∈ `{high, medium, low}`; `sentiment` ∈
  `{positive, neutral, negative}`. Model drift gets mapped, not rejected.
- **NP-verified arithmetic.** Every `amount_eur` runs through `Calc`; the
  model never does math.
- **Tenant scope is durable.** The constructor binds it; every sub-call
  inherits it; no per-call `tenant_id=` arguments scattered.
- **No new runtime deps.** Still `requests` only.

---

## Verb ladder (iter plan)

| Iter | Verb | Unlocks for bricks | Status |
|-----:|------|--------------------|:------:|
| 1 | `MonceOS._call` + framework binding       | any brick POSTs with tenant scope       | ✓ v1.2.4 |
| 2 | `os.capture(transcript=...)` + `CR`       | Field's 5-extraction contract           | ✓ v1.2.4 |
| 3 | `os.match.client` / `.contact` / `.article` + `is_new` diff | Field screen 2 contacts, Pain 2 | planned |
| 4 | `os.verify.amount` / `.date`              | exact arithmetic + ISO dates            | planned |
| 5 | `os.store` (S3 · local · memory)          | permanency, GDPR delete, audit log      | planned |
| 6 | `os.memory` — Concierge + CSV fallback    | integrated + standalone modes           | planned |
| 7 | `os.brief(account_id)`                    | Field screen 2 — pre-visit brief        | planned |
| 8 | `os.route(actions)` — Snake classifier    | Field action plan routing               | planned |
| 9 | `os.capture(audio_bytes=...)` — STT       | full voice pipeline (Deepgram/Whisper)  | planned |
| 10 | `os.export.pdf` / `.email` (SES)         | Field screen 4 — PDF + email            | planned |
| 11 | `os.agents.*` + `os.session`             | V1.5 concierge chat, multi-turn state   | planned |
| 12 | `os.kpi.*` + `os.observe.*`              | director dashboard + SLO alerts         | planned |

**Tier 1 (iters 3–5) is the minimum for a credible Field V1 demo.**
Tier 2 (iters 6–8) ships when the Field backend is ready to plug in.
Tier 3 (iters 9–10) is the final polish before a RIOU pilot.

---

## Mapping to Field V1 pains

From `monce-fa/docs/product/01-master-pain.md`:

| Pain | MonceOS verb | Evidence |
|------|--------------|----------|
| P1 — reps don't fill the CRM         | `os.capture(transcript=...)` | typed `CR` from 2min of speech, 10s wall clock |
| P2 — reps discover accounts 5min before a visit | `os.brief(account_id)` (iter 7), `os.match.contact` (iter 3) | numbers-first brief; contacts resolved against factory table |
| P3 — promises never reach back office | `cr.actions[i].owner_team` + `os.route` (iter 8) | enum-clamped routing to `sales_ops` / `service` / `quoting` / `logistics` |
| P4 — directors fly blind              | `cr.to_json()` + `os.kpi.*` (iter 12) | schema-stable payload aggregates trivially |
| P5 — rep turnover costs 6 months      | `os.store` (iter 5) + `os.memory.past_visits` (iter 6) | tenant-scoped, permanent, searchable |
| P6 — CRM is a €100-250/seat tax       | the whole loop                | rep writes zero fields |

---

## Layout

```
monceai/monceos/
  __init__.py         # exports MonceOS
  core.py             # MonceOS class, _call, verb bindings
  types.py            # CR, Action, Contact, NextStep, Brief (typed, enum-clamped)
  capture.py          # iter 2 — transcript → CR via Json (charles-json)
  match.py            # iter 3 — wraps Matching with factory + contact diff
  verify.py           # iter 4 — wraps Calc, date parsing, ISO normalization
  store.py            # iter 5 — S3 / local / memory backends + audit log
  memory.py           # iter 6 — Concierge + CSV fallback
  brief.py            # iter 7 — pre-visit brief assembly
  route.py            # iter 8 — action → team, Snake-backed
  stt.py              # iter 9 — Deepgram primary, Whisper fallback
  export.py           # iter 10 — PDF (HTML template) + SES email
  agents.py           # iter 11 — Concierge / Moncey / Architect wrappers
  session.py          # iter 11 — multi-turn, state-persistent
  kpi.py              # iter 12 — dashboard primitives
  observe.py          # iter 12 — hooks, alerts, SLO tracking
```

`core.py` always imports the modules it needs at call time to keep the
import graph flat. No circular deps. Each iter module is independently
testable against live monceapp.

---

## Design invariants (don't violate)

1. **Don't touch `llm.py` / `matching.py` / `extraction.py` / `outlook.py`.**
   MonceOS composes them; it doesn't fork them. If a primitive is missing a
   feature (e.g. `framework_id` forwarding), MonceOS talks to `/v1/chat`
   directly via its own HTTP client rather than patching the primitive.
2. **Proprietary model by default.** Any new verb that calls an LLM picks
   from `{charles, charles-json, charles-science, charles-architect, moncey,
   concierge}`. Bare Bedrock only via explicit `model=` override.
3. **Typed in, typed out.** Verbs accept and return dataclasses from
   `types.py`. Raw dicts cross the boundary only for JSON serialization.
4. **Tenant scoping is one-way.** Once `MonceOS(tenant=...)` is constructed,
   no verb returns data from a different tenant. The constructor is the trust
   boundary.
5. **Fail loud, never hallucinate.** If Matching confidence is below the
   threshold, return `None` and flag it. If the LLM returns invalid JSON,
   return a `CR` with `schema_error="json_parse_failed"` — don't paper over.

---

## Non-goals

MonceOS is not a framework. It is a brick kit. It doesn't:

- define a router, a controller pattern, or a dependency injection scheme
- generate boilerplate brick scaffolding
- manage database migrations or ORMs
- wrap Bedrock's raw API (that's `LLM`)
- wrap Snake training (that's `Snake`)
- replace existing primitives — they remain the direct path when you need
  lower-level control

If MonceOS feels like too much abstraction for your brick, import the
primitives directly. MonceOS earns its place only when the composition
actually saves you work.

---

## Change policy

- **Adding a verb** → new module under `monceai/monceos/`, imported from
  `core.py`, added to this manifest, iter status in README updated.
- **Changing a verb signature** → bump `monceai` minor version (v1.2.x → v1.3.x).
- **Removing a verb** → not allowed before v2.0. Deprecate first, keep for
  two minor versions.
- **Modifying `types.py`** → if a field's type or enum changes, bump minor.
  Adding optional fields with defaults is compatible.

Bricks depend on this manifest. Treat it as a contract.
