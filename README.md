# monceai

[![PyPI](https://img.shields.io/badge/pip%20install-monceai-3776AB?logo=python&logoColor=white)](https://github.com/Monce-AI/monceai-sdk)
[![Version](https://img.shields.io/badge/version-v1.2.0-5b2a8e)](https://github.com/Monce-AI/monceai-sdk/releases)
[![Snake v5.4.5](https://img.shields.io/badge/Snake-v5.4.5-black)](https://github.com/Monce-AI/algorithmeai-snake)
[![AWS Lambda](https://img.shields.io/badge/backend-AWS%20Lambda-FF9900?logo=awslambda&logoColor=white)](https://snakebatch.aws.monce.ai)
[![AWS Bedrock](https://img.shields.io/badge/AWS-Bedrock-ff9900?logo=amazonaws&logoColor=white)](https://aws.amazon.com/bedrock/)
[![MonceApp](https://img.shields.io/badge/MonceApp-live-22c55e)](https://monceapp.aws.monce.ai)
[![Tests](https://img.shields.io/badge/tests-live-22c55e)](tests/)
[![License](https://img.shields.io/badge/license-proprietary-red)](LICENSE)
[![Monce SAS](https://img.shields.io/badge/Monce-SAS-blue)](https://monce.ai)

**LLM, VLM, Snake, SAT, Charles, Moncey, Architect, Json, Concierge, Matching, Calc, Diff — plus Extraction + Outlook for memory-augmented document workflows. One SDK, zero config for chat.**

```python
from monceai import Charles, Matching, Calc, Extraction, Outlook

Charles("6x7")                                # → "42" (boolean arithmetic)
Calc("123x3456")                               # → "425088" (exact Decimal)
Matching("LGB Menuiserie", factory_id=4)       # → client #60689 (89% conf)
Matching("44.2 rTherm", factory_id=4)          # → article #63442 (100% conf)

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
