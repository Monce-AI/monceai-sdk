"""monceai — Monce AI SDK.

Modules:
    Snake   — SAT-based explainable classifier (algorithmeai-snake).
    SAT     — Solve any SAT instance within a time budget.
    LLM     — Text/image in, answer out. 13 models via monceapp.aws.monce.ai.
    generate_report — Build HTML/PDF reports from model results.
"""

__version__ = "0.3.0"

from .snake import Snake
from .sat import SAT, SATSession, SATResult, SATProof
from .llm import LLM, VLM, Charles, LLMSession, LLMResult
from .report import generate_report
