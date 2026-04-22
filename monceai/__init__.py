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
    Architect  — ASCII schemas / diagrams via charles-architect. v1.2.2

    Extraction — Memory-augmented file extraction. v1.2.0
    Outlook    — Email / Outlook workflow (extract + recall + remember). v1.2.0

API key required (SNAKE_API_KEY / SAT_API_KEY):
    Snake   — SAT-based explainable classifier (algorithmeai-snake).
    SAT     — Solve any SAT instance within a time budget.

    generate_report — Build HTML/PDF reports from model results.
"""

__version__ = "1.2.4"

from .snake import Snake
from .sat import SAT, SATSession, SATResult, SATProof
from .llm import (
    LLM, VLM, Charles, Moncey, Architect, Json, Concierge,
    LLMSession, LLMResult,
    Calc, Diff,
)
from .matching import (
    Matching,
    classify as matching_classify,
    parse_client_text,
    looks_like_client,
    looks_like_article,
    CLIENT_FIELDS,
    ARTICLE_FIELDS,
)
from .report import generate_report
from .extraction import Extraction
from .outlook import Outlook
from .monceos import MonceOS
from .synthax import Synthax, SynthaxJob, Stage
from .google import Google
from .compute import Computation
from .mlclass import ML
