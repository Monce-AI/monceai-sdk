"""
monceai.SAT — Solve any SAT instance within a time budget.

Backend: npdollars.aws.monce.ai — evolutive swarm SAT solver.
Three worker types (explorers + provers + solvers) enrich a shared
LogicSpace dictionary. Explorers grow implications, provers shrink
assumptions (uphill), solvers attack the residual with Kissat.

Budget enforcement:
    The budget= parameter is a hard ceiling in seconds.
    Cloud mode: HTTP timeout at budget + 2s grace.
    Local mode: LogicSpace supervise + Kissat within budget.

If SAT: assignment exhibited (signed int list).
If UNSAT: LogicSpace proof returned (backbones, tension, dictionary stats).

Usage:

    from monceai import SAT

    result = SAT("problem.cnf")                    # 60s budget
    result = SAT("problem.cnf", budget=1.0)         # 1s budget
    result = SAT(dimacs_string, budget=5.0)          # from string

    bool(result)           # True if SAT or UNSAT (solved)
    result.result          # "SAT", "UNSAT", "UNKNOWN", "TIMEOUT"
    result.assignment      # [1, -2, 3, ...] if SAT — exhibited solution
    result.proof           # dict if UNSAT — LogicSpace proof
    result.equation        # {T_compile_ms, T_swarm_ms, V_free, tension, ...}

    # Search log (new in v2):
    result.rounds          # number of swarm rounds
    result.round_reports   # per-round metrics (tension delta, entries, cost)
    result.cost            # total cost breakdown in USD
    result.tension         # final dictionary tension [0, 1]
"""

from __future__ import annotations
import json
import os
import time
import requests
from dataclasses import dataclass, field
from typing import Optional


DEFAULT_ENDPOINT = "https://npdollars.aws.monce.ai"


@dataclass
class SATProof:
    """LogicSpace UNSAT proof.

    The dictionary compiled the formula's implication structure and
    proved unsatisfiability via backbone convergence, exhaustive split,
    or swarm enrichment.
    """
    backbones: list[int]           # forced literals
    tension: float                 # dictionary saturation [0, 1]
    entries: int                   # dictionary entries compiled
    method: str                    # "compiler" | "backbone_convergence" | "solver_exhaustive"

    def __repr__(self):
        return (f"Proof(backbones={len(self.backbones)}, "
                f"tension={self.tension:.3f}, "
                f"entries={self.entries}, method={self.method})")


@dataclass
class SATResult:
    """Result from the npdollars SAT solver."""

    result: str                                 # "SAT", "UNSAT", "UNKNOWN", "TIMEOUT", "BUDGET_EXCEEDED"
    solved_by: str = "none"                     # "kissat_direct", "logicspace_init", "swarm", "solver"
    budget: float = 60.0
    session_id: str = ""                        # task ID for tracking / resume

    # Timing
    total_ms: float = 0.0
    compile_ms: float = 0.0
    swarm_ms: float = 0.0

    # If SAT: exhibited solution
    assignment: Optional[list[int]] = None      # [1, -2, 3] = x1=T, x2=F, x3=T

    # If UNSAT: LogicSpace proof
    proof: Optional[SATProof] = None

    # Equation diagnostics
    c_ratio: Optional[float] = None             # |V_free| / log2(n)
    equation: Optional[dict] = None             # {T_compile_ms, T_swarm_ms, V_free, tension}

    # Dictionary state
    tension: float = 0.0                        # final dictionary tension [0, 1]
    entries: int = 0                            # final dictionary size
    backbones: int = 0                          # forced variables count
    promotions_total: int = 0                   # entries promoted (left side shrunk)

    # Cost
    total_cost_usd: float = 0.0
    cost_breakdown: Optional[dict] = None       # {"explorer": 0.01, "prover": 0.02, ...}

    # Search log
    rounds: int = 0
    round_reports: list = field(default_factory=list)
    worker_count: int = 0

    # Audit (on TIMEOUT)
    ui: str = ""                                # post-mortem URL
    audit: Optional[dict] = None                # {kissat_direct, swarm_dispatched, ...}

    # Formula stats
    n_vars: int = 0
    n_clauses: int = 0

    def __bool__(self):
        return self.result in ("SAT", "UNSAT")

    def __repr__(self):
        parts = [f"SAT({self.result}"]
        if self.session_id:
            parts.append(f"id={self.session_id}")
        if self.result == "SAT" and self.assignment:
            parts.append(f"solution={len(self.assignment)} vars")
        if self.result == "UNSAT" and self.proof:
            parts.append(f"proof={self.proof.method}")
        if self.result == "TIMEOUT":
            parts.append(f"task={self.session_id}")
        parts.append(f"tension={self.tension:.3f}")
        if self.rounds > 0:
            parts.append(f"rounds={self.rounds}")
        if self.total_cost_usd > 0:
            parts.append(f"${self.total_cost_usd:.4f}")
        parts.append(f"{self.total_ms:.0f}ms")
        return ", ".join(parts) + ")"

    @property
    def cost(self) -> dict:
        """Cost summary."""
        return {
            "total_usd": self.total_cost_usd,
            "breakdown": self.cost_breakdown or {},
        }

    def verify(self, clauses: list[list[int]] = None) -> bool:
        """Verify SAT assignment against clauses (if provided)."""
        if self.result != "SAT" or not self.assignment:
            return False
        if clauses is None:
            return True
        asgn = set(self.assignment)
        return all(any(l in asgn for l in c) for c in clauses)


def SAT(input, budget: float = 60.0, vocal: bool = False,
        mode: str = "cloud", endpoint: str | None = None,
        api_key: str | None = None,
        budget_dollars: float = 1.0) -> SATResult:
    """Solve a SAT instance within a time budget.

    Args:
        input: DIMACS file path, DIMACS string, raw bytes, or any object
               with a .to_dimacs() method.
        budget: time budget in seconds (default 60s). Hard ceiling.
        vocal: print progress to stdout.
        mode: "cloud" (npdollars backend) or "local" (LogicSpace + Kissat).
        endpoint: API URL override.
        api_key: Bearer token. Defaults to SAT_API_KEY env var.
        budget_dollars: dollar budget for cloud mode (default $1.00).

    Returns:
        SATResult with:
        - If SAT: .assignment = exhibited solution (signed int list)
        - If UNSAT: .proof = LogicSpace proof (backbones, tension, method)
        - Always: .equation, .rounds, .round_reports, .cost, .total_ms
    """
    if mode == "local":
        return _local_solve(input, budget, vocal)
    return _cloud_solve(input, budget, vocal, endpoint, api_key, budget_dollars)


def _cloud_solve(input, budget: float, vocal: bool,
                 endpoint: str | None, api_key: str | None,
                 budget_dollars: float) -> SATResult:
    """Cloud solve: POST to npdollars swarm backend."""
    t_start = time.perf_counter()
    ep = (endpoint or os.environ.get("SAT_ENDPOINT", DEFAULT_ENDPOINT)).rstrip("/")
    key = api_key or os.environ.get("SAT_API_KEY", "")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    dimacs_str = _read_dimacs(input)
    n_vars, n_clauses = _parse_header(dimacs_str)

    if vocal:
        print(f"  Formula: {n_vars} vars, {n_clauses} clauses")
        print(f"  Endpoint: {ep}/solve")
        print(f"  Budget: {budget}s, ${budget_dollars}")

    try:
        resp = requests.post(
            f"{ep}/solve",
            json={
                "dimacs": dimacs_str,
                "budget": budget,
                "budget_dollars": budget_dollars,
                "sync": True,
            },
            headers=headers,
            timeout=budget + 5.0,
        )
        total_ms = (time.perf_counter() - t_start) * 1000

        if resp.status_code != 200:
            return SATResult(result="TIMEOUT", budget=budget, total_ms=total_ms,
                             n_vars=n_vars, n_clauses=n_clauses)

        r = resp.json()
        # Handle API Gateway wrapper
        if "body" in r and isinstance(r["body"], str):
            r = json.loads(r["body"])

        return _parse_response(r, budget, total_ms, n_vars, n_clauses, vocal)

    except requests.exceptions.Timeout:
        total_ms = (time.perf_counter() - t_start) * 1000
        if vocal:
            print(f"  TIMEOUT at {total_ms:.0f}ms")
        return SATResult(result="TIMEOUT", budget=budget, total_ms=total_ms,
                         n_vars=n_vars, n_clauses=n_clauses)

    except Exception:
        total_ms = (time.perf_counter() - t_start) * 1000
        return SATResult(result="UNKNOWN", budget=budget, total_ms=total_ms,
                         n_vars=n_vars, n_clauses=n_clauses)


def _local_solve(input, budget: float, vocal: bool) -> SATResult:
    """Local solve: LogicSpace supervise + Kissat."""
    t_start = time.perf_counter()

    try:
        from logicspace import LogicSpace
    except ImportError:
        raise ImportError(
            "Local mode requires logicspace. Install:\n"
            "  pip install -e /path/to/logicspace.aws.monce.ai"
        )

    import math
    import tempfile
    import subprocess

    dimacs_str = _read_dimacs(input)
    n_vars, n_clauses = _parse_header(dimacs_str)

    # Parse clauses
    clauses = []
    for line in dimacs_str.splitlines():
        line = line.strip()
        if not line or line[0] in ("c", "p", "%"):
            continue
        lits = [int(x) for x in line.split() if int(x) != 0]
        if lits:
            clauses.append(lits)

    if vocal:
        print(f"  Formula: {n_vars} vars, {len(clauses)} clauses")

    # Phase 1: LogicSpace supervise
    ls = LogicSpace.from_clauses(n_vars, clauses)
    learn_budget = max(n_vars ** 2, 1000)

    if vocal:
        print(f"  LogicSpace: budget={learn_budget} evals")

    result = ls.supervise(budget=learn_budget, vocal=vocal)
    compile_ms = (time.perf_counter() - t_start) * 1000

    snap = ls.kpis()

    if result == "SAT":
        return SATResult(
            result="SAT", solved_by="compiler", budget=budget,
            total_ms=compile_ms, compile_ms=compile_ms,
            assignment=ls.solution,
            n_vars=n_vars, n_clauses=n_clauses,
            tension=snap.get("tension", 0),
            entries=len(ls.D.entries) if hasattr(ls, "D") else 0,
            equation={"T_compile_ms": compile_ms, "T_swarm_ms": 0,
                      "V_free": 0, "tension": snap.get("tension", 0)},
        )

    if result == "UNSAT":
        bb = ls.backbones()
        stats = ls.stats()
        return SATResult(
            result="UNSAT", solved_by="compiler", budget=budget,
            total_ms=compile_ms, compile_ms=compile_ms,
            n_vars=n_vars, n_clauses=n_clauses,
            tension=snap.get("tension", 0),
            entries=stats.get("entries", 0),
            backbones=len(bb),
            proof=SATProof(
                backbones=bb,
                tension=snap.get("tension", 0),
                entries=stats.get("entries", 0),
                method="compiler",
            ),
            equation={"T_compile_ms": compile_ms, "T_swarm_ms": 0,
                      "V_free": 0, "tension": snap.get("tension", 0)},
        )

    # Phase 2: Export optimal CNF + Kissat
    bb = ls.backbones()
    bb_vars = set(abs(l) for l in bb)
    free_vars = [v for v in range(1, n_vars + 1) if v not in bb_vars]
    n_free = len(free_vars)
    c_ratio = n_free / max(1, math.log2(n_vars)) if n_vars > 1 else 0

    forced_map = {abs(l): (1 if l > 0 else 0) for l in bb}
    optimal = [[l] for l in bb]
    for c in clauses:
        satisfied = False
        new_c = []
        for l in c:
            var = abs(l)
            if var in forced_map:
                val = forced_map[var]
                if (l > 0 and val == 1) or (l < 0 and val == 0):
                    satisfied = True
                    break
            else:
                new_c.append(l)
        if not satisfied and new_c:
            optimal.append(new_c)

    # Add learned clauses from dictionary
    if hasattr(ls, "D"):
        for key, val in ls.D.entries.items():
            if not key:
                continue
            gain = val - key
            for g in gain:
                clause = [-l for l in key] + [g]
                if len(clause) <= 3:
                    optimal.append(clause)

    remaining_budget = budget - (time.perf_counter() - t_start)
    if remaining_budget <= 0.1:
        return SATResult(
            result="TIMEOUT", budget=budget,
            total_ms=(time.perf_counter() - t_start) * 1000,
            compile_ms=compile_ms,
            n_vars=n_vars, n_clauses=n_clauses, c_ratio=c_ratio,
            tension=snap.get("tension", 0),
        )

    lines = [f"p cnf {n_vars} {len(optimal)}"]
    for c in optimal:
        lines.append(" ".join(str(l) for l in c) + " 0")
    optimal_dimacs = "\n".join(lines) + "\n"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".cnf", delete=False) as tmp:
        tmp.write(optimal_dimacs)
        tmp_path = tmp.name

    kissat_path = os.environ.get("KISSAT_PATH", "kissat")
    t_knife = time.perf_counter()

    try:
        proc = subprocess.run(
            [kissat_path, tmp_path],
            capture_output=True, text=True,
            timeout=remaining_budget,
        )
        knife_ms = (time.perf_counter() - t_knife) * 1000
        total_ms = (time.perf_counter() - t_start) * 1000

        if proc.returncode == 10:
            assignment = []
            for line in proc.stdout.splitlines():
                if line.startswith("v "):
                    for tok in line[2:].split():
                        val = int(tok)
                        if val != 0:
                            assignment.append(val)
            return SATResult(
                result="SAT", solved_by="logicspace+kissat", budget=budget,
                total_ms=total_ms, compile_ms=compile_ms,
                assignment=assignment,
                n_vars=n_vars, n_clauses=n_clauses, c_ratio=c_ratio,
                tension=snap.get("tension", 0),
                equation={"T_compile_ms": compile_ms, "T_swarm_ms": 0,
                          "T_solve_ms": knife_ms, "V_free": n_free,
                          "tension": snap.get("tension", 0)},
            )

        if proc.returncode == 20:
            stats = ls.stats()
            return SATResult(
                result="UNSAT", solved_by="logicspace+kissat", budget=budget,
                total_ms=total_ms, compile_ms=compile_ms,
                n_vars=n_vars, n_clauses=n_clauses, c_ratio=c_ratio,
                tension=snap.get("tension", 0),
                entries=stats.get("entries", 0),
                backbones=len(bb),
                proof=SATProof(
                    backbones=bb,
                    tension=snap.get("tension", 0),
                    entries=stats.get("entries", 0),
                    method="logicspace+kissat",
                ),
                equation={"T_compile_ms": compile_ms, "T_swarm_ms": 0,
                          "T_solve_ms": knife_ms, "V_free": n_free,
                          "tension": snap.get("tension", 0)},
            )

        return SATResult(
            result="UNKNOWN", budget=budget,
            total_ms=(time.perf_counter() - t_start) * 1000,
            compile_ms=compile_ms,
            n_vars=n_vars, n_clauses=n_clauses, c_ratio=c_ratio,
            tension=snap.get("tension", 0),
        )

    except subprocess.TimeoutExpired:
        total_ms = (time.perf_counter() - t_start) * 1000
        return SATResult(
            result="TIMEOUT", budget=budget, total_ms=total_ms,
            compile_ms=compile_ms,
            n_vars=n_vars, n_clauses=n_clauses, c_ratio=c_ratio,
            tension=snap.get("tension", 0),
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ─── Helpers ─────────────────────────────────────────────────────

def _read_dimacs(input) -> str:
    """Read input to clean DIMACS string."""
    if isinstance(input, bytes):
        raw = input.decode(errors="ignore")
    elif isinstance(input, str):
        if os.path.isfile(input):
            with open(input) as f:
                raw = f.read()
        else:
            raw = input
    elif hasattr(input, "to_dimacs"):
        raw = input.to_dimacs()
    else:
        raise TypeError(f"Expected file path, DIMACS string, or Formula, got {type(input)}")

    clean = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped in ("%", "0") and not stripped.startswith("p"):
            break
        clean.append(line)
    return "\n".join(clean) + "\n"


def _parse_header(dimacs: str) -> tuple[int, int]:
    """Extract n_vars and n_clauses from DIMACS header."""
    for line in dimacs.splitlines():
        line = line.strip()
        if line.startswith("p cnf"):
            parts = line.split()
            return int(parts[2]), int(parts[3])
    return 0, 0


def _parse_response(r: dict, budget: float, total_ms: float,
                    n_vars: int, n_clauses: int, vocal: bool) -> SATResult:
    """Parse npdollars API response into SATResult."""
    result_str = r.get("result", "UNKNOWN")
    solved_by = r.get("solved_by", "none")
    equation = r.get("equation")
    sid = r.get("session_id", "")

    if vocal:
        print(f"  [{sid}] {result_str} by {solved_by} in {r.get('total_ms', 0):.0f}ms")
        if r.get("rounds"):
            print(f"  Rounds: {r['rounds']}, tension: {r.get('tension', 0):.3f}")
        if r.get("total_cost_usd"):
            print(f"  Cost: ${r['total_cost_usd']:.4f}")
        if result_str == "TIMEOUT":
            ui_url = r.get("ui", "")
            print(f"  Task ID: {sid}")
            if ui_url:
                print(f"  Post-mortem: {ui_url}")

    # Build proof if UNSAT
    proof = None
    if result_str == "UNSAT" and r.get("proof"):
        p = r["proof"]
        proof = SATProof(
            backbones=p.get("backbones", []),
            tension=p.get("tension", 0),
            entries=p.get("entries", 0),
            method=p.get("method", solved_by),
        )
        if vocal:
            print(f"  Proof: {proof}")

    return SATResult(
        result=result_str,
        solved_by=solved_by,
        budget=budget,
        session_id=sid,
        total_ms=total_ms,
        compile_ms=r.get("compile_ms", 0),
        swarm_ms=r.get("swarm_ms", 0),
        assignment=r.get("assignment"),
        proof=proof,
        c_ratio=equation.get("c_ratio") if equation else None,
        equation=equation,
        tension=r.get("tension", 0),
        entries=r.get("entries", 0),
        backbones=r.get("backbones", 0),
        promotions_total=r.get("promotions_total", 0),
        total_cost_usd=r.get("total_cost_usd", 0),
        cost_breakdown=r.get("cost_breakdown"),
        rounds=r.get("rounds", 0),
        round_reports=r.get("round_reports", []),
        worker_count=r.get("workers_total", r.get("worker_count", 0)),
        ui=r.get("ui", ""),
        audit=r.get("audit"),
        n_vars=n_vars or r.get("n_vars", 0),
        n_clauses=n_clauses or r.get("n_clauses", 0),
    )
