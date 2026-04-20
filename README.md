# monceai

[![PyPI](https://img.shields.io/badge/pip%20install-monceai-3776AB?logo=python&logoColor=white)](https://github.com/Monce-AI/monceai-sdk)
[![Version](https://img.shields.io/badge/version-v1.1.0-5b2a8e)](https://github.com/Monce-AI/monceai-sdk/releases)
[![Snake v5.4.5](https://img.shields.io/badge/Snake-v5.4.5-black)](https://github.com/Monce-AI/algorithmeai-snake)
[![AWS Lambda](https://img.shields.io/badge/backend-AWS%20Lambda-FF9900?logo=awslambda&logoColor=white)](https://snakebatch.aws.monce.ai)
[![AWS Bedrock](https://img.shields.io/badge/AWS-Bedrock-ff9900?logo=amazonaws&logoColor=white)](https://aws.amazon.com/bedrock/)
[![MonceApp](https://img.shields.io/badge/MonceApp-live-22c55e)](https://monceapp.aws.monce.ai)
[![Tests](https://img.shields.io/badge/tests-live-22c55e)](tests/)
[![License](https://img.shields.io/badge/license-proprietary-red)](LICENSE)
[![Monce SAS](https://img.shields.io/badge/Monce-SAS-blue)](https://monce.ai)

**LLM, VLM, Snake, SAT, Charles, Moncey, Json, Concierge — plus Matching, Calc, Diff, Monolith + memory-augmented overlays. One SDK, zero config for chat.**

```python
from monceai import Charles, Matching, Calc

Charles("6x7")                            # → "42" (boolean arithmetic)
Calc("123x3456")                           # → "425088" (exact Decimal)
Matching("LGB Menuiserie", factory_id=4)   # → client #60689 (89% conf)
Matching("44.2 rTherm", factory_id=4)      # → article #63442 (100% conf)
```

`Matching(text)` auto-routes client vs article in one parallel call.
No need to specify `field=` — the server races both paths and returns
the higher-confidence match.

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

## VLM — Image + Text In, JSON Out

```python
from monceai import VLM

r = VLM("what is in this image?", image=open("photo.png", "rb").read())
r = VLM("extract all glass fields", image=pdf_bytes)

r.text   # raw response
r.json   # parsed dict
```

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

## Json — Structured Output (dict subclass)

```python
from monceai import Json

Json("list 5 primes")              # → {"primes": [2, 3, 5, 7, 11]}
Json('{"broken: json}')            # → fixes it
Json("nom: Charles, age: 26")      # → {"nom": "Charles", "age": 26}

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

## Matching — Factory-Driven Field Reliability (v1.1.0)

Overlay for extracted terms. **One call, auto-detects client vs article.**
Wraps `claude.aws/stage_0` (client cascade) and `snake.aws/query`
(article matching) — both raced in parallel, higher-confidence wins.

```python
from monceai import Matching

# Auto-routing — no field= needed
Matching("LGB Menuiserie SAS", factory_id=4)
# → {"kind": "client", "numero_client": "9232", "nom": "LGB MENUISERIE",
#    "confidence": 0.98, "method": "snake_exact", ...}

Matching("44.2 rTherm", factory_id=4)
# → {"kind": "article", "num_article": "63442",
#    "denomination": "44.2 rTherm", "confidence": 1.0, ...}

# Explicit field= override (per-field article matching)
Matching("44.2", field="verre", factory_id=4)
# → {"num_article": "63442", "denomination": "44.2", "confidence": 1.0}

# JSON overlay — preserves extra fields, enriches client block
Matching({"nom": "LGB", "qty": 50, "adresse": "Lyon"}, factory_id=4)
# → {"nom": "LGB", "qty": 50, "adresse": "Lyon",
#    "numero_client": "9232", "match_confidence": 1.0}

# Batch
Matching(["LGB", "ACTIF PVC", "VME"], factory_id=4)

# Reusable client — parallel futures (Charles/Moncey style)
m = Matching(factory_id=4)
a = m("LGB"); b = m("44.2 rTherm")
print(a.get("numero_client"))  # blocks on read
```

### Production benchmark (50 real clients + 50 real articles)

Pulled from `VIP_Clients_Unique.xlsx` / `VIP_Articles_Unique.xlsx`:

| | Routing | Matches |
|---|---|---|
| Clients | 50/50 (100%) | 50/50 (100%) |
| Articles | 20/50 (40%) | 20/50 (40%) |

Article misses are catalog coverage (snake hasn't seen the item), not
routing bugs. Zero client→article misroutes. One article→client misroute
(`"PRBLOC"` matched a client with that name).

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
