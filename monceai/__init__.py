"""monceai — Monce AI SDK.

Modules:
    Snake   — SAT-based explainable classifier (algorithmeai-snake).
    SAT     — Solve any SAT instance within a time budget.
              Cloud mode (API Gateway + Lambda) or local (fast_fork + kissat).
    generate_report — Build HTML/PDF reports from model results.
"""

__version__ = "0.2.0"

from .snake import Snake
from .sat import SAT
from .report import generate_report
