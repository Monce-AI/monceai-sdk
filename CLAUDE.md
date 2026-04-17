# monceai SDK — Guide for Claude

Cloud-backed LLM/VLM chat, Snake classifier, SAT solver.

Author: Charles Dana / Monce SAS.
Repo: `Monce-AI/monceai-sdk` (public)
Version: 0.3.0

## Package Layout

```
monceai/
  __init__.py       # Exports: LLM, VLM, Charles, LLMSession, LLMResult, Snake, SAT, ...
  llm.py            # LLM/VLM/Charles — 13 models via monceapp.aws.monce.ai (FREE, no auth)
  snake.py          # Cloud Snake classifier (SNAKE_API_KEY required)
  sat.py            # SAT solver cloud + local (SAT_API_KEY required)
  report.py         # Audit report ZIP generator
pyproject.toml      # depends on: requests
```

## Free (No API Key)

```python
from monceai import LLM, VLM, Charles

# Text → answer
r = LLM("6x7")                              # default model: charles-science
r = LLM("factor 10403", model="charles-auma")
r = LLM("hello", model="haiku")

r.text        # response text
r.json        # parsed dict (charles-json responses)
r.ok          # True if successful
r.elapsed_ms  # wall clock
r.sat_memory  # compute receipt

# Image → structured JSON
r = VLM("extract fields", image=open("doc.png", "rb").read())

# Smart router — auto-picks best sub-model
c = Charles()
c("6x7")                    # → charles-auma (math detected)
c("is K4 3-colorable?")     # → charles-science (graph/SAT detected)
c.math("minimize x^2")      # explicit: charles-auma
c.science("factor 91")      # explicit: charles-science
c.json("list primes")       # explicit: charles-json
c.vlm("describe", image=b)  # explicit: charles-json VLM

# Session (persistent context)
from monceai import LLMSession
s = LLMSession(model="charles")
s.send("my name is Charles")
s.send("what's my name?")
```

### 13 Model Shorthands

| Shorthand | Model ID | Free |
|-----------|----------|------|
| `charles-auma` | charles-auma | Yes |
| `charles-science` | charles-science | Yes |
| `charles` | charles | Yes |
| `charles-json` | charles-json | Yes |
| `charles-architect` | charles-architect | Yes |
| `concise` | concise | Yes |
| `cc` | cc | Yes |
| `sonnet` | eu.anthropic.claude-sonnet-4-6 | Yes |
| `sonnet4` | eu.anthropic.claude-sonnet-4-20250514-v1:0 | Yes |
| `haiku` | eu.anthropic.claude-haiku-4-5-20251001-v1:0 | Yes |
| `nova-pro` | eu.amazon.nova-pro-v1:0 | Yes |
| `nova-lite` | eu.amazon.nova-lite-v1:0 | Yes |
| `nova-micro` | eu.amazon.nova-micro-v1:0 | Yes |

### LLMResult Properties

| Property | Type | Description |
|----------|------|-------------|
| `text` | str | Response text |
| `json` | dict/None | Parsed JSON (None if not valid JSON) |
| `ok` | bool | True if response received and not error |
| `model` | str | Model that responded |
| `session_id` | str | Session ID for follow-up |
| `input_tokens` | int | Input token count |
| `output_tokens` | int | Output token count |
| `elapsed_ms` | int | Wall clock ms |
| `sat_memory` | dict | Compute receipt (formula, services, evals) |
| `raw` | dict | Full API response |

### Backend

All LLM/VLM calls go to `https://monceapp.aws.monce.ai/v1/chat` as multipart form POST.
- `message` = prompt text
- `model_id` = resolved model ID
- `file` = image bytes (optional, for VLM)
- `factory_id` = factory context (0 = none, 4 = VIP/Riou, etc.)

## API Key Required

### Snake (SNAKE_API_KEY)

```python
from monceai import Snake

Snake.warmup_all()
model = Snake(data, target_index="label", mode="fast")
model.get_prediction(X)
model.get_probability(X)
```

Backend: `https://snakebatch.aws.monce.ai`

### SAT (SAT_API_KEY)

```python
from monceai import SAT

result = SAT("p cnf 3 2\n1 2 0\n-1 3 0\n")
```

Backend: `https://npdollars.aws.monce.ai`

## Auth Summary

| Module | Env Var | Required |
|--------|---------|----------|
| LLM, VLM, Charles | None | No |
| Snake | `SNAKE_API_KEY` | Yes |
| SAT | `SAT_API_KEY` | Yes |

## Dependencies

- `requests` — the only runtime dependency

## CRITICAL: Never set bucket=len(data) in Snake

```python
# WRONG — O(n^2)
model = Snake(data, n_layers=1, bucket=max(len(data), 1))

# CORRECT
model = Snake(data, n_layers=1, bucket=250)
```
