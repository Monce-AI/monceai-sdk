# monceai

[![PyPI](https://img.shields.io/badge/pip%20install-monceai-3776AB?logo=python&logoColor=white)](https://github.com/Monce-AI/monceai-sdk)
[![Version](https://img.shields.io/badge/version-v1.2.5-5b2a8e)](https://github.com/Monce-AI/monceai-sdk/releases)
[![Synthax](https://img.shields.io/badge/Synthax-%2412%2Fquery%20flagship-c084fc)](#synthax--deep-reasoning-flagship-v124)
[![Computation](https://img.shields.io/badge/Computation-SAT%20verified-10b981)](#computation--verified-compute-v125)
[![ML](https://img.shields.io/badge/ML-Snake%20classifier-10b981)](#ml--context-driven-classifier-v125)
[![Playground](https://img.shields.io/badge/Playground-drag%20drop%20connect-8b5cf6)](https://monceapp.aws.monce.ai/playground)
[![Document](https://img.shields.io/badge/Document-drop%20%C2%B7%20ask%20%C2%B7%20extract-ef4444)](#document--drop-a-file-ask-a-question-v125)
[![Classifier](https://img.shields.io/badge/Classifier-two%20phase%20triage-f59e0b)](#classifier--fast-n-label-triage-v125)
[![MonceOS](https://img.shields.io/badge/MonceOS-v1.2.4-6d28d9)](#monceos--brick-kit-for-field-orders-quotes-v124)
[![Matching v2](https://img.shields.io/badge/Matching-v2%20rerank+arbitration-0ea5e9)](#matching--universal-client--article-resolver-v123)
[![Snake v5.4.5](https://img.shields.io/badge/Snake-v5.4.5-black)](https://github.com/Monce-AI/algorithmeai-snake)
[![AWS Lambda](https://img.shields.io/badge/backend-AWS%20Lambda-FF9900?logo=awslambda&logoColor=white)](https://snakebatch.aws.monce.ai)
[![AWS Bedrock](https://img.shields.io/badge/AWS-Bedrock-ff9900?logo=amazonaws&logoColor=white)](https://aws.amazon.com/bedrock/)
[![MonceApp](https://img.shields.io/badge/MonceApp-live-22c55e)](https://monceapp.aws.monce.ai)
[![Tests](https://img.shields.io/badge/tests-live-22c55e)](tests/)
[![License](https://img.shields.io/badge/license-proprietary-red)](LICENSE)
[![Monce SAS](https://img.shields.io/badge/Monce-SAS-blue)](https://monce.ai)

**LLM, VLM, Snake, SAT, Charles, Moncey, Architect, Json, Concierge, Matching, Calc, Diff, Synthax, Google, Computation, ML — plus Extraction + Outlook for memory-augmented document workflows, and MonceOS for brick-ready composition. One SDK, zero config for chat.**

```python
from monceai import Charles, Matching, Calc, Extraction, Outlook, Synthax

Charles("6x7")                                # → "42" (boolean arithmetic)
Calc("123x3456")                               # → "425088" (exact Decimal)
Matching("LGB Menuiserie", factory_id=4)       # → client #60689 (89% conf)
Matching("44.2 rTherm", factory_id=4)          # → article #63442 (100% conf)

# v1.2.4 — deep reasoning flagship, $12/query budget
s = Synthax("design auth for a glass factory portal")
str(s)         # TL;DR  (≤ 3 sentences, Haiku-compacted)
s.answer       # exhaustive Sonnet synthesis
s.job.stages   # recall → plan → draft → adversary → revise → arbiter → notify

# v1.2.0 — memory-augmented extraction
ex = Extraction("quote.pdf", user_id="7a3f9b2c", auto_memory=True)
ex.lines       # structured rows
ex.trust       # {"score": 98, "routing": "AUTO_APPROVE"}
ex.insights    # Haiku-distilled bullets written back to memory

ol = Outlook(user_id="7a3f9b2c", auto_memory=True)
ol.extract_email(attachments=[pdf_bytes], subject="Devis VIP", body="comme d'hab")
ol.recall("VIP cloisonneur patterns")
```

`Matching(text)` auto-routes client vs article in one parallel call.
No need to specify `field=` — the server races both paths and returns
the higher-confidence match. `Extraction` / `Outlook` ship the full
reflex loop: recall prior memories → extract → distill insights → remember.

> Charles Dana &middot; Monce SAS &middot; April 2026 &middot; [Paper](https://monceapp.aws.monce.ai/paper)

---

## Install

```bash
pip install git+https://github.com/Monce-AI/monceai-sdk.git
```

Zero dependencies beyond `requests`. No API key needed for LLM/VLM/Charles.

## What's Free, What Needs a Key

| Module | Auth | Backend | Cost |
|--------|------|---------|------|
| `LLM()` | **None** | monceapp.aws.monce.ai | Free |
| `VLM()` | **None** | monceapp.aws.monce.ai | Free |
| `Charles()` / `Moncey()` | **None** | monceapp.aws.monce.ai | Free |
| `Json()` / `Concierge()` | **None** | monceapp / concierge.aws.monce.ai | Free |
| `Matching()` / `Calc()` / `Diff()` | **None** | monceapp.aws.monce.ai | Free |
| `Extraction()` / `Outlook()` | **user_id only** | selfservice.aws.monce.ai | Free |
| `Snake()` | `SNAKE_API_KEY` | snakebatch.aws.monce.ai | Per-invocation |
| `SAT()` | `SAT_API_KEY` | npdollars.aws.monce.ai | Per-invocation |

---

## LLM — Text In, Answer Out

```python
from monceai import LLM

r = LLM("6x7")                                    # default: charles-science
r = LLM("factor 10403", model="charles-auma")      # boolean maximization
r = LLM("what is pi?", model="haiku")              # fast + cheap
r = LLM("morning bruv", model="charles")            # full charles pipeline

r.text           # "42"
r.json           # parsed dict (when charles-json)
r.ok             # True if successful
r.elapsed_ms     # wall clock
r.sat_memory     # compute receipt (formula, evals, services fired)
```

### Compute Models (charles family)

| Shorthand | Engine | Latency | Cost/msg |
|-----------|--------|---------|----------|
| `charles` | 4x parallel (mem+csv+cnf+sudoku) &rarr; Sonnet | 8-15s | ~$0.01 |
| `charles-auma` | Haiku encode &rarr; AUMA {0,1}^n &rarr; Haiku | 3-8s | ~$0.003 |
| `charles-science` | Snake router &rarr; 7 services &rarr; Sonnet | 15-60s | ~$0.01 |
| `charles-json` | Memory &rarr; Sonnet strict JSON, VLM | 5-15s | ~$0.01 |
| `charles-architect` | Memory &rarr; Sonnet ASCII diagrams | 5-15s | ~$0.01 |
| `concise` | charles &rarr; Haiku TL;DR | 10-20s | ~$0.01 |
| `cc` | charles &parallel; concise &rarr; synthesis | 12-25s | ~$0.02 |
| `moncey` | Glass sales agent (snake.aws + moncesuite) | 2-5s | ~$0.003 |
| `concierge` | Knowledge base + Snake tools | 3-10s | ~$0.005 |

### Overlay Models (v1.1.0 — monolith + matching)

General-purpose extraction + factory-driven matching, optionally
augmented with charles or concierge memory.

| Shorthand | What it does | Memory |
|-----------|--------------|--------|
| `monolith` | Bedrock Sonnet + factory context (extract/describe) | — |
| `matching` | Client ∥ article race, picks higher confidence | — |
| `charles-monolith` | monolith + charles.aws memory prefix | charles |
| `charles-matching` | matching + Haiku re-arbitration on memory | charles |
| `concierge-monolith` | monolith + concierge.aws search results | concierge |
| `concierge-matching` | matching + Haiku re-arbitration on memory | concierge |

**Real benchmark** (prompt: `"44.2 rTherm"`, factory 4):
- `matching`: 1.7s, snake_sat, **50% confidence**
- `charles-matching`: 10s, 1185c memory, **95% via memory_arbitration**
- `concierge-matching`: 4.3s, 1874c memory, **95% via memory_arbitration**

Memory arbitration fires automatically when the primary match confidence
is below 0.85 and a memory prefix exists. Haiku re-scores candidates
using the recalled context.

### Bedrock Passthrough (direct Converse)

| Shorthand | Model | Tools | Vision | Latency |
|-----------|-------|:---:|:---:|---------|
| `sonnet` | Sonnet 4.6 | ✅ | ✅ | 1-3s |
| `sonnet4` | Sonnet 4 | ✅ | ✅ | 2-4s |
| `haiku` | Haiku 4.5 | ✅ | ✅ | 1-2s |
| `nova-pro` | Nova Pro | — | ✅ | 0.8s |
| `nova-lite` | Nova Lite | — | — | 0.7s |
| `nova-micro` | Nova Micro | — | — | 0.6s |

## VLM — Image / File + Text In, JSON Out

```python
from monceai import VLM

# Images — multipart to the backend
r = VLM("what is in this image?", image=open("photo.png", "rb").read())

# Unified `file=` — path, Path, bytes, or file-like. Any doctype.
# Binary (.pdf/.png/.docx/...) → multipart.
# Text-like (.txt/.json/.csv/.md/.ndjson/...) → inlined into the prompt,
# so even text-only endpoints can "see" the file.
r = VLM("extract all glass fields", file="quote.pdf")
r = VLM("parse the order", file="order.json")
r = VLM("summarise", file=open("notes.md", "rb"))
r = VLM("what's wrong?", file=pdf_bytes, filename="q.pdf")

r.text   # raw response
r.json   # parsed dict
```

All five eyed classes take the same `file=` argument:
**`VLM`**, **`LLM`**, **`Json`**, **`Charles`**, and **`LLMSession.send`**.

## Charles — Smart Router

```python
from monceai import Charles

c = Charles()

# Auto-routes to the best sub-model
c("6x7")                          # → charles-auma (math)
c("is K4 3-colorable?")           # → charles-science (SAT)
c("list 5 primes", strategy="json")  # → charles-json

# Explicit sub-model calls
c.math("minimize x^2 - 4x + 4")
c.science("solve this sudoku: 530070000...")
c.json("list the planets")
c.vlm("describe", image=img_bytes)

# Parallel strategy — fire multiple models, take the best
c("explain gravity", strategy="deep")  # charles + charles-science in parallel
```

## Moncey — Glass Industry Sales Agent

```python
from monceai import Moncey

Moncey("44.2 Silence/16 alu gris/4 rFloat JPP")
# → "Bonjour, j'ai identifié: Feuilleté 44.2 + Intercalaire 16mm..."

# Client mode — parallel futures
m = Moncey()
a = m("44.2 feuillete LowE 16mm")
b = m("devis 20 vitrages")
print(a)  # blocks on read
```

Pipeline: snake.aws/comprendre (deterministic glass decomp) &rarr;
moncesuite.aws/comprendre (10 classifiers if quality < 75%) &rarr;
Haiku synthesis. Default factory_id=3 (Monce).

## Architect — ASCII Schemas on Demand

```python
from monceai import Architect

# Blocking — str subclass, IS the diagram
schema = Architect("auth service: users, sessions, api keys")
print(schema)                          # boxed ASCII ERD

# File in — diagram an existing spec
Architect("diagram this module", file="monceai/llm.py")

# Client mode — reusable, parallel futures
a = Architect()
s1 = a("postgres schema for glass factory orders")
s2 = a("sequence diagram: OAuth2 PKCE flow")
print(s1)                              # blocks on first read

schema.result.elapsed_ms               # LLMResult metadata
```

Backed by `charles-architect` on monceapp.aws.monce.ai — every response is
a diagram (ERD, class diagram, sequence, flowchart, system architecture).

## Json — Structured Output (dict subclass)

```python
from monceai import Json

Json("list 5 primes")              # → {"primes": [2, 3, 5, 7, 11]}
Json('{"broken: json}')            # → fixes it
Json("nom: Charles, age: 26")      # → {"nom": "Charles", "age": 26}

# File in — text-like files are inlined, binaries go multipart.
Json("extract the order", file="order.txt")
Json("list the items", file="quote.pdf")
Json("parse this", file=open("items.csv", "rb"))

j = Json("3 colors with hex")
j["colors"]                        # list access
print(j)                           # json.dumps(indent=2)
```

## Document — Drop a File, Ask a Question (v1.2.5)

[![Drop a file](https://img.shields.io/badge/input-PDF%20%C2%B7%20XLSX%20%C2%B7%20image%20%C2%B7%20text-ef4444)](#document--drop-a-file-ask-a-question-v125)
[![Routes through](https://img.shields.io/badge/routes-Charles%20%C2%B7%20Concierge%20%C2%B7%20Json-6d28d9)](#document--drop-a-file-ask-a-question-v125)
[![Playground](https://img.shields.io/badge/Playground-node%20ready-8b5cf6)](https://monceapp.aws.monce.ai/playground)

A file + a question, one line. `Document` wraps the charles family
(`Charles` / `Concierge` / `charles-json`) behind a single ergonomic surface.
Pass `prompt=` at construction and `str(doc)` is the answer.

```python
from monceai import Document

# One-shot — file + prompt → str via __str__
answer = str(Document("quote.pdf", prompt="what's the intercalaire?"))
# → "44.2 rTherm with 16mm TPS noir, per the VIP cloisonneur profile…"

# Multi-question — instantiate once, ask many times
doc = Document("spec.xlsx")
doc.ask("what's the total number of lines?")
doc.ask("any deadline mentioned?", model="concierge")   # memory-backed
doc.extract("list all glass lines as JSON")             # → dict via Json

# Concierge mode — binary files are pre-transcribed through charles-json,
# then the extracted text is handed to Concierge for a memory-backed answer.
str(Document("devis_VIP.pdf",
             prompt="is this the usual pattern for this client?",
             model="concierge"))
```

Accepts paths, `pathlib.Path`, raw bytes, or any file-like with `.read()`.
Text-like payloads (`.txt`, `.md`, `.csv`, `.json`…) are inlined into the
prompt; binaries (`.pdf`, `.xlsx`, `.png`, `.docx`…) go out as multipart.

**Playground integration.** Drag the red **Document** chip onto the canvas —
or just drop a file anywhere on the canvas and a Document node is spawned
at the drop point with the file pre-attached. Wire its output into any
downstream `Charles` / `Concierge` / `Arbiter` node.

| Mode | Backend | Best for |
|------|---------|----------|
| `model="charles"` (default) | charles-json via Charles auto-routing | Single questions, VLM included |
| `model="concierge"` | charles-json → Concierge | Memory-backed answers on documents |
| `model="charles-json"` | charles-json direct | Structured JSON / `.extract()` workflows |

Lives at [monceapp.aws.monce.ai/playground](https://monceapp.aws.monce.ai/playground).

## Concierge — Monce Knowledge Base

```python
from monceai import Concierge

Concierge("what's the accuracy for VIP today?")    # ask
Concierge("VIP uses warm edge TPS noir as default") # teach

# Memory management
Concierge.remember("44.2 rTherm is standard for Riou")
Concierge.search("rTherm")
Concierge.forget("old pricing info")
Concierge.digest()                                  # daily digest
Concierge.kpi(days=7, factory_id=4)                 # KPIs
```

Backend: concierge.aws.monce.ai. Sonnet + memory + Snake tools + email signals.

## LLMSession — Persistent Chat

```python
from monceai import LLMSession

s = LLMSession(model="charles")
r1 = s.send("my name is Charles")
r2 = s.send("what is my name?")   # remembers context
```

---

## Matching — Universal Client & Article Resolver (v1.2.3)

[![top-1 CPU](https://img.shields.io/badge/top--1%20(CPU%20only)-73.7%25-22c55e)](#benchmark--factory-4-vip-april-2026)
[![top-1 LLM](https://img.shields.io/badge/top--1%20(+LLM%20arb)-85.3%25-22c55e)](#benchmark--factory-4-vip-april-2026)
[![vs hosted](https://img.shields.io/badge/vs%20hosted%20cascade-%2B45pp-0ea5e9)](#benchmark--factory-4-vip-april-2026)
[![zero tokens](https://img.shields.io/badge/CPU%20path-0%20tokens-6d28d9)](#matching--universal-client--article-resolver-v123)
[![single](https://img.shields.io/badge/single-~80ms-6d28d9)](#live-timings-factory-4)
[![batch x3](https://img.shields.io/badge/batch%20x3-~70ms-6d28d9)](#live-timings-factory-4)
[![modes](https://img.shields.io/badge/modes-article%20%7C%20client%20%7C%20doc%20%7C%20auto%20%7C%20batch-94a3b8)](#matching--universal-client--article-resolver-v123)

Constructor-to-resolution: `Matching(arg, ...)` blocks and *is* the result.
Four input forms, one class, no fuzzy. `/batch` and `/batch_client` on
snake.aws are the source of truth; snake's own candidate list is re-ranked
locally (CPU only); an optional LLM arbitration band on `[0.6, 0.95)`
uses monceapp Haiku + concierge in parallel, agreement-gated.

```python
from monceai import Matching

# 1. single article
Matching("44.2 rTherm", factory_id=4, field="verre")
# → {"kind": "article", "num_article": "63442",
#    "denomination": "44.2 rTherm", "confidence": 1.0, "method": "snake_exact"}

# 2. array — one /batch call, results in input order
r = Matching(["44.2 rTherm", "4/16/4", "SGG Planitherm"],
             factory_id=4, field="verre")
r["stats"]              # {n, matched_rate, mean_confidence, by_tier}
r.items_list            # [{...}, {...}, {...}] in input order

# 3. client by free text (auto-parses nom / siret / email)
Matching("LGB Menuiserie SAS, SIRET 552 100 554 00025", factory_id=4)
# → {"kind": "client", "numero_client": "9232", "nom": "LGB MENUISERIE",
#    "confidence": 0.98, "method": "snake_exact"}

# 4. document → client (pdf / image / docx / eml / msg)
from pathlib import Path
Matching(Path("quote.pdf"), factory_id=4)
# → claude.aws/stage_0 → client_infos + matched client

# 5. auto mode (no field, no kind)
Matching("Riou Group", factory_id=4)           # → client
Matching("44.2 rTherm WE noir", factory_id=4)  # → article
# Ambiguous? Fires both in parallel, returns higher-confidence winner.

# 6. reusable client — deferred futures, parallel across cores
m = Matching(factory_id=4)
a = m("44.2 rTherm", field="verre")
b = m("LGB")
a["num_article"]        # blocks until ready
```

### LLM arbitration (optional, agreement-gated)

Enable for the ambiguous middle. Below 0.6 = garbage, not rescuable.
At/above 0.95 = seamless passthrough. In between, monceapp Haiku and
`concierge.aws/chat` vote independently — only agreement mutates the pick.

```python
Matching("Triplevitrage33/2+4+5Trempé", factory_id=4,
         use_llm=True, top_k=20)
# → local rerank picks a candidate; if conf ∈ [0.6, 0.95), both arbiters
#   vote; agreement promotes the pick to tier 2 with method="llm_arb_agree"
```

### Accuracy assessment

```python
pairs = [("44.2 rTherm", "63442"), ("SGG Planitherm", "98219"), ...]
report = Matching.assess(pairs, factory_id=4, field="global",
                         use_llm=True, top_k=20)

report["hit_top1"]            # 0.853 (85.3% top-1)
report["hit_topk"]            # top-k recall
report["above_floor_accuracy"] # accuracy on rows ≥ 0.6 confidence
report["by_method"]           # per-method breakdown
report["calibration"]         # [(lo, hi, n, hit_rate), ...]
report["failures"]            # first 200 wrong picks with method/conf
```

### Benchmark — factory 4 (VIP), April 2026

342 queries across 57 articles × 6 variant kinds (exact / lower /
extra-token / reorder / OCR / nospace), vs live `snake.aws/batch`:

| Config | top-1 | Tokens | Wall clock |
|---|---|---|---|
| Hosted cascade (snake→haiku→fuzzy) | 40% | — | — |
| Matching v2, CPU only (no fuzzy, no LLM) | **73.7%** | 0 | 4.3s |
| Matching v2, top_k=20 + LLM arbitration | **85.3%** | 4,400 | ~50s |

Variant breakdown @ 85%: exact 98%, lower 98%, reorder 95%, extra-token 90%,
OCR 83%, nospace 46%. Calibration: `[0.95, 1.0)` → 97%, `[0.8, 0.95)` → 91%.
Benchmark source: `bench_matching.py`.

Article fields for explicit `field=`: `verre`, `verre1`, `verre2`, `verre3`,
`intercalaire`, `intercalaire1`, `intercalaire2`, `remplissage`, `gaz`,
`faconnage`, `façonnage_arete`, `global`.

### Live timings — factory 4

From `from monceai import Matching`, measured against live `snake.aws`:

| Call | Wall clock | Tokens |
|------|-----------:|-------:|
| `Matching("44.2 rTherm", field="verre", factory_id=4)`       | **86 ms** | 0 |
| `Matching("ACTIF PVC", factory_id=4)` — client path          | **41 ms** | 0 |
| `Matching(["44.2 rTherm", "16 TPS noir", "Argon"], f=4)`     | **69 ms** (3 queries) | 0 |
| `Matching("SGG Planitherm", factory_id=4)` — auto client+article race | **78 ms** | 0 |
| Reusable `m = Matching(f=4); m(q1); m(q2)` — 2 parallel      | **46 ms** | 0 |

## Monolith Chat Models (v1.1.0)

Same `LLM()` / `LLMSession()` API — just point at the named model.
MonceApp wires factory context + memory retrieval automatically.

```python
from monceai import LLM

# General extraction via Sonnet + factory context
LLM("extract fields from this order", model="monolith", factory_id=4,
    image=pdf_page_bytes)

# Memory-augmented: charles.aws memory feeds the extraction
LLM("what is rTherm?", model="charles-monolith")

# Memory-augmented: concierge.aws search results feed the extraction
LLM("what is rTherm?", model="concierge-monolith")
# → answer uses remembered corrections + alias mappings
```

Chat-mode access (live on `/v1/chat`):
- `/monolith`, `/matching`
- `/charles-monolith`, `/charles-matching`
- `/concierge-monolith`, `/concierge-matching`

## Calc — Exact NP Arithmetic (v1.1.0)

```python
from monceai import Calc

Calc("123x3456")            # → "425088"
Calc("1000000x1000000")     # → "1000000000000"
float(Calc("44.2 * 1000"))  # → 44200.0
```

`Calc` is a `str` subclass &mdash; the instance IS the result. Decimal-backed,
exact. Operators: `x * / % + -`.

## Diff — Raw vs Enhanced (v1.1.0)

```python
from monceai import Diff

d = Diff("Quel intercalaire pour 44.2 rTherm?", factory_id=4)
d.raw_text                # generic model answer (often wrong)
d.enhanced_text           # monceai-enhanced answer (factory-correct)
d.context_tokens_added    # cost of enhancement
print(d.report())         # formatted side-by-side
```

Perfect for proving the value of `(monceai-)` context to stakeholders.

---

## Extraction — Memory-Augmented File Extraction (v1.2.0)

One-shot: file in, structured data + insights + memory out. Backed by
[`selfservice.aws.monce.ai`](https://selfservice.aws.monce.ai), which hosts
the full VLM engine and per-user memory store. No key — just pass a
`user_id` (8-char opaque token).

```python
from monceai import Extraction

ex = Extraction("quote.pdf", user_id="7a3f9b2c")

ex.lines              # list[dict] — extracted rows
ex.trust              # {"score": 98, "routing": "AUTO_APPROVE"}
ex.client             # {"name": "RIOU GLASS", "id": ..., "match": ...}
ex.header             # {"document_type": "devis", "language": "fr", ...}
ex.validation         # {"issues": [...], "overall_confidence": 0.92}
ex.task_id            # for feedback / audit
ex.duration_ms        # end-to-end latency
```

Accepts a path, raw bytes, or a list of paths/bytes for multi-file:

```python
Extraction(pdf_bytes, filename="order.pdf", user_id="7a3f9b2c")
Extraction(["a.pdf", "b.pdf"], user_id="7a3f9b2c")
```

### Reflex mode (auto_memory=True)

Fires a Haiku pass after extraction, distilling 1-3 short bullets worth
remembering (client patterns, routing quirks, recurring corrections) —
and writes them back as memory entries tagged `insight`. The next
extraction automatically sees them as `prior_memories`.

```python
ex = Extraction("quote.pdf", user_id="7a3f9b2c", auto_memory=True,
                email_subject="Devis VIP urgent",
                email_body="Peux-tu traiter comme d'hab?")

ex.insights            # ['VIP cloisonneur orders consistently specify warm edge 16mm', ...]
ex.prior_memories      # memories surfaced as context for *this* extraction
```

### Feedback

```python
ex.accept(note="looks right")
ex.reject(reason="wrong client")
ex.correct(line=0, was="44.2 rTherm", should_be="44.2 clair")
```

Feedback is stored as tagged memory and shows up in downstream recall.

### Benchmark (live, parallel, 3 real PDFs)

| PDF | Pages | Lines | Trust | Routing | Duration |
|---|---:|---:|---:|---|---:|
| Safran aerospace PO | 1 | 1 | 100 | AUTO_APPROVE | 14.0s |
| ASICA industrial PO | 1 | 6 | 98 | AUTO_APPROVE | 14.7s |
| Gasket International enquiry | 2 | 1 | 100 | AUTO_APPROVE | 12.1s |

Wall-clock for all three in parallel: **30.5s**. Auto-memory surfaced the
ASICA context on the third extraction mid-burst.

---

## Outlook — Email Workflow Client (v1.2.0)

Higher-level wrapper around `Extraction` for email / Outlook flows. Ships
`remember`, `recall`, `forget`, `history`, `chat`, and `extract_email`.

```python
from monceai import Outlook

ol = Outlook(user_id="7a3f9b2c", auto_memory=True)

# Extract attachments with full email context (subject + body)
ex = ol.extract_email(
    attachments=[pdf_bytes, ("invoice.xlsx", xlsx_bytes)],
    subject="Devis cloisonneur VIP",
    body="Peux-tu me traiter ça comme d'hab?",
)
ex.lines; ex.insights

# Memory ops
ol.remember("client always wants 44.2 rTherm as intercalaire", tags=["VIP"])
ol.recall("VIP cloisonneur patterns")          # keyword-scored
ol.forget("outdated note")                     # substring match

# History and activity
ol.history(limit=10)                           # past extractions
ol.memories(limit=50, tag="insight")           # memory listing
ol.stats()                                     # {memories, extractions, conversations}

# Chat — Sonnet grounded on this user's memory only
reply = ol.chat("What does this user usually route to VIP?")
reply["reply"]; reply["latency_ms"]
```

### The reflex loop

When `auto_memory=True`, every `extract_email()` call chains:

```
recall(subject)
  ↓
extract(file, context=body)
  ↓
distill(result, prior=recall_output)   ← Haiku
  ↓
remember(bullets)                       ← tagged 'insight'
```

Toggle at runtime: `ol.auto_memory = False`. Manual mode still auto-logs
the extraction event (just skips the Haiku distillation).

### Endpoints hit

`Outlook` is a thin client over [`selfservice.aws.monce.ai`](https://selfservice.aws.monce.ai)
— the full API is documented at [/docs](https://selfservice.aws.monce.ai/docs).
Memory is isolated per `user_id` and mirrored to S3 (versioned) for
permanency.

### Recipes

Patterns we actually ran against the live service while validating v1.2.0.
A runnable version lives at [`examples/extraction_quickstart.py`](examples/extraction_quickstart.py)
— `python examples/extraction_quickstart.py path/to/file.pdf`.

**1. Quality probe — one PDF, full reflex loop**

```python
from monceai import Extraction, Matching

ex = Extraction(
    "quote.pdf",
    user_id="7a3f9b2c",
    industry="glass",
    email_subject="Devis urgent",
    email_body="Peux-tu traiter comme d'hab?",
    auto_memory=True,
)

# The shape:
assert isinstance(ex, dict)              # pretty-prints JSON
assert ex.task_id and ex.duration_ms > 0
assert isinstance(ex.lines, list)
assert isinstance(ex.trust, dict)

# What was extracted:
print(f"vertical : {ex.result['vertical']}")
print(f"client   : {ex.client['name']}")
print(f"trust    : {ex.trust['score']} ({ex.trust['routing']})")
print(f"lines    : {len(ex.lines)}")

# What came back from the reflex loop:
for bullet in ex.insights:
    print(f"  insight  • {bullet}")
for mem in ex.prior_memories:
    print(f"  recalled • {mem[:80]}")

# Independently cross-check the client match (matching lives in monceapp):
cross = Matching(ex.client["name"], factory_id=4)
print(f"cross-check: {cross['nom']} #{cross['numero_client']} conf={cross['confidence']}")
```

**2. Bulk throughput — parallel extractions with ThreadPoolExecutor**

```python
import concurrent.futures as cf
from pathlib import Path
from monceai import Extraction

def run_one(path, idx):
    return Extraction(
        path,
        user_id=f"bulk_{idx:04x}",
        email_subject=f"Stress {idx}: {Path(path).name}",
        auto_memory=True,
        timeout=240,
    )

paths = ["a.pdf", "b.pdf", "c.pdf", "d.pdf"]  # your files
with cf.ThreadPoolExecutor(max_workers=4) as pool:
    futures = [pool.submit(run_one, p, i) for i, p in enumerate(paths)]
    for fut in cf.as_completed(futures):
        ex = fut.result()
        print(f"{ex.filename:<30} trust={ex.trust.get('score')} "
              f"routing={ex.trust.get('routing'):<14} {ex.duration_ms}ms")
```

Keep `max_workers` ≤ server worker count to avoid queueing. Selfservice
currently runs 20 gunicorn workers on t3.medium — client parallelism of 8
is a safe default.

**3. Multi-file synthesis — one extraction from N attachments**

```python
from monceai import Outlook

ol = Outlook(user_id="7a3f9b2c", auto_memory=True)

# Pass a list of paths OR raw bytes OR (filename, bytes) tuples.
# Selfservice runs the engine per file and merges the result server-side:
# first successful file → header/client, all lines concat'd with
# _source_file tagging, worst routing wins.
ex = ol.extract_email(
    attachments=[
        "order.pdf",
        ("quote.pdf", open("quote.pdf", "rb").read()),
    ],
    subject="Batch upload",
    body="Two files, one workflow.",
)

print(f"merged from {len({l.get('_source_file') for l in ex.lines})} files")
print(f"total lines: {len(ex.lines)}")
print(f"worst routing: {ex.trust['routing']}")
```

**4. Memory reflex — sequential calls compound context**

```python
from monceai import Outlook

ol = Outlook(user_id="ops_team_01", auto_memory=True)

for path in sorted_pdfs:           # e.g. a day's incoming email attachments
    ex = ol.extract_email(attachments=[path], subject=path.name)
    # `ex.prior_memories` grows with each call — the server auto-recalls
    # relevant history BEFORE each extraction and Haiku cross-references
    # it in the insights it writes back.
    if ex.prior_memories:
        print(f"  → surfaced {len(ex.prior_memories)} prior memories as context")

# At the end, Sonnet can summarize the entire run from user memory alone.
summary = ol.chat("What pattern emerged across today's orders?")
print(summary["reply"])
```

**5. Feedback — accept / reject / correct**

```python
ex = Extraction("quote.pdf", user_id="7a3f9b2c", auto_memory=True)

# All three return a memory entry tagged 'feedback' and persist to disk + S3.
ex.accept(note="looks right")
ex.reject(reason="wrong client — this is ASCA not ASICA")
ex.correct(line=2, field="verre1", was="44.2", should_be="44.2 LowE")

# Feedback is searchable like any other memory:
from monceai import Outlook
ol = Outlook(user_id="7a3f9b2c")
corrections = ol.memories(tag="correct", limit=50)
```

**6. Stats + history + recall**

```python
ol = Outlook(user_id="7a3f9b2c")

ol.stats()                         # {'memories': 50, 'extractions': 16, 'conversations': 3}
ol.history(limit=10)               # last 10 extractions with routing + trust
ol.memories(limit=20)              # full memory list (optionally tag-filtered)
ol.recall("VIP cloisonneur")       # keyword-scored search
ol.forget("outdated pricing")      # substring match, returns count deleted
```

**7. Factory-aware `/extract` pipeline — drop-in replacement for claude.aws**

[`examples/extract_pipeline.py`](examples/extract_pipeline.py) is a single-file
`Extract` class that assembles `Extraction` + `Outlook` + `Matching` + `Json` +
`Charles` into a payload that is byte-compatible with
`POST https://claude.aws.monce.ai/extract`.

```python
from extract_pipeline import Extract

ex = Extract("quote.pdf", factory_id=4, user_id="7a3f9b2c", industry="glass")

ex["extracted_data"]["value"]["measurements"]    # prod schema
ex["extracted_data"]["client_matching"]          # {"numero_client", "nom", "confidence"}
ex["metadata"]["routing_decision"]               # "auto_approved" | "human_review"
ex.measurements                                  # same as above, convenience accessor
```

What it actually does:

1. `Outlook.recall(q=f"factory_{factory_id}")` pulls user-specific priors.
2. `Extraction(source, user_id=..., industry="glass", context=...)` runs the
   selfservice VLM lift per document with priors threaded into `context`.
3. `upgrade_matches` fires one `Matching(..., field=..., factory_id=...)`
   future **per (row × field) in parallel**; low-confidence hits (<0.75)
   fall back to `Json` arbitration over the SDK's top-N candidates.
4. `upgrade_client` fires 4 parallel `Matching` futures (nom / logo /
   raison_sociale / siret), argmax wins.
5. `Json` cross-doc synthesis when `len(sources) > 1`.
6. `Charles` narrates the run for `_handle_metadata.agent_summary`.
7. `Outlook.remember` logs the run so the next call for this user recalls
   what happened.

All prompts live in one file as triple-quoted f-strings keyed off a
`FACTORY` table — one row per factory_id (1=VIT, 3=Monce, 4=VIP,
9=Eurovitrage, 10=TGVI, 13=VIC), driving prompts, matching fields, and
normalization toggles (spacer color, default gas, IGU decomposition).

```bash
python examples/extract_pipeline.py quote.pdf --factory 4 --user-id 7a3f9b2c
python examples/extract_pipeline.py a.pdf b.pdf order.eml --factory 3 \
    --user-id 7a3f9b2c --json
```

---

## Synthax — Deep Reasoning Flagship (v1.2.4)

[![budget](https://img.shields.io/badge/budget-%2412%2Fquery-c084fc)](#synthax--deep-reasoning-flagship-v124)
[![stages](https://img.shields.io/badge/stages-9%20specialized-6d28d9)](#synthax--deep-reasoning-flagship-v124)
[![tokens](https://img.shields.io/badge/tokens-unlimited-22c55e)](#synthax--deep-reasoning-flagship-v124)

Synthax is a multi-stage reasoning pipeline — each specialist's output
becomes the next's input. The planner (Haiku) picks the chain per
prompt; math skips the Architect, glass inserts Moncey, architecture
inserts the ASCII diagrammer. Adversary (cold Sonnet) attacks the draft;
revise patches the holes. Verify backstops numeric claims with exact
`Calc`. Arbiter (Sonnet) synthesizes TL;DR + confidence + residual
doubts. Notify writes the verdict back to Concierge so the next run
recalls it.

```python
from monceai import Synthax

# Input: a text prompt. Output: a Haiku-compacted TL;DR with an
# exhaustive Sonnet answer attached.
s = Synthax("design an auth layer for a glass factory portal",
            budget_usd=12.0)

# Output shape
str(s)                 # TL;DR (≤ 3 sentences, ≤ 280 chars)
s.answer               # exhaustive Sonnet synthesis
s.job.stages           # list[Stage] — full audit timeline
s.job.artifacts        # dict{stage_name → text}
s.job.cost_usd         # accumulated USD, hard-capped at budget
s.job.elapsed_ms       # wall-clock
s.job.confidence       # float 0..1 from arbiter
s.job.doubts           # list[str] — residual concerns
s.job.arbiter_rationale
print(s.report())      # human-readable stage-by-stage timeline
```

Reusable client (lazy futures, like Charles/Moncey):

```python
s_client = Synthax()
a = s_client("factor 10403 and prove uniqueness")
b = s_client("design a migration plan for PostgreSQL partitioning")
print(a, b)           # run in parallel, resolve on read
```

Pipeline shape (the planner may skip stages per bucket):

```
 recall → plan → draft → render → adversary → revise → verify → arbiter → notify
  ↑        ↑      ↑        ↑         ↑          ↑         ↑         ↑         ↑
 Concierge Haiku  spec.   Architect  Sonnet    Json     Calc       Sonnet   Concierge
 memory         (auma/    ASCII     cold       patch    exact      unified  writeback
 search         science   diagram   attack     holes    arithmetic answer
                /glass)
```

**Real receipt** — `Synthax("What is 6x7 and why is it the answer to life?", budget_usd=0.25)`:

| Stage | Source | Time | Cost |
|---|---|---:|---:|
| recall | concierge | 72ms | $0.005 |
| plan | haiku | 1,249ms | $0.003 |
| draft | charles | 15,268ms | $0.010 |
| render | — | — | skipped |
| adversary | sonnet | 8,798ms | $0.015 — caught fake dataset |
| revise | charles-json | 14,584ms | $0.010 — patched draft |
| verify | — | — | skipped (no numeric claims) |
| arbiter | sonnet | 9,007ms | $0.015 — TL;DR confidence=0.98 |
| notify | concierge | 0ms | $0.005 |

Total: **9 stages · 49s · $0.063 · confidence 0.98 · 2 residual doubts**.
Budget hard-cap $0.25 was not exhausted; adversary caught a draft
hallucination, revise cleaned it, arbiter delivered a 2-sentence TL;DR
within 280 chars.

`.replay(from_="revise", with_extra="...")` resumes the pipeline with
altered context, reusing earlier artifacts as priors.

---

## Google — Web Search (v1.2.4)

[![backend](https://img.shields.io/badge/backend-Claude%20web__search-facc15)](#google--web-search-v124)
[![cost](https://img.shields.io/badge/cost-Bedrock%20tokens-ff9900)](#google--web-search-v124)

Takes any text prompt, hits the live web, returns a Haiku-synthesized
paragraph with inline `[1][2]` citations. `str(Google(q))` IS the
synthesis, ready to feed downstream.

```python
from monceai import Google

g = Google("prix verre 44.2 rTherm 2026")

# Output
str(g)            # "Le verre 44.2 rTherm se situe autour de ... [1][2]"
g.results         # [{"title", "url", "snippet"}, ...]
g.raw_html        # backend HTML (for debugging)
g.search_ms       # search latency (before synthesis)
g.result          # LLMResult with tokens + sat_memory
```

Client mode with lazy parallel futures:

```python
g = Google()
a = g("Kissat SAT solver")
b = g("monceai SDK")
print(a, b)       # both resolve in parallel
```

Chain into Synthax for grounded deep reasoning (RAG in 3 lines):

```python
from monceai import Google, Synthax

ctx = Google("current market price for 44.2 rTherm glass France 2026")
s   = Synthax(f"Answer with sources and confidence: "
              f"what should I quote a client for 20 units? "
              f"Web context:\n{ctx}",
              budget_usd=2.0)
```

---

## Computation — Verified Compute (v1.2.5)

[![backend](https://img.shields.io/badge/backend-npdollars%20%2F%20Kissat-10b981)](https://npdollars.aws.monce.ai)
[![tokens](https://img.shields.io/badge/LLM%20tokens-0-22c55e)](#computation--verified-compute-v125)
[![proof](https://img.shields.io/badge/output-SAT%20proof-6d28d9)](#computation--verified-compute-v125)

Zero-LLM compute for prompts that have a deterministic answer. Detects
factoring / raw DIMACS / pure arithmetic, builds the matching CNF or
Decimal expression, dispatches to `npdollars.aws.monce.ai/solve` where
Kissat runs the SAT, and returns the verified answer with a proof
certificate.

```python
from monceai import Computation

Computation("factor 10403")
# → "10403 = 101 × 103"   (binary-multiplier CNF, Kissat, 0 tokens)

Computation("factor 2027")
# → "2027 is prime (UNSAT on binary-multiplier CNF)"

Computation("6x7")
# → "42"   (local Decimal, no network)

Computation("p cnf 3 2\n1 2 0\n-1 3 0\n")
# → "SAT assignment: [1, 2, 3]"   (raw DIMACS passthrough)

# Non-matching prompts → empty string + .recognized = False
c = Computation("explain gravity")
c.recognized   # False
```

**Attributes:**
- `str(c)` — the verified answer (or `""` if no pattern)
- `c.recognized` — True if a computable pattern was detected
- `c.pattern` — `"factor" | "dimacs" | "arith" | "coloring" | "none"`
- `c.proof` — DIMACS header, SAT assignment, Kissat ms, etc.
- `c.elapsed_ms`, `c.cost_usd`

**How it works under the hood.** The factoring encoder builds a full
binary-multiplier CNF via AND/XOR/full-adder gadgets (Dana-theorem
polynomial construction): each bit of P × Q is a fresh SAT variable,
column sums use ripple-carry adders, non-triviality is P ≥ 2 ∧ Q ≥ 2.
The CNF is sent to Kissat on npdollars which returns either SAT (with
an assignment we decode into P and Q) or UNSAT (N is prime).

**v0 limits.** The binary-multiplier CNF exceeds the npdollars nginx
413 body limit past ~16-bit N. Demo-sized numbers only; server-side
streaming upload is the extension path.

**Live receipts:**

| Input | Wall | Result |
|---|---:|---|
| `Computation("factor 15")` | 156 ms | `15 = 3 × 5` (Kissat: 1.5 ms, 245 vars) |
| `Computation("factor 2027")` | 417 ms | `2027 is prime (UNSAT)` |
| `Computation("6x7")` | 0 ms | `42` (Decimal, no network) |

Use as a parallel branch in Synthax: fire alongside the LLM draft,
dismiss when `.recognized=False`, promote to winner when it's True —
skipping adversary/revise/verify and saving tokens.

---

## ML — Context-Driven Classifier (v1.2.5)

[![backend](https://img.shields.io/badge/backend-snakebatch%20Lambda-10b981)](https://snakebatch.aws.monce.ai)
[![tokens](https://img.shields.io/badge/LLM%20tokens-0-22c55e)](#ml--context-driven-classifier-v125)

Snake classification on data you supply inline. `ML` detects a CSV
block in the prompt (header + ≥2 data rows) alongside a classify-shaped
verb, trains a Snake via `snakebatch.aws.monce.ai/csv/run`, and returns
`<class> (p=<confidence>)`.

```python
from monceai import ML

r = ML('''Classify: is (5.1, 3.5, 1.4, 0.2) a setosa?

sepal_length,sepal_width,petal_length,petal_width,species
5.1,3.5,1.4,0.2,setosa
4.9,3.0,1.4,0.2,setosa
7.0,3.2,4.7,1.4,versicolor
6.4,3.2,4.5,1.5,versicolor
''')

str(r)           # "setosa (p=0.97)"
r.prediction     # "setosa"
r.confidence     # 0.97
r.proof          # Snake audit trail: model_id, literal tests
```

No CSV → `r.recognized = False`. Used by Synthax as a parallel branch
for prompts that smell like "predict / classify / is X a Y given this
data", same early-exit semantics as `Computation`.

---

## Classifier — Fast N-Label Triage (v1.2.5)

[![two phase](https://img.shields.io/badge/pipeline-Haiku%20preview%20%E2%86%92%20Sonnet%20verdict-f59e0b)](#classifier--fast-n-label-triage-v125)
[![timeout](https://img.shields.io/badge/timeout-%E2%89%A430s%20guaranteed-22c55e)](#classifier--fast-n-label-triage-v125)
[![never hangs](https://img.shields.io/badge/never-hangs%20or%20raises-22c55e)](#classifier--fast-n-label-triage-v125)
[![backend](https://img.shields.io/badge/model-charles--json-5b2a8e)](#classifier--fast-n-label-triage-v125)

Fire-and-forget N-label classification over arbitrary context — text,
documents (paths / bytes / tuples), and free-form side arrays. The
constructor returns immediately and runs a background pipeline:

1. **Phase 1 (Haiku, ~7s)** — fast verdict on email text + filenames.
   Fires in parallel with VLM extraction so `.preview` lands as soon
   as Haiku responds, not after the documents finish extracting.
2. **Phase 2 (Sonnet via `charles-json`, ~18s)** — strict verdict on
   the full VLM-fused context with evidence and flippers.
3. **Guaranteed answer within `timeout` (default 30s)** — if Phase 2
   doesn't finish in time or produces unparseable JSON, the Phase 1
   preview is promoted to `.label` and marked `.tentative=True`.
   Never hangs, never raises.

```python
from monceai import Classifier

clf = Classifier(
    labels=["order", "quote", "informative"],
    rules="order=pipeline-ready PO/BL/invoice; "
          "quote=needs human estimator; "
          "informative=everything else",
    documents=["po_attached.pdf", ("drawing.png", png_bytes)],
    text="Merci de me chiffrer l'intercalaire pour du 44.2 rTherm",
    factory_id=4,
    timeout=30,     # hard cap, verdict guaranteed by then
)

clf.preview        # {'label': 'quote', 'confidence': 0.95, ...}  ~7s
clf.label          # 'quote'  (blocks up to 30s for the Sonnet verdict)
clf.confidence     # 0.95
clf.evidence       # ["'me chiffrer' explicit quote request", ...]
clf.flippers       # ["if PO number visible in drawing → flip to order"]
clf.runner_up      # 'informative'
clf.pipeline_ready # False  (needs human)
clf.tentative      # False  (True if Phase 2 fell back to preview)
clf.elapsed_ms     # 17234
```

### Progressive getters

| getter | blocks until | typical latency |
|---|---|---|
| `.preview` / `.fast` | Phase 1 done | 3-10s |
| `.ready_fast` / `.ready` | non-blocking poll | 0ms |
| `.label` / `.confidence` / `.evidence` / ... | Phase 2 done (or timeout→fallback) | ≤30s |
| `.wait(timeout=...)` | explicit block | user-controlled |

Show the preview to a human operator instantly, then upgrade the card
when the strict verdict lands:

```python
clf = Classifier(labels=[...], rules="...", documents=[...], text=...)
render_pending(clf.preview)       # instant UI
render_final(clf.to_dict())       # upgrade with evidence once ready
```

### Batch rollups

```python
verdicts = Classifier.batch(
    jobs=[{"documents": [p], "text": body} for p, body in pairs],
    labels=["order", "quote", "informative"],
    rules=RULES,
    factory_id=4,
    timeout=30,
    parallel=3,                   # concurrent classifications
)
```

### Benchmark — HEF 10-sample triage (Apr 2026)

Sequential, one classifier at a time, mixed Order / Extraction images
paired with realistic French email bodies:

| metric | value |
|---|---|
| accuracy | **10 / 10** (EXCELLENT) |
| avg confidence | 87.4% |
| avg Phase 1 latency | 7.0s |
| avg Phase 2 latency | 17.6s |
| wall time (sequential) | 175.9s (~18s / sample) |
| tentative verdicts | 4 / 10 (recovered by Phase 1 fallback) |

The four tentative verdicts are the mechanism paying out: Phase 2
returned unparseable text on those samples and the Phase 1 preview —
already correct — was promoted automatically. Without the fallback
they would have been `"informative" / 0%` defaults.

### Why `charles-json` on both phases

Raw Bedrock Sonnet ignores strict-JSON instructions under
rules-heavy prompts and produces mixed prose + JSON that fails
`json.loads`. `charles-json` enforces strict-JSON server-side.
Swapping `haiku`/`sonnet` → `charles-json` on the same 10-sample
benchmark took accuracy from **6/10 MEH → 10/10 EXCELLENT** and
cut wall time from 246s → 176s. Override via `fast_model=` /
`deep_model=` kwargs if you need a different routing.

### Constructor — simple, every field optional except `labels`

```python
Classifier(
    labels,                      # list[str] — the N mutually-exclusive classes
    rules="",                    # free-form natural-language rules
    documents=None,              # paths | bytes | (filename, bytes) tuples
    text=None,                   # email body, message, any free-form text
    factory_id=0,                # factory scope for Monce context
    timeout=30,                  # hard cap on .label blocking
    fast_timeout=12,             # cap on Phase 1
    extract_timeout=8,           # per-document VLM cap
    extras=None,                 # dict of arbitrary side arrays → [BLOCKS]
    parallel=4,                  # in-Classifier document extraction workers
    fast_model="charles-json",
    deep_model="charles-json",
)
```

---

## Playground — No-Code Canvas

[![live](https://img.shields.io/badge/live-monceapp.aws.monce.ai%2Fplayground-22c55e)](https://monceapp.aws.monce.ai/playground)
[![mobile](https://img.shields.io/badge/mobile-friendly-8b5cf6)](https://monceapp.aws.monce.ai/playground)

A drag-drop-connect canvas for every module in this SDK. Drop nodes,
wire ports, hit Play. The right pane emits the exact Python that
would produce the same result — copy, paste, run locally.

`https://monceapp.aws.monce.ai/playground`

**Features**
- 13 module nodes: `Context`, `Charles`, `Moncey`, `Json`, `Matching`,
  `Calc`, `Diff`, `Concierge`, `Architect`, `Google`, `Synthax`,
  `Computation`, `ML`, `Arbiter`
- **Fan-in**: a node can have multiple upstream parents, concatenated
  under `[Label]` headers for LLM nodes
- **Arbiter** node: Sonnet synthesizes N candidate answers into one,
  citing `[Agent N]` per claim
- **Colored ports** by payload type — text (blue) · document (red) ·
  number (green) · web (yellow) · proof (emerald) · synth (purple)
- **Live SSE streaming**: each node paints green the instant it
  completes — Calc's 87 ms answer appears 4 s before Concierge's
  4075 ms answer on a parallel fan-out
- **Server-side parallelism**: independent nodes at the same topological
  level run concurrently (ThreadPoolExecutor, max 8 workers)
- **Canvas pan**: drag empty space to move the viewport; ⊙ Reset view
  snaps back to origin
- **Templates**: 6 golden one-tap graphs (Monce Stack · Glass Quote ·
  Ramanujan 1729 · Raw vs Monce · RAG in 3 Nodes · Synthax Flex)
- **Save / Load** user graphs to localStorage; **Import .py** parses
  any snippet of `monceai` calls into a graph via the server's AST
  parser at `POST /playground/import`
- **Draft auto-save**: every canvas mutation persists to localStorage,
  no reload can lose your work
- **Live Python export** — the canvas and the exported snippet always
  match, byte-for-byte
- **Synthax pseudo** tab unfolds the 9-stage pipeline as linear Python
- **Mobile-friendly**: horizontal palette strip, bottom drawer for
  Python, tap-to-connect ports, pinch-zoom canvas, auto-compact boot
  scene under 900px
- **Shareable URL state**: every node position + edge serialized to
  `?g=...` so graphs are pasteable

The default boot scene is self-referential: *"Moncey, quelle est la
feature #1 sur monceapp aujourd'hui ?"* fans out to Moncey, Matching,
Concierge, Google, and Synthax in parallel, then an Arbiter weaves a
single unified response — every part of the Monce stack collaborating
on a meta-question.

---

## MonceOS — Brick Kit for Field, Orders, Quotes (v1.2.4)

[![manifest](https://img.shields.io/badge/manifest-MONCEOS__MANIFEST.md-5b2a8e)](MONCEOS_MANIFEST.md)
[![iter 1](https://img.shields.io/badge/iter%201-core%20+%20_call-22c55e)](monceai/monceos/core.py)
[![iter 2](https://img.shields.io/badge/iter%202-os.capture-22c55e)](monceai/monceos/capture.py)
[![iter 3](https://img.shields.io/badge/iter%203-os.match-94a3b8)](#roadmap)
[![iter 4](https://img.shields.io/badge/iter%204-os.verify-94a3b8)](#roadmap)
[![iter 5](https://img.shields.io/badge/iter%205-os.store-94a3b8)](#roadmap)
[![iter 6](https://img.shields.io/badge/iter%206-os.memory-94a3b8)](#roadmap)
[![iter 7](https://img.shields.io/badge/iter%207-os.brief-94a3b8)](#roadmap)
[![iter 8](https://img.shields.io/badge/iter%208-os.route-94a3b8)](#roadmap)
[![iter 9](https://img.shields.io/badge/iter%209-os.capture(audio)-94a3b8)](#roadmap)
[![iter 10](https://img.shields.io/badge/iter%2010-os.export-94a3b8)](#roadmap)
[![iter 11](https://img.shields.io/badge/iter%2011-os.agents-94a3b8)](#roadmap)
[![iter 12](https://img.shields.io/badge/iter%2012-os.kpi%20+%20observe-94a3b8)](#roadmap)

**Powered by proprietary Monce models:**
[![charles-json](https://img.shields.io/badge/charles--json-4--payload-6d28d9)](https://monceapp.aws.monce.ai/charles-json)
[![moncey](https://img.shields.io/badge/moncey-glass%20agent-6d28d9)](https://monceapp.aws.monce.ai/moncey)
[![concierge](https://img.shields.io/badge/concierge-account%20memory-6d28d9)](https://monceapp.aws.monce.ai/concierge)

The OS layer. One constructor binds `factory_id`, `tenant`, and `framework_id`
for the session. Every verb routes through the proprietary Monce models
(`charles-json`, `moncey`, `concierge`) — never bare Haiku/Sonnet.

```python
from monceai import MonceOS

os = MonceOS(factory_id=4, tenant="riou", framework_id="field_riou_test")

# Voice/transcript → typed, validated CR (charles-json, 4-payload Monce model)
cr = os.capture(transcript=stt_output, today="2026-04-22")
cr.summary                    # 2-3 sentences
cr.actions                    # [Action] — enum-clamped owner_team, deadline, amount_eur
cr.contacts_met               # [Contact] — is_new flagged
cr.sentiment                  # "positive" | "neutral" | "negative"
cr.next_step                  # NextStep(what, when)
cr.to_json()                  # schema-stable dashboard payload
```

### What MonceOS is for

A brick kit for Monce OS bricks (Field, Orders, Quotes, Concierge). The SDK
primitives (LLM, Json, Matching, Calc, Concierge, Moncey) stay untouched;
MonceOS composes them into verbs that bricks consume without re-wiring
factory scoping, framework binding, or model selection on every call.

### The four lines — Monce Field V1 AI stack

```python
from monceai import MonceOS

os = MonceOS(factory_id=4, tenant="riou", framework_id="field_riou_test")
cr = os.capture(transcript=stt_output)         # ~10s, typed, validated
for a in cr.actions: route_to_team(a)          # enum → inbox
save_to_s3(cr.to_json())                       # tenant-scoped, permanent
```

### Typed contract (`CR`, `Action`, `Contact`, `NextStep`)

- `owner_team` ∈ `{sales_ops, service, quoting, logistics}` — enum-clamped; model drift mapped to valid vocab
- `priority` ∈ `{high, medium, low}`
- `sentiment` ∈ `{positive, neutral, negative}`
- `amount_eur` is number-or-null, never string
- `deadline` / `next_step.when` in ISO 8601 (computed from `today=`)
- Guard: `{"error": "recording_too_short"}` for <30s usable speech

### Runnable demo

```bash
python examples/field_flow.py
```

Full loop against live factory 4 (VIP / RIOU Glass): capture → route → match
client `ACTIF PVC (#55298)` → verify arithmetic via `Calc` → agents
(`Moncey`, `Concierge`) for glass decode and account Q&A. ~27s end-to-end.

### Roadmap

| Iter | Verb | What it unlocks | Status |
|------|------|-----------------|--------|
| 1    | `MonceOS._call` + framework binding       | any brick can POST with tenant scope | ![](https://img.shields.io/badge/live-v1.2.4-22c55e) |
| 2    | `os.capture(transcript=...)` + `CR`       | Field's 5-extraction contract          | ![](https://img.shields.io/badge/live-v1.2.4-22c55e) |
| 3    | `os.match.client` + `is_new` diff         | contacts resolved against factory table | ![](https://img.shields.io/badge/next-planned-f59e0b) |
| 4    | `os.verify.amount` / `.date`              | NP-verified arithmetic + dates         | ![](https://img.shields.io/badge/planned--94a3b8) |
| 5    | `os.store` — S3 persistence + audit log   | permanency, GDPR delete                | ![](https://img.shields.io/badge/planned--94a3b8) |
| 6    | `os.memory` — Concierge + CSV fallback    | integrated + standalone mode           | ![](https://img.shields.io/badge/planned--94a3b8) |
| 7    | `os.brief(account_id)`                    | Field screen 2 — pre-visit brief       | ![](https://img.shields.io/badge/planned--94a3b8) |
| 8    | `os.route(actions)` — Snake classifier    | Field action plan routing              | ![](https://img.shields.io/badge/planned--94a3b8) |
| 9    | `os.capture(audio_bytes=...)` — STT       | full voice pipeline (Deepgram/Whisper) | ![](https://img.shields.io/badge/planned--94a3b8) |
| 10   | `os.export.pdf` / `.email`                | Field screen 4 — PDF + SES             | ![](https://img.shields.io/badge/planned--94a3b8) |
| 11   | `os.agents.*` + `os.session`              | V1.5 concierge chat, multi-turn state  | ![](https://img.shields.io/badge/planned--94a3b8) |
| 12   | `os.kpi.*` + `os.observe.*`               | director dashboard + SLO alerts        | ![](https://img.shields.io/badge/planned--94a3b8) |

---

## Snake — SAT Classifier (API key required)

```python
export SNAKE_API_KEY="sk-snake-..."
```

```python
from monceai import Snake

Snake.warmup_all()
model = Snake(data, target_index="label", mode="fast")
model.get_prediction(X)       # → "survived"
model.get_probability(X)      # → {"survived": 0.97, "died": 0.03}
model.get_audit(X)            # → SAT reasoning trace
model.to_json("model.json")   # → download for offline use
```

### Training Modes

| Mode | Layers | Bucket | Speed (200 rows) |
|------|--------|--------|-------------------|
| `fast` | 25 | 16 | ~600ms |
| `balanced` | 50 | 32 | ~1.0s |
| `heavy` | 100 | 64 | ~1.7s |

### Batch Ranking

```python
result = model.get_batch_rank(items=test_data, target_class="fraud", top=100, budget_ms=1000)
result.top          # Top 100 sorted by P(fraud)
result.n_scored     # Items scored within budget
```

## SAT — SAT Solver (API key required)

```python
export SAT_API_KEY="sk-sat-..."
```

```python
from monceai import SAT

result = SAT("p cnf 3 2\n1 2 0\n-1 3 0\n")
result.result        # "SAT"
result.assignment    # [1, -2, 3]
```

---

## Dependencies

- `requests` &mdash; the only runtime dependency
- No API key for LLM/VLM/Charles
- `SNAKE_API_KEY` for Snake, `SAT_API_KEY` for SAT

---

Charles Dana &middot; Monce SAS &middot; 2026
