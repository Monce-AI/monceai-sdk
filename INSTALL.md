# Installation — monceai SDK

LLM, VLM, Snake classifier, SAT solver. One `pip install`.

## 1. Install

```bash
pip install git+https://github.com/Monce-AI/monceai-sdk.git
```

Or from a local clone:

```bash
git clone https://github.com/Monce-AI/monceai-sdk.git
cd monceai-sdk
pip install -e .
```

The only dependency is `requests`.

## 2. Verify — No API Key Needed

```python
from monceai import LLM

r = LLM("what is 2+2?", model="haiku")
print(r.text)  # "4"
print(r.ok)    # True
```

If this works, you're connected. LLM, VLM, and Charles are free — no API key, no signup.

## 3. Quick Start

```python
from monceai import LLM, VLM, Charles

# Text → answer (13 models available)
r = LLM("6x7", model="charles-auma")           # AUMA boolean arithmetic
r = LLM("factor 10403", model="charles-science") # Snake router → 7 services
r = LLM("hello", model="haiku")                 # fast Haiku

# Image → structured JSON
r = VLM("describe this", image=open("photo.png", "rb").read())
r.json  # parsed dict

# Smart router
c = Charles()
c("any question")                  # auto-routes to best model
c.math("minimize x^2 - 4x + 4")   # → charles-auma
c.science("is K4 3-colorable?")    # → charles-science
c.json("list the planets")         # → charles-json
c.vlm("extract", image=img)        # → charles-json VLM
```

## 4. Models

| Shorthand | Speed | Cost | Best for |
|-----------|-------|------|----------|
| `haiku` | 1-2s | ~$0.003 | Fast general chat |
| `charles-auma` | 3-8s | ~$0.003 | Math, optimization, arithmetic from bits |
| `sonnet` | 1-3s | ~$0.03 | Premium quality |
| `charles-science` | 15-60s | ~$0.01 | Scientific computing (7 services) |
| `charles` | 8-15s | ~$0.01 | Deep analysis with compute |
| `charles-json` | 5-15s | ~$0.01 | Structured JSON, VLM |
| `nova-micro` | 0.6s | ~$0.0005 | Bulk cheap queries |

## 5. Snake & SAT (API Key Required)

For Snake classifier and SAT solver, set API keys:

```bash
export SNAKE_API_KEY="sk-snake-..."
export SAT_API_KEY="sk-sat-..."
```

```python
from monceai import Snake, SAT

# Snake classifier
model = Snake(data, target_index="label", mode="fast")
model.get_prediction(X)

# SAT solver
result = SAT("p cnf 3 2\n1 2 0\n-1 3 0\n")
print(result.result)  # "SAT"
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ImportError: monceai` | `pip install -e .` from repo root |
| `LLM() timeout` | Increase timeout: `LLM("...", timeout=60)` |
| Snake `401` | Check `SNAKE_API_KEY` is set |
| Cold starts | `Snake.warmup_all()` once at startup |
