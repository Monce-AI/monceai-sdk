"""monceai — Monce AI SDK.

Free (no API key):
    LLM        — Text in, answer out. 13 models. from monceai import LLM
    VLM        — Image + text in, structured JSON out. from monceai import VLM
    Charles    — Smart router, fires sub-models in parallel. from monceai import Charles
    Moncey     — Glass industry sales agent.
    Json       — Structured output (dict subclass).
    Concierge  — Monce knowledge base.
    Matching   — Factory-driven field matching (client + article). v1.1.0
    Calc       — Exact NP-complete arithmetic. v1.1.0
    Diff       — Raw vs monceai-enhanced side by side. v1.1.0

    Extraction — Memory-augmented file extraction. v1.2.0
    Outlook    — Email / Outlook workflow (extract + recall + remember). v1.2.0

API key required (SNAKE_API_KEY / SAT_API_KEY):
    Snake   — SAT-based explainable classifier (algorithmeai-snake).
    SAT     — Solve any SAT instance within a time budget.

    generate_report — Build HTML/PDF reports from model results.
"""

__version__ = "1.2.0"

from .snake import Snake
from .sat import SAT, SATSession, SATResult, SATProof
from .llm import (
    LLM, VLM, Charles, Moncey, Json, Concierge,
    LLMSession, LLMResult,
    Matching, Calc, Diff,
)
from .report import generate_report
from .extraction import Extraction
from .outlook import Outlook
