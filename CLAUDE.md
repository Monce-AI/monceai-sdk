# monceai SDK v1.1.0 — Guide for Claude

Repo: `Monce-AI/monceai-sdk` (public)
Backend: `monceapp.aws.monce.ai` (EC2 t3.small, 8 workers, 100 concurrent)

## Install

```bash
pip install git+https://github.com/Monce-AI/monceai-sdk.git
```

## Package Layout

```
monceai/
  __init__.py       # Exports: Charles, Moncey, Json, LLM, VLM, LLMSession, LLMResult,
                    #          Matching, Calc, Diff, Concierge, Snake, SAT
  llm.py            # Charles, Moncey, Json, LLM, VLM, LLMSession, Matching, Calc, Diff,
                    #   Concierge (FREE, no auth — all MonceApp-backed)
  snake.py          # Cloud Snake classifier (SNAKE_API_KEY required)
  sat.py            # SAT solver cloud + local (SAT_API_KEY required)
  report.py         # Audit report ZIP generator
pyproject.toml      # depends on: requests
```

## Free (No API Key)

### Charles — text in, text out, lazy parallel

```python
from monceai import Charles

Charles("6x7")                          # → "42" (38ms, 0 tokens, NP calc)
Charles("pi - (30+sqrt(2))/10")         # → "0.0001712976" (68ms, 0 tokens, regex decomposition)
Charles("factor 10403")                 # → "101 × 103" (AUMA + npdollars)
Charles("roots of z^2 + 1 = 0")        # → "z = ±i" (AUMA complex)
Charles("morning bruv")                 # → general chat (charles model)
```

Charles is a lazy future. Constructor fires a background thread, returns immediately.
Resolves when you read: `print()`, `str()`, `f""`, `+`, `len()`, `[]`.

```python
# Fire 100 in parallel — 0ms to launch, wall clock = slowest
calls = [Charles(f"{i}x{i+1}") for i in range(100)]
for c in calls: print(c)  # all already computed
```

Metadata: `c.result.model`, `c.result.elapsed_ms`, `c.result.sat_memory`.

#### Charles execution paths (fastest wins)

1. **NP calc** — pure arithmetic (`6x7`, `100/3`), math expressions (`pi+e`, `sin(pi/4)`). Regex → AST eval. 0 tokens, <100ms.
2. **Binary circuit** — multiplication/division detected by regex. CNF carry-chain → npdollars/Kissat. 0 tokens, <200ms. Works up to 64-bit.
3. **AUMA** — optimization, roots, factoring. Fourier probing over {0,1}^n or Real/Complex. 0 tokens for compute, 1-2 Haiku calls for encoding.
4. **Full pipeline** — Haiku encodes → AUMA + npdollars + snakebatch race → Haiku synthesizes. 2 Haiku calls.

Strategies: `Charles("...", strategy="math")`, `"science"`, `"json"`.

### Moncey — glass industry sales agent

```python
from monceai import Moncey

Moncey("44.2 Silence/16 alu gris/4 rFloat JPP")
# → "Bonjour, j'ai identifié: Feuilleté 44.2 + Intercalaire 16mm..."
```

Moncey is a lazy future like Charles. Fires on construction, resolves on read.

Pipeline:
1. `snake.aws.monce.ai/comprendre` — deterministic glass decomposition (verre, intercalaire, gas). 224ms.
2. If quality ≥ 75% → skip moncesuite classifiers (like NP calc skips LLM for math).
3. If quality < 75% → `moncesuite.aws.monce.ai/comprendre` — 10 classifiers (email, quote, business, sales, negotiation...).
4. Haiku synthesizes a French sales response with the classifier context.

Default factory_id: 3 (Monce). Override: `Moncey("...", factory_id=4)`.

### Json — structured output, dict subclass

```python
from monceai import Json

Json("list 5 primes")              # → {"primes": [2, 3, 5, 7, 11]}
Json('{"broken: json}')            # → fixes it
Json("nom: Charles, age: 26")      # → {"nom": "Charles", "age": 26}

# v1.2.1 — file=path/Path/bytes/file-like, any doctype
Json("extract the order", file="order.txt")     # text inlined
Json("list items", file="quote.pdf")            # binary multipart
Json("parse", file=open("items.csv", "rb"))     # file-like
```

Json is a `dict` subclass + lazy future. Resolves on any dict access.

```python
j = Json("3 colors with hex")
j["colors"]         # blocks until resolved, returns list
list(j.keys())      # blocks, returns keys
print(j)            # json.dumps(indent=2)
str(j)              # json.dumps(indent=2)
```

Backend: charles-json (Sonnet strict JSON output). v1.2.1 unified `file=`
argument across Json/LLM/VLM/Charles/LLMSession: text-like files
(.txt/.json/.csv/.md/.ndjson/…) are inlined into the prompt so the
chat endpoint — which only accepts binary multipart — still sees them;
binaries (.pdf/.png/.docx/…) go multipart.

### Chaining — constructors compose via `+`

```python
from monceai import Moncey, Json

# Moncey resolves first (str), + concatenates, Json wraps the result
Json("Extract order info: " + Moncey("44.2 feuillete LowE 16mm"))
# → {"order": {"articles": [...], "missing_information": [...]}}
```

This works because:
- `Moncey("...")` is a lazy future
- `"string" + Moncey("...")` calls `__radd__`, which calls `__str__`, which resolves
- `Json("..." + resolved_string)` fires with the full text

### LLM — direct model access

```python
from monceai import LLM

LLM("hello", model="haiku")              # fast, cheap
LLM("hello", model="sonnet")             # premium
LLM("hello", model="charles-science")    # Snake router → 7 services
```

Returns `LLMResult` with `.text`, `.json`, `.ok`, `.model`, `.elapsed_ms`, `.sat_memory`.

### VLM — image + text

```python
from monceai import VLM

VLM("describe", image=open("photo.png", "rb").read())
```

### Matching — factory-driven field matching (v1.1.0)

Reliability overlay: takes extracted terms, returns canonical IDs.
Two modes — client (via `claude.aws/stage_0`) or article (via `snake.aws/query`),
both funneled through MonceApp's `/v1/matching` endpoint.

```python
from monceai import Matching

# Client matching — free text, identifies the ordering company
Matching("LGB Menuiserie SAS", factory_id=4)
# → {"numero_client": "9232", "nom": "LGB MENUISERIE", "confidence": 0.98, "method": "snake_exact", ...}

# Article matching — verre / intercalaire / remplissage / faconnage
Matching("44.2 rTherm", field="verre", factory_id=4)
# → {"num_article": "63442", "denomination": "44.2 rTherm", "confidence": 1.0}

# Dict overlay — preserves extra fields, enriches client block in-place
Matching({"nom": "LGB", "qty": 50, "adresse": "Lyon"}, factory_id=4)
# → {"nom": "LGB", "qty": 50, "adresse": "Lyon", "numero_client": "9232", "match_confidence": 1.0}

# Batch — returns list[Matching]
Matching(["LGB", "ACTIF PVC", "VME"], factory_id=4)

# Client mode — reusable, fires parallel futures (like Charles/Moncey)
m = Matching(factory_id=4)
a = m("LGB")                                  # future
b = m("44.2 rTherm", field="verre")           # future
print(a.get("numero_client"))                 # blocks on read
```

Matching is a `dict` subclass. `.result` carries `LLMResult` metadata
(elapsed_ms, sat_memory with method/source/candidates).

Article fields: `verre`, `verre1`, `verre2`, `verre3`, `intercalaire`,
`intercalaire1`, `intercalaire2`, `remplissage`, `gaz`, `faconnage`,
`façonnage_arete`, `global`.

### Calc — exact NP arithmetic (v1.1.0)

```python
from monceai import Calc

Calc("123x3456")          # → "425088"
Calc("100/3")             # → "33.333333"
Calc("1000000x1000000")   # → "1000000000000"
float(Calc("44.2 * 1000"))  # → 44200.0
```

`Calc` is a `str` subclass. Operators: `x * / % + -`. Decimal-backed,
multiplication is poly-time to verify, NP-hard to invert (factoring).

### Diff — raw vs monceai-enhanced, side by side (v1.1.0)

```python
from monceai import Diff

d = Diff("Quel intercalaire pour 44.2 rTherm?", factory_id=4)
d.raw_text              # what the bare model says (often wrong)
d.enhanced_text         # what monceai-enhanced says (factory-correct)
d.context_tokens_added  # int — cost of enhancement
print(d.report())       # formatted side-by-side
```

Use this to show stakeholders the value of the `(monceai-)` context layer.
`Diff` is a `dict` subclass — the full JSON response is accessible as a dict.

### LLMSession — persistent chat

```python
from monceai import LLMSession

s = LLMSession(model="charles")
s.send("my name is Charles")
s.send("what is my name?")  # remembers
```

### 14 Model Shorthands

| Shorthand | Model | Free |
|-----------|-------|------|
| `charles` | charles | Yes |
| `charles-science` | charles-science | Yes |
| `charles-auma` | charles-auma | Yes |
| `charles-json` | charles-json | Yes |
| `charles-architect` | charles-architect | Yes |
| `concise` | concise | Yes |
| `cc` | cc | Yes |
| `moncey` | moncey | Yes |
| `sonnet` | Sonnet 4.6 | Yes |
| `sonnet4` | Sonnet 4 | Yes |
| `haiku` | Haiku 4.5 | Yes |
| `nova-pro` | Nova Pro | Yes |
| `nova-lite` | Nova Lite | Yes |
| `nova-micro` | Nova Micro | Yes |

## API Key Required

### Snake (SNAKE_API_KEY)

```python
from monceai import Snake

model = Snake(data, target_index="label", mode="fast")
model.get_prediction(X)       # → "survived"
model.get_probability(X)      # → {"survived": 0.97, "died": 0.03}
```

Backend: `snakebatch.aws.monce.ai`. Modes: fast/balanced/heavy.

### SAT (SAT_API_KEY)

```python
from monceai import SAT

result = SAT("p cnf 3 2\n1 2 0\n-1 3 0\n")
result.result        # "SAT"
result.assignment    # [1, -2, 3]
```

Backend: `npdollars.aws.monce.ai`.

## Backend Architecture

All free calls go to `https://monceapp.aws.monce.ai/v1/chat` as multipart POST.

charles-auma has 4 compute engines racing in parallel:
- **NP calc** — AST-safe eval, regex math decomposition (0 tokens)
- **Binary circuits** — multiplication/division as CNF → Kissat (0 tokens)
- **AUMA** — Fourier optimization over {0,1}^n (auma.aws.monce.ai)
- **SnakeBatch** — train classifier from Haiku CSV (snakebatch.aws.monce.ai)

First engine to return exact result wins — rest are cancelled.

Moncey calls:
- `snake.aws.monce.ai/comprendre` — glass decomposition
- `moncesuite.aws.monce.ai/comprendre` — 10 classifiers (only if snake quality < 75%)

## Usage Tracking

Every Charles/Moncey/Json call POSTs to `/usage` on monceapp — full prompt, answer, sat_memory.
Dashboard: `https://monceapp.aws.monce.ai/dashboard` (auto-refresh, all workers, persists to disk).

## Live Pages

| URL | What |
|-----|------|
| monceapp.aws.monce.ai/developers | Interactive playground — Charles + Moncey + Json |
| monceapp.aws.monce.ai/professionals | Glass industry — Moncey + Json one-liners |
| monceapp.aws.monce.ai/demo | 35-line script, syntax highlighted, Run on EC2 |
| monceapp.aws.monce.ai/dashboard | Live usage stats, auto-refresh |
| monceapp.aws.monce.ai/paper | Technical paper |
| monceapp.aws.monce.ai/architecture | System diagrams |
| monceapp.aws.monce.ai/economics | Cost model |

## CI/CD

Push to `main` on `Monce-AI/monceai-llm-vlm-wrapper` → GitHub Actions → rsync to EC2 → restart → health check. 28 seconds.

## Dependencies

- `requests` — the only runtime dependency

## CRITICAL: Never set bucket=len(data) in Snake

```python
# WRONG — O(n^2)
model = Snake(data, n_layers=1, bucket=max(len(data), 1))

# CORRECT
model = Snake(data, n_layers=1, bucket=250)
```
