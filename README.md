# monceai

[![PyPI](https://img.shields.io/badge/pip%20install-monceai-3776AB?logo=python&logoColor=white)](https://github.com/Monce-AI/monceai-sdk)
[![Snake v5.4.4](https://img.shields.io/badge/Snake-v5.4.4-black)](https://github.com/Monce-AI/algorithmeai-snake)
[![AWS Lambda](https://img.shields.io/badge/backend-AWS%20Lambda-FF9900?logo=awslambda&logoColor=white)](https://snakebatch.aws.monce.ai)
[![License](https://img.shields.io/badge/license-proprietary-red)](LICENSE)
[![Monce SAS](https://img.shields.io/badge/Monce-SAS-blue)](https://monce.ai)

**Cloud Snake classifier + SAT solver. Three lines to train, one to predict.**

Drop-in replacement for `algorithmeai.Snake` backed by distributed AWS Lambda. Train on 3,000 rows in **527ms**. Predict in **5ms** warm. Rank 25K items within a **1-second budget**. Zero dependencies beyond `requests`.

> Charles Dana &middot; Monce SAS &middot; April 2026 &middot; [Paper (PDF)](paper.pdf)

---

## Install

```bash
pip install git+ssh://git@github.com/Monce-AI/monceai-sdk.git
```

Set your API key:

```bash
export SNAKE_API_KEY="sk-snake-..."
```

## Quick Start

```python
from monceai import Snake

# Warm all Lambdas (once at startup)
Snake.warmup_all()

# Train
model = Snake(data, target_index="label", mode="fast")

# Predict
model.get_prediction({"age": 25, "sex": "female", "class": 1})
# -> "survived"

model.get_probability({"age": 25, "sex": "female", "class": 1})
# -> {"survived": 0.97, "died": 0.03}

# Training log
model.log
# -> 'Distributed training (v3): 25L, bucket=16, 25 workers, 200 samples, profile=balanced, 885ms'
```

## Training Modes

| Mode | Layers | Bucket | Wall Clock (200 rows) | Use Case |
|------|--------|--------|-----------------------|----------|
| `fast` | 25 | 16 | ~600ms | Quick iteration, demos |
| `balanced` | 50 | 32 | ~1.0s | Production default |
| `heavy` | 100 | 64 | ~1.7s | Maximum accuracy |

```python
model = Snake(data, target_index="label", mode="fast")       # 25 layers, bucket 16
model = Snake(data, target_index="label", mode="balanced")    # 50 layers, bucket 32
model = Snake(data, target_index="label", mode="heavy")       # 100 layers, bucket 64
model = Snake(data, target_index="label", n_layers=77)        # explicit override
```

## Constructor

```python
Snake(data, target_index="label")        # Train from list[dict], CSV, DataFrame
Snake(model_id="snake-abc-123")          # Connect to existing model
Snake("snake-abc-123")                   # Shorthand
Snake("model.json")                      # Upload local Snake model for cloud inference
```

## Methods

| Method | Returns | Notes |
|--------|---------|-------|
| `get_prediction(X)` | str | Top class |
| `get_probability(X)` | dict | `{class: float}`, sums to 1.0 |
| `get_audit(X)` | str | Human-readable SAT reasoning trace |
| `get_augmented(X)` | dict | Prediction + probability + audit + lookalikes |
| `get_lookalikes(X)` | list | Matching training samples |
| `get_lookalikes_labeled(X)` | list | With core/noise origin labels |
| `get_batch_rank(items, target_class, top, budget_ms)` | `RankResult` | Budgeted distributed top-K |
| `get_batch_prediction(items, mode, budget_ms)` | list | Parallel batch predictions |
| `to_json(path, stripped)` | str | Download model (compatible with `algorithmeai.Snake`) |
| `get_report(test_data, target_class)` | str | Audit report ZIP |
| `info()` | dict | Model metadata |
| `usage(limit)` | dict | API usage + costs |
| `warmup(workers)` | dict | Pre-warm scorer Lambdas |
| `warmup_all(scorers)` | dict | Warm all Lambdas (class method) |
| `estimate(n_samples, n_layers)` | dict | Cost estimate (static method) |

## Properties

| Property | Type | Description |
|----------|------|-------------|
| `model_id` | str | Unique model identifier |
| `wall_clock_ms` | int | Server-side training time |
| `breakdown` | dict | Per-stage timing (preprocess, upload, splitter, merge) |
| `log` | str | Server-side training summary |
| `training_info` | dict | Full training response (includes `dedup` stats) |

## Warmup

Cold Lambda starts add ~1s. Warm them once at startup:

```python
from monceai import Snake

# Warm everything: API + orchestrator + inference + 5 scorers
result = Snake.warmup_all(scorers=5)
# -> {'api': True, 'orchestrator': True, 'inference': True, 'scorers': 5, 'wall_clock_ms': 109}

# Then train + predict are fast
model = Snake(data, target_index="label", mode="fast")   # ~500ms
model.get_prediction(X)                                   # ~130ms
```

## Dedup Tracking

Preprocessing deduplicates rows by feature values. Stats are always available:

```python
model.training_info["dedup"]
# -> {'input_rows': 18, 'unique_rows': 15, 'dropped': 3, 'happened': True}

model.log
# -> '... dedup=3/18, 544ms'
```

## Batch Ranking

Score and rank large datasets within a strict time budget:

```python
result = model.get_batch_rank(
    items=test_data,          # list[dict], up to 100K+
    target_class="fraud",     # class to rank by
    top=100,                  # return top N
    budget_ms=1000,           # total wall-clock budget
)

result.top          # Top 100 items sorted by P(fraud) descending
result.n_scored     # How many items were scored within budget
result.n_total      # Total items
result.cache_key    # Reuse on subsequent calls (skip upload)
result.wall_clock_ms
```

## Download + Local Use

```python
# Download cloud model
model.to_json("model.json")                  # Full (with population)
model.to_json("model_light.json", stripped=True)  # Inference-only, 95% smaller

# Load locally with algorithmeai
from algorithmeai import Snake as LocalSnake
local = LocalSnake("model.json")
local.get_prediction(X)  # Works offline
```

## SAT Solver

```python
from monceai import SAT

result = SAT("p cnf 3 2\n1 2 0\n-1 3 0\n")
result.satisfiable   # True
result.assignment     # {1: True, 2: False, 3: True}
result.wall_clock_ms  # 12
```

Cloud-backed SAT solver using the npdollars architecture: LogicSpace dictionary + parallel Kissat workers on Lambda.

## Budget System

Every budgeted call subtracts 500ms overhead (network), sends the rest to the server:

```python
# budget_ms=1000 -> server gets 500ms -> scorers get 350ms
# Actual E2E: ~800ms (under budget)
```

| Budget | Avg E2E | Coverage | Compliant |
|--------|---------|----------|-----------|
| 1000ms | 817ms | 19% | 15/15 |
| 1500ms | ~1200ms | 80-94% | 3/3 |
| 2000ms | ~1470ms | 100% | 3/3 |

## Backend

This SDK talks to [`snake-monceai-api`](https://github.com/Monce-AI/snake-monceai-api) &mdash; distributed Snake training + inference on AWS Lambda.

## Dependencies

- `requests` &mdash; the only runtime dependency
- `algorithmeai-snake` &mdash; NOT required. Only needed for `to_json()` local use.

---

Charles Dana &middot; Monce SAS &middot; 2026
