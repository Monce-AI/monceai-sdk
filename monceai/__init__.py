"""monceai — Monce AI SDK.

Free (no API key):
    LLM     — Text in, answer out. 13 models. from monceai import LLM
    VLM     — Image + text in, structured JSON out. from monceai import VLM
    Charles — Smart router, fires sub-models in parallel. from monceai import Charles

API key required (SNAKE_API_KEY / SAT_API_KEY):
    Snake   — SAT-based explainable classifier (algorithmeai-snake).
    SAT     — Solve any SAT instance within a time budget.

    generate_report — Build HTML/PDF reports from model results.
"""

__version__ = "1.0.0"

from .snake import Snake
from .sat import SAT, SATSession, SATResult, SATProof
from .llm import LLM, VLM, Charles, Moncey, Json, LLMSession, LLMResult
from .report import generate_report
