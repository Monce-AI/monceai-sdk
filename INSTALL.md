# Installation — monceai SDK

Python client for distributed Snake classification and SAT solving on AWS Lambda.

## Prerequisites

- Python 3.9+
- A `SNAKE_API_KEY` (get one from the API admin)

## 1. Install

From GitHub (internal):

```bash
pip install git+ssh://git@github.com/Monce-AI/monceai-sdk.git
```

From local clone:

```bash
git clone git@github.com:Monce-AI/monceai-sdk.git
cd monceai-sdk
pip install -e .
```

The only dependency is `requests`.

## 2. Set API Key

```bash
# Add to your shell profile (~/.zshrc or ~/.bashrc)
export SNAKE_API_KEY="sk-snake-YOUR-TOKEN"
```

Or pass it directly:

```python
from monceai import Snake
model = Snake(data, target_index="label", api_key="sk-snake-YOUR-TOKEN")
```

## 3. Verify

```python
from monceai import Snake

# Warm all Lambda containers (eliminates cold starts)
result = Snake.warmup_all()
print(result)
# {'api': True, 'orchestrator': True, 'inference': True, 'scorers': 5, 'wall_clock_ms': 109}
```

If this works, you're connected.

## 4. Train Your First Model

```python
from monceai import Snake

data = [
    {"age": 22, "fare":  7.25, "sex": "male",   "class": 3, "survived": 0},
    {"age": 38, "fare": 71.28, "sex": "female", "class": 1, "survived": 1},
    {"age": 26, "fare":  7.92, "sex": "male",   "class": 3, "survived": 0},
    {"age": 35, "fare": 53.10, "sex": "female", "class": 1, "survived": 1},
    {"age": 28, "fare":  8.05, "sex": "male",   "class": 3, "survived": 0},
    {"age": 27, "fare": 11.13, "sex": "female", "class": 3, "survived": 1},
    {"age": 54, "fare": 51.86, "sex": "male",   "class": 1, "survived": 0},
    {"age":  2, "fare": 21.07, "sex": "female", "class": 3, "survived": 1},
    {"age": 14, "fare": 30.07, "sex": "female", "class": 2, "survived": 1},
    {"age":  4, "fare": 16.70, "sex": "male",   "class": 3, "survived": 1},
]

model = Snake(data, target_index="survived", mode="fast")
print(model)
# Snake(model_id='snake-abc-123', 600ms, log='Distributed training (v3): 25L, bucket=16, ...')
```

## 5. Predict

```python
# Single prediction
model.get_prediction({"age": 25, "fare": 50.0, "sex": "female", "class": 1})
# -> 1

# Probabilities
model.get_probability({"age": 25, "fare": 50.0, "sex": "female", "class": 1})
# -> {'0': 0.03, '1': 0.97}

# Full audit trace (explainable)
model.get_audit({"age": 25, "fare": 50.0, "sex": "female", "class": 1})
```

## 6. Training Modes

```python
model = Snake(data, target_index="survived", mode="fast")       # 25 layers, bucket 16
model = Snake(data, target_index="survived", mode="balanced")    # 50 layers, bucket 32
model = Snake(data, target_index="survived", mode="heavy")       # 100 layers, bucket 64
model = Snake(data, target_index="survived", n_layers=77)        # explicit override
```

| Mode | Layers | Bucket | Speed (200 rows) |
|------|--------|--------|-------------------|
| fast | 25 | 16 | ~600ms |
| balanced | 50 | 32 | ~1.0s |
| heavy | 100 | 64 | ~1.7s |

## 7. Batch Ranking (Large Scale)

```python
# Rank 25,000 items within 1 second
result = model.get_batch_rank(
    items=test_data,
    target_class="1",
    top=100,
    budget_ms=1000,
)

print(result)
# RankResult(top=100, scored=4750/25000, 850ms, workers=15)

# Reuse cache for repeated calls
result2 = model.get_batch_rank(
    items_key=result.cache_key,   # skip upload
    target_class="1",
    top=100,
    budget_ms=1000,
)
```

## 8. Save and Load Locally

```python
# Download from cloud
model.to_json("model.json")                       # full model
model.to_json("model_stripped.json", stripped=True) # 95% smaller, no audit

# Load locally (requires: pip install algorithmeai-snake)
from algorithmeai import Snake as LocalSnake
local = LocalSnake("model.json")
local.get_prediction({"age": 25, "fare": 50.0, "sex": "female", "class": 1})
```

## 9. SAT Solver

```python
from monceai import SAT

result = SAT("p cnf 3 2\n1 2 0\n-1 3 0\n")
print(result.satisfiable)    # True
print(result.assignment)     # {1: True, 2: False, 3: True}
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `401 Unauthorized` | Check `SNAKE_API_KEY` is set |
| `ImportError: monceai` | Run `pip install -e .` from repo root |
| Cold start ~2s | Call `Snake.warmup_all()` once at startup |
| Prediction returns `None` | Small dataset (<20 rows) can hit empty buckets. Use more data or check `model.training_info` for fallback flag |
| Import conflict with VLM monceai | Use `PYTHONPATH=.` or install this package with `pip install -e .` |
