# monceai

[![PyPI](https://img.shields.io/badge/pip%20install-monceai-3776AB?logo=python&logoColor=white)](https://github.com/Monce-AI/monceai-sdk)
[![Snake v5.4.5](https://img.shields.io/badge/Snake-v5.4.5-black)](https://github.com/Monce-AI/algorithmeai-snake)
[![AWS Lambda](https://img.shields.io/badge/backend-AWS%20Lambda-FF9900?logo=awslambda&logoColor=white)](https://snakebatch.aws.monce.ai)
[![License](https://img.shields.io/badge/license-proprietary-red)](LICENSE)
[![Monce SAS](https://img.shields.io/badge/Monce-SAS-blue)](https://monce.ai)

**LLM, VLM, Snake classifier, SAT solver. One SDK, zero config for chat.**

```python
from monceai import Charles

c = Charles()
c("6x7")                                  # → "42" (boolean arithmetic over {0,1}^n)
c("factor 10403")                          # → "101 × 103" (AUMA optimization)
c("is K4 3-colorable?")                    # → SAT solver, graph coloring
c.vlm("extract fields", image=img_bytes)   # → structured JSON from image
```

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
| `Charles()` | **None** | monceapp.aws.monce.ai | Free |
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

### 13 Models

| Shorthand | Engine | Latency | Cost/msg |
|-----------|--------|---------|----------|
| `charles-auma` | Haiku encode &rarr; AUMA {0,1}^n &rarr; Haiku (= or &asymp;) | 3-8s | ~$0.003 |
| `charles-science` | Snake router &rarr; 7 services &rarr; Sonnet | 15-60s | ~$0.01 |
| `charles` | 4x parallel (mem+csv+cnf+sudoku) &rarr; Sonnet | 8-15s | ~$0.01 |
| `charles-json` | Memory &rarr; Sonnet strict JSON, VLM | 5-15s | ~$0.01 |
| `charles-architect` | Memory &rarr; Sonnet ASCII diagrams | 5-15s | ~$0.01 |
| `concise` | charles &rarr; Haiku TL;DR | 10-20s | ~$0.01 |
| `cc` | charles &parallel; concise &rarr; synthesis | 12-25s | ~$0.02 |
| `sonnet` | Sonnet 4.6 + tools | 1-3s | ~$0.03 |
| `sonnet4` | Sonnet 4 + tools | 2-4s | ~$0.03 |
| `haiku` | Haiku 4.5 + tools | 1-2s | ~$0.003 |
| `nova-pro` | Nova Pro (context only) | 0.8s | ~$0.008 |
| `nova-lite` | Nova Lite (context only) | 0.7s | ~$0.001 |
| `nova-micro` | Nova Micro (context only) | 0.6s | ~$0.0005 |

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

## LLMSession — Persistent Chat

```python
from monceai import LLMSession

s = LLMSession(model="charles")
r1 = s.send("my name is Charles")
r2 = s.send("what is my name?")   # remembers context
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
