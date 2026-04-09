# monceai SDK — Guide for Claude

Cloud-backed Snake classifier + SAT solver. Drop-in for `algorithmeai.Snake`.

Author: Charles Dana / Monce SAS.
Repo: `Monce-AI/monceai-sdk`
Backend: `Monce-AI/snake-monceai-api` (`https://snakebatch.aws.monce.ai`)
SAT backend: `https://npdollars.aws.monce.ai`

## Package Layout

```
monceai/
  __init__.py       # Exports: Snake, SAT, generate_report
  snake.py          # Cloud Snake -- drop-in for algorithmeai.Snake
  sat.py            # SAT solver (cloud + local)
  report.py         # Audit report ZIP generator
pyproject.toml      # depends on: requests
paper.pdf           # SnakeBatch paper (April 2026)
```

## Quick Start

```python
from monceai import Snake

Snake.warmup_all()                                          # warm all Lambdas
model = Snake(data, target_index="label", mode="fast")      # train
model.get_prediction(X)                                     # predict
model.get_probability(X)                                    # probabilities
```

## Training Modes

| Mode | Layers | Bucket | Use case |
|------|--------|--------|----------|
| fast | 25 | 16 | Quick iteration, demos |
| balanced | 50 | 32 | Production default |
| heavy | 100 | 64 | Maximum accuracy |

`n_layers=` and `bucket=` override mode when set explicitly.

## Constructor Modes

```python
Snake(data, target_index="label")        # Train from list[dict]
Snake(model_id="snake-abc-123")          # Connect to existing model
Snake("snake-abc-123")                   # Shorthand
Snake("model.json")                      # Upload local Snake model
```

## Methods

| Method | Returns | Notes |
|--------|---------|-------|
| `get_prediction(X)` | str | Top class |
| `get_probability(X)` | dict | {class: float}, sums to 1.0 |
| `get_audit(X)` | str | SAT reasoning trace (needs full model) |
| `get_augmented(X)` | dict | Prediction + probability + audit + lookalikes |
| `get_lookalikes(X)` | list | Matching training samples |
| `get_lookalikes_labeled(X)` | list | With core/noise origin labels |
| `get_batch_rank(items, target_class, top, budget_ms)` | RankResult | Budgeted top-K |
| `get_batch_prediction(items, mode, budget_ms)` | list | Parallel predictions |
| `to_json(path, stripped=False)` | str | Download model (algorithmeai-compatible) |
| `get_report(test_data, target_class, top)` | str | Audit report ZIP |
| `info()` | dict | Model metadata |
| `usage(limit)` | dict | API usage + costs |
| `warmup(workers)` | dict | Pre-warm scorer Lambdas |
| `warmup_all(scorers)` | dict | Warm ALL Lambdas (class method) |
| `estimate(n_samples, n_layers)` | dict | Cost estimate (static method) |

## Properties

| Property | Type | Description |
|----------|------|-------------|
| `model_id` | str | Unique model identifier |
| `wall_clock_ms` | int | Server-side training time |
| `breakdown` | dict | Per-stage timing |
| `log` | str | Server training summary |
| `training_info` | dict | Full response (includes dedup stats) |

## Auth

API key from `SNAKE_API_KEY` env var. Bearer token auth on all endpoints except `/estimate`.

## Budget System

Every budgeted call subtracts 500ms overhead (network), sends the rest to the server.

## CRITICAL: Preprocessing — NEVER set bucket=len(data)

```python
# WRONG — O(n^2)
mini = Snake(data, n_layers=1, bucket=max(len(data), 1), noise=0)

# CORRECT
mini = Snake(data, n_layers=1, bucket=250, noise=0)
```

## Dependencies

- `requests` — the only runtime dependency
- `algorithmeai-snake` — NOT required. Only for `to_json()` local use.

## Note

There is another `monceai` package at the VLM extraction repo (`claude-multistage.aws.monce.ai`). That is the glass manufacturing extraction pipeline. This package is the Snake/SAT cloud SDK. Use `PYTHONPATH=.` or `pip install -e .` to avoid import conflicts.
