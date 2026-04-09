# monceai — Guide for Claude

Monce AI Python SDK. Cloud-backed Snake classifier with distributed Lambda training and budgeted inference.

Author: Charles Dana / Monce SAS.
Repo: `/Users/charlesdana/Documents/monceai`
AWS infra: `/Users/charlesdana/Documents/snakebatch.aws.monce.ai`
API endpoint: `https://snakebatch.aws.monce.ai`
Dashboard: `https://snake.aws.monce.ai/parallelism`

## Package Layout

```
monceai/
  __init__.py       # Exports: Snake, SAT, generate_report
  snake.py          # Cloud Snake — drop-in for algorithmeai.Snake
  sat.py            # SAT solver (cloud + local)
  report.py         # Audit report ZIP generator
pyproject.toml      # depends on: requests
```

## Quick Start

```python
from monceai import Snake

# Train (distributed Lambda, ~250ms server warm)
model = Snake(data, target_index="label", n_layers=5, bucket=250)

# Predict (5ms warm)
model.get_prediction(X)
model.get_probability(X)
model.get_audit(X)

# Rank 25K items within 1s budget
result = model.get_batch_rank(test_data, target_class="A", top=10, budget_ms=1000)

# Download Snake-compatible model
model.to_json("model.json")                 # full (with population)
model.to_json("light.json", stripped=True)   # inference-only, 95% smaller

# Load locally
from algorithmeai import Snake as Local
Local("model.json").get_prediction(X)        # works
Local("light.json").get_prediction(X)        # works (no audit)
```

## Auth

API key from `SNAKE_API_KEY` env var (set in `.zshrc`). Bearer token auth on all endpoints except `/estimate`.

## Constructor Modes

```python
Snake(data, target_index="label")     # Train from list[dict]
Snake(model_id="snake-abc-123")       # Connect to existing model
Snake("snake-abc-123")                # Shorthand
Snake("model.json")                   # Upload local model for cloud inference
```

## Methods

| Method | Returns | Notes |
|--------|---------|-------|
| `get_prediction(X)` | str | Top class |
| `get_probability(X)` | dict | `{class: float}`, sums to 1.0 |
| `get_audit(X)` | str | Human-readable SAT trace (needs full model) |
| `get_augmented(X)` | dict | Prediction + probability + audit + lookalikes |
| `get_lookalikes(X)` | list | Matching training samples |
| `get_lookalikes_labeled(X)` | list | With core/noise origin labels |
| `get_batch_rank(items, target_class, top, budget_ms)` | RankResult | Budgeted top-K ranking |
| `get_batch_prediction(items, mode, budget_ms)` | list | Parallel predictions |
| `to_json(path, stripped=False)` | str | Download model (Snake-compatible) |
| `get_report(test_data, target_class, top)` | str | Audit report ZIP |
| `info()` | dict | Model metadata |
| `usage(limit)` | dict | API usage + costs from DynamoDB |
| `warmup(workers)` | dict | Pre-warm scorer Lambda containers |
| `estimate(n_samples, n_layers, bucket)` | dict | Cost estimate (static method) |

## Budget System

Every budgeted operation subtracts a fixed 500ms overhead (network + API handler), then passes the remaining time to scorers at 0.7x.

```python
# User asks for 1000ms
# Client sends: server_budget = max(100, 1000 - 500) = 500ms
# Server scorer budget: 500 * 0.7 = 350ms
# Server collection deadline: 500ms (full)
# Scorers stop at 350ms, return partial results
# API collects until 500ms, returns
# Network adds ~300ms
# E2E: ~800ms (under 1000ms budget)
```

Tested at scale (25K items, 10 mixed features, 15 workers):

| Budget | Avg E2E | Coverage | Compliant |
|--------|---------|----------|-----------|
| 1000ms | 817ms | 19% | 15/15 |
| 1500ms | ~1200ms | 80-94% | 3/3 |
| 2000ms | ~1470ms | 100% | 3/3 |

## CRITICAL: Preprocessing — NEVER set bucket=len(data)

When creating a temporary Snake for preprocessing (type detection, normalization), **ALWAYS use `bucket=250`**:

```python
# WRONG — O(n^2) SAT on a single bucket, will timeout at >1K samples
mini = Snake(data, n_layers=1, bucket=max(len(data), 1), noise=0)

# CORRECT — O(n*250) with bucketing, fast at any scale
mini = Snake(data, n_layers=1, bucket=250, noise=0)
```

This applies to: orchestrator, supervisor, local simulation, client. The bucket parameter controls max partition size. Setting it to `len(data)` creates one bucket doing O(n^2) SAT construction — catastrophic.

## Large Data (>3MB)

Training data >4MB is chunked via `/cache-items` (each chunk <3MB), stored in S3, then the orchestrator reads and merges. Training >3K samples runs async — client polls until `status.json` shows `"ready"`.

Ranking data >3MB is chunked similarly via `cache_chunks`. The rank handler reads and merges server-side.

## Stripped Models

`to_json(stripped=True)` produces a model with `population=[]`. Predictions and probabilities work identically. Audit breaks (needs population for lookalike display).

| Samples | Full | Stripped | Savings |
|---------|------|----------|---------|
| 100 | 63KB | 40KB | 37% |
| 10K | 1.3MB | 0.1MB | 95% |
| 100K | ~13MB | ~0.5MB | 96% |

Inference Lambdas load stripped models by default. Audit requests load full models.

## Audit Report

```python
model.get_report(test_data=test, target_class="A", top=50)
# Produces: snake_audit_<model_id>.zip containing:
#   EXECUTIVE_SUMMARY.html    — print-to-PDF quality
#   MODEL_CARD.json           — version, config, features, classes
#   TRAINING_PROFILE.json     — class balance, feature stats
#   COST_AND_PERFORMANCE.json — training time, Lambda costs
#   model.json                — full Snake model
#   ranked_results.csv        — scored + ranked test items
#   audit_traces/
#     SUMMARY.txt             — one-liner per item
#     001_A.txt               — full SAT trace per datapoint
```

## Cost Tracking

Every API call logs to DynamoDB (`snake-batch-usage`):
- Endpoint, model_id, latency_ms, n_lambdas, estimated_cost_usd
- Queryable via `model.usage()` or the `/parallelism` dashboard

Typical costs:
- Training (100 samples, 5 layers): $0.00008
- Single prediction: $0.000001
- Rank 25K items: $0.0002

## AWS Architecture (v2 collapsed)

```
Client (monceai SDK)
  │ HTTPS
  ▼
API Gateway (snakebatch.aws.monce.ai)
  │
  ▼
API Lambda (2GB) — routes, auth, budget, cost tracking
  │
  ├─ /train → Orchestrator Lambda (4GB)
  │              Preprocess + chain build + fan-out
  │              ├─ Bucket v2 (2GB) × N — inline model, SAT construction
  │              └─ Writes model.json + model_stripped.json to S3
  │
  ├─ /predict → Inference Lambda (1GB) — loads stripped model, cached in /tmp
  │
  ├─ /rank → Scorer Lambda (2GB) × N — inline model, budgeted batch scoring
  │
  └─ /parallelism → snake.aws.monce.ai dashboard (CloudWatch + DynamoDB)
```

## Dependencies

- `requests` — HTTP client (the only runtime dependency)
- `algorithmeai-snake` — NOT required by monceai. Only needed if you want to run models locally after `to_json()`.

## Testing

```bash
cd /Users/charlesdana/Documents/monceai
PYTHONPATH=. SNAKE_API_KEY="sk-..." python3 -c "
from monceai import Snake
model = Snake([{'label':'A','x':1},{'label':'B','x':10}], target_index='label', n_layers=2, bucket=3)
print(model.get_prediction({'x': 1}))
"
```

Note: there's another `monceai` package at `/Users/charlesdana/Documents/claude-multistage.aws.monce.ai/src/monceai/`. Use `PYTHONPATH=.` or `cd` into this repo to avoid import conflicts.
