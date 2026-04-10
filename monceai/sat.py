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
        mode: str = "local", solve_mode: str = "haiku",
        endpoint: str | None = None,
        api_key: str | None = None,
        budget_dollars: float = 1.0) -> "SATSession":
    """Solve a SAT instance within a time budget.

    Returns a SATSession — a live object with the dictionary,
    learned clauses, backbones, and full LogicSpace state.
    The result is on .result. If TIMEOUT, resume with more budget:

        s = SAT("problem.cnf", budget=10)
        s.result          # "SAT" | "UNSAT" | "TIMEOUT"
        s.D               # the dictionary — all learned knowledge
        s.backbones       # forced literals
        s.tension         # |backbones| / n_vars
        s.entry_histogram()

        # TIMEOUT? Keep going:
        s.swarm(budget=30)
        s.prove(budget=10)
        s.solve(budget=5)

    Args:
        input: DIMACS file path, DIMACS string, raw bytes, or any object
               with a .to_dimacs() method.
        budget: time budget in seconds (default 60s). Hard ceiling.
        vocal: print progress to stdout.
        mode: "local" (LogicSpace + Kissat) or "cloud" (npdollars backend).
        solve_mode: worker budget tier for cloud mode.
        endpoint: API URL override.
        api_key: Bearer token. Defaults to SAT_API_KEY env var.
        budget_dollars: dollar budget for cloud mode (default $1.00).

    Returns:
        SATSession with .result (SATResult), .D (Dictionary), .backbones, etc.
    """
    if mode == "cloud":
        # Cloud mode: one-shot, wraps response in a session shell
        result = _cloud_solve(input, budget, vocal, endpoint, api_key,
                              budget_dollars, solve_mode)
        session = SATSession(input)
        session.result = result
        return session

    session = SATSession(input)
    session.swarm(budget=budget, vocal=vocal)
    return session


def _cloud_solve(input, budget: float, vocal: bool,
                 endpoint: str | None, api_key: str | None,
                 budget_dollars: float,
                 solve_mode: str = "haiku") -> SATResult:
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
                "mode": solve_mode,
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


# ─── SATSession — interactive prove-loop solver ────────────────────────


class SATSession:
    """Interactive SAT solver session.

    Compiles formula into a LogicSpace Dictionary, then alternates
    polynomial prove rounds (entry promotion) with Kissat solves.

    Usage:
        s = SATSession("problem.cnf")
        s.prove(budget=5.0, vocal=True)
        s.solve(budget=10.0)
        s.run(budget=60.0, vocal=True)
    """

    def __init__(self, input, kissat_path: str | None = None):
        from logicspace import Dictionary

        self._dimacs = _read_dimacs(input)
        self.n_vars, self.n_clauses = _parse_header(self._dimacs)
        self._kissat_path = kissat_path or os.environ.get("KISSAT_PATH", "kissat")
        self.result: SATResult | None = None
        self.log: list[str] = []

        # Parse clauses
        self._clauses = []
        for line in self._dimacs.splitlines():
            line = line.strip()
            if not line or line[0] in ("c", "p", "%"):
                continue
            lits = [int(x) for x in line.split() if int(x) != 0]
            if lits:
                self._clauses.append(lits)

        # Build dictionary
        self.D = Dictionary(self.n_vars)
        for c in self._clauses:
            self.D.seed(c)
        self.D.chain(max_rounds=10)
        self.D.conflicts()

        self._log(f"compiled: {self.n_vars} vars, {self.n_clauses} clauses, "
                  f"{len(self.D.entries)} entries, {len(self.backbones)} backbones")

    # ── Properties ────────────────────────────────────────

    @property
    def status(self) -> str:
        s, _ = self.D.solve()
        return s

    @property
    def backbones(self) -> list[int]:
        return self.D.backbones()

    @property
    def tension(self) -> float:
        return len(self.backbones) / max(self.n_vars, 1)

    @property
    def entries(self) -> int:
        return len(self.D.entries)

    def entry_histogram(self) -> dict[int, int]:
        h: dict[int, int] = {}
        for key in self.D.entries:
            ks = len(key)
            h[ks] = h.get(ks, 0) + 1
        return dict(sorted(h.items()))

    def gain_summary(self) -> dict:
        gains = [len(v) - len(k) for k, v in self.D.entries.items() if k]
        return {
            "total_gain": sum(gains),
            "avg_gain": sum(gains) / len(gains) if gains else 0,
            "max_gain": max(gains) if gains else 0,
            "entries": len(gains),
        }

    def _stopped(self) -> bool:
        """Check if run() signalled cancellation."""
        return getattr(self, "_cancel", False)

    # ── Core: swarm (exponential spawn) ───────────────────

    def swarm(self, budget: float = 60.0, atom: float = 1.0,
              max_depth: int = 15, max_workers: int = 10000,
              vocal: bool = False) -> SATResult:
        """Exponential BCP+CDCL swarm. The real solver.

        Each worker:
          1. BCP: D.deduce(branch) → contradiction? → learned clause, DONE
          2. SPLIT: pick variable, fire 2 children (async)
          3. CDCL: Kissat with proof → extract short learned clauses
          4. FEED: all clauses → dictionary → chain → conflict

        Workers spawn exponentially. BCP prunes before spawn.
        Dictionary strengthens every round. Convergence.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading

        t0 = time.perf_counter()
        deadline = t0 + budget
        self._cancel = False

        # Shared state (thread-safe via lock)
        lock = threading.Lock()
        workers_fired = [0]
        clauses_fed = [0]
        solution = [None]  # [model] if SAT found
        # Build optimal once, workers share it read-only
        optimal_snap = [self._build_optimal_dimacs()]

        def _worker(branch: list[int], depth: int):
            """One BCP+CDCL worker. May spawn children."""
            if self._stopped() or solution[0] is not None:
                return
            if time.perf_counter() > deadline:
                return

            with lock:
                workers_fired[0] += 1
                if workers_fired[0] > max_workers:
                    return

            # 1. BCP
            trail = self.D.deduce(frozenset(branch))
            if self.D.contradicts(trail):
                clause = [-l for l in branch]
                with lock:
                    self.D.seed(clause, original=False)
                    clauses_fed[0] += 1
                return

            # 2. CDCL: Kissat with proof extraction
            remaining = deadline - time.perf_counter()
            if remaining < 0.1:
                return
            probe_atom = min(atom, remaining)

            res, model, learned_clauses, kms = \
                self._kissat_with_proof(
                    branch, probe_atom, dimacs=optimal_snap[0])

            if res == "SAT" and model:
                solution[0] = model
                self._cancel = True
                return

            if res == "UNSAT" and learned_clauses:
                with lock:
                    for c in learned_clauses:
                        if len(c) <= max_depth:
                            self.D.seed(c, original=False)
                            clauses_fed[0] += 1
                    if clauses_fed[0] % 100 == 0:
                        self.D.chain(max_rounds=2)
                        self.D.conflicts()
                        # Rebuild optimal for future workers
                        optimal_snap[0] = self._build_optimal_dimacs()

            # 3. SPLIT: pick variable, spawn 2 children
            if depth >= max_depth or solution[0] is not None:
                return

            assigned = {abs(l) for l in trail}
            split_var = None
            for v in range(1, self.n_vars + 1):
                if v not in assigned:
                    split_var = v
                    break
            if split_var is None:
                return

            for pol in [split_var, -split_var]:
                child_branch = branch + [pol]
                child_trail = self.D.deduce(frozenset(child_branch))
                if self.D.contradicts(child_trail):
                    clause = [-l for l in child_branch]
                    with lock:
                        self.D.seed(clause, original=False)
                        clauses_fed[0] += 1
                else:
                    pool.submit(_worker, child_branch, depth + 1)

        # Fire the swarm
        pool = ThreadPoolExecutor(max_workers=min(64, max_workers))
        try:
            # Start with root
            pool.submit(_worker, [], 0)

            # Wait for completion or timeout
            while time.perf_counter() < deadline:
                if solution[0] is not None:
                    break
                # Check dictionary
                status, sol = self.D.solve()
                if status in ("SAT", "UNSAT"):
                    solution[0] = sol
                    self._cancel = True
                    break
                time.sleep(0.2)

        finally:
            self._cancel = True
            pool.shutdown(wait=False)

        # Final chain
        self.D.chain(max_rounds=5)
        self.D.conflicts()

        total_ms = (time.perf_counter() - t0) * 1000

        if vocal:
            print(f"  swarm: {workers_fired[0]} workers, "
                  f"{clauses_fed[0]} clauses, "
                  f"bb={len(self.backbones)}, "
                  f"t={self.tension:.3f}, "
                  f"{total_ms:.0f}ms")

        self._log(f"swarm: workers={workers_fired[0]} "
                  f"clauses={clauses_fed[0]} "
                  f"bb={len(self.backbones)} {total_ms:.0f}ms")

        if solution[0] is not None:
            self.result = self._make_result("SAT", solution[0], t0)
        else:
            status, sol = self.D.solve()
            if status in ("SAT", "UNSAT"):
                self.result = self._make_result(status, sol, t0)
            else:
                # Try Kissat on enriched optimal
                remaining = budget - (time.perf_counter() - t0)
                if remaining > 1.0:
                    r = self.solve(budget=remaining)
                    return r
                self.result = self._make_result("TIMEOUT", None, t0)

        return self.result

    def _kissat_with_proof(self, assumptions: list[int],
                           budget: float,
                           dimacs: str = None) -> tuple:
        """Run Kissat with DRAT proof, extract learned clauses.

        Returns (result, model, learned_clauses, ms).
        """
        import subprocess
        import tempfile

        optimal_dimacs = dimacs or self._build_optimal_dimacs()

        # Add assumptions as unit clauses
        if assumptions:
            lines = optimal_dimacs.splitlines()
            new_lines = []
            for line in lines:
                if line.startswith("p cnf"):
                    parts = line.split()
                    orig_c = int(parts[3])
                    new_lines.append(
                        f"p cnf {self.n_vars} "
                        f"{orig_c + len(assumptions)}")
                else:
                    new_lines.append(line)
            hdr = next(i for i, l in enumerate(new_lines)
                       if l.startswith("p cnf"))
            for lit in assumptions:
                new_lines.insert(hdr + 1, f"{lit} 0")
            optimal_dimacs = "\n".join(new_lines) + "\n"

        fd, cnf_path = tempfile.mkstemp(suffix=".cnf")
        fd2, proof_path = tempfile.mkstemp(suffix=".drat")
        os.close(fd2)

        t0 = time.perf_counter()
        try:
            with os.fdopen(fd, "w") as f:
                f.write(optimal_dimacs)

            if budget < 1.0:
                cmd = [self._kissat_path, cnf_path, proof_path,
                       "--no-binary", "--quiet"]
                timeout = budget + 0.2
            else:
                cmd = [self._kissat_path, cnf_path, proof_path,
                       "--no-binary", "--quiet",
                       f"--time={max(1, int(budget))}"]
                timeout = budget + 5

            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout)
            ms = (time.perf_counter() - t0) * 1000

            result = "TIMEOUT"
            model = None
            learned = []

            if proc.returncode == 10:
                result = "SAT"
                model = []
                for line in proc.stdout.splitlines():
                    if line.startswith("v "):
                        for tok in line[2:].split():
                            val = int(tok)
                            if val != 0:
                                model.append(val)

            elif proc.returncode == 20:
                result = "UNSAT"
                # Parse DRAT proof
                try:
                    with open(proof_path) as f:
                        for line in f:
                            line = line.strip()
                            if not line or line.startswith("d "):
                                continue
                            lits = []
                            for tok in line.split():
                                v = int(tok)
                                if v == 0:
                                    break
                                lits.append(v)
                            if lits:
                                learned.append(lits)
                except Exception:
                    pass

            return result, model, learned, ms

        except subprocess.TimeoutExpired:
            return "TIMEOUT", None, [], \
                   (time.perf_counter() - t0) * 1000
        finally:
            try:
                os.unlink(cnf_path)
            except OSError:
                pass
            try:
                os.unlink(proof_path)
            except OSError:
                pass

    # ── Core: probe ───────────────────────────────────────

    def probe(self, budget: float = 10.0, atom: float = 0.5,
              vocal: bool = False) -> dict:
        """Multi-depth sweep with recursive downscaling.

        Start deep (where Kissat resolves), learn clauses, BCP,
        then sweep shallower. Each depth level benefits from
        clauses learned at deeper levels.

        depth=20 → learn 20-lit clauses → chain+conflict
        depth=15 → enriched dict helps → learn 15-lit clauses
        depth=10 → even easier → shorter clauses
        depth=5  → may find backbones
        depth=0  → single-var probes, direct backbones

        Returns dict with backbones_found, clauses_learned, probes,
                        timeouts, ms.
        """
        import random as _rng

        t0 = time.perf_counter()
        deadline = t0 + budget

        bb_before = len(self.backbones)
        total_clauses = 0
        total_probes = 0
        total_timeouts = 0
        total_backbones = 0

        # Sweep from deep to shallow
        depths = [20, 15, 10, 5, 1]

        for depth in depths:
            if time.perf_counter() > deadline or self._stopped():
                break

            bb_set = {abs(l) for l in self.D.backbones()}
            free = [v for v in range(1, self.n_vars + 1)
                    if v not in bb_set]

            if depth > len(free):
                continue

            optimal_dimacs = self._build_optimal_dimacs()
            depth_clauses = 0
            depth_probes = 0
            depth_timeouts = 0
            depth_sat = 0

            # Budget per depth: split remaining time across levels
            remaining_depths = len([d for d in depths
                                    if d >= depth])
            depth_budget = min(
                (deadline - time.perf_counter()) / max(remaining_depths, 1),
                (deadline - time.perf_counter()) * 0.5)
            depth_deadline = time.perf_counter() + depth_budget

            while time.perf_counter() < depth_deadline and not self._stopped():
                if depth == 1:
                    # Single-variable probe
                    if not free:
                        break
                    v = free[depth_probes % len(free)]
                    if v in bb_set:
                        depth_probes += 1
                        continue
                    pol = v if depth_probes % 2 == 0 else -v
                    assumptions = [pol]
                else:
                    pick = _rng.sample(free, min(depth, len(free)))
                    assumptions = [v * _rng.choice([1, -1])
                                   for v in pick]

                depth_probes += 1
                total_probes += 1
                res, model, kms = self._kissat_call(
                    optimal_dimacs, assumptions, atom)

                if res == "UNSAT":
                    clause = [-l for l in assumptions]
                    self.D.seed(clause, original=False)
                    depth_clauses += 1
                    total_clauses += 1

                    if depth == 1:
                        # Direct backbone
                        backbone = -assumptions[0]
                        self.D.chain(max_rounds=3)
                        self.D.conflicts()
                        new_bb = self.D.backbones()
                        cascade = len({abs(l) for l in new_bb}) - len(bb_set)
                        bb_set = {abs(l) for l in new_bb}
                        total_backbones += 1 + max(0, cascade)
                        free = [v for v in range(1, self.n_vars + 1)
                                if v not in bb_set]
                        optimal_dimacs = self._build_optimal_dimacs()
                        if vocal:
                            print(f"  d={depth}: backbone {backbone} "
                                  f"(+{cascade}) bb={len(new_bb)} "
                                  f"t={len(new_bb)/self.n_vars:.3f}")

                    # Batch chain every 10 clauses
                    elif depth_clauses % 10 == 0:
                        self.D.chain(max_rounds=3)
                        self.D.conflicts()
                        new_bb = self.D.backbones()
                        new_found = (len({abs(l) for l in new_bb})
                                     - len(bb_set))
                        if new_found > 0:
                            bb_set = {abs(l) for l in new_bb}
                            total_backbones += new_found
                            free = [v for v in range(1, self.n_vars + 1)
                                    if v not in bb_set]
                        optimal_dimacs = self._build_optimal_dimacs()

                elif res == "TIMEOUT":
                    depth_timeouts += 1
                    total_timeouts += 1

                elif res == "SAT":
                    depth_sat += 1

            # End-of-depth chain + conflict
            if depth_clauses > 0:
                self.D.chain(max_rounds=5)
                self.D.conflicts()
                new_bb = self.D.backbones()
                new_found = len({abs(l) for l in new_bb}) - len(bb_set)
                if new_found > 0:
                    total_backbones += new_found

            if vocal:
                bb_now = len(self.D.backbones())
                print(f"  d={depth}: {depth_clauses} clauses, "
                      f"{depth_probes} probes, "
                      f"{depth_timeouts} to, {depth_sat} sat, "
                      f"bb={bb_now} t={bb_now/self.n_vars:.3f} "
                      f"entries={self.entries}")

            # Check if solved
            status, sol = self.D.solve()
            if status in ("SAT", "UNSAT"):
                if vocal:
                    print(f"  *** {status} by dictionary ***")
                break

        ms = (time.perf_counter() - t0) * 1000
        if vocal:
            print(f"  probe total: {total_backbones} bb, "
                  f"{total_clauses} clauses, {total_probes} probes, "
                  f"{total_timeouts} to, {ms:.0f}ms")

        self._log(f"probe: bb={total_backbones} "
                  f"clauses={total_clauses} probes={total_probes} "
                  f"to={total_timeouts} {ms:.0f}ms")

        return {
            "backbones_found": total_backbones,
            "clauses_learned": total_clauses,
            "probes": total_probes,
            "timeouts": total_timeouts,
            "ms": round(ms, 1),
        }

    # ── Core: extend ──────────────────────────────────────

    def extend(self, budget: float = 5.0, atom: float = 0.1,
               max_extend: int = 20, vocal: bool = False) -> dict:
        """Grow right side of entries: discover new forced literals.

        For entry {a,b} → {a,b,c}, probe unassigned vars:
            kissat(optimal, [a,b,-d]) UNSAT → d also forced → {a,b} → {a,b,c,d}

        Growing gain makes entries more valuable. High-gain entries
        are then cheaper to promote (more right-side lits to test).

        Returns dict with extensions, new_gain, probes, ms.
        """
        t0 = time.perf_counter()
        deadline = t0 + budget

        optimal_dimacs = self._build_optimal_dimacs()
        bb_set = {abs(l) for l in self.backbones}

        # Pick entries with highest existing gain (most likely to extend)
        candidates = [(k, v) for k, v in self.D.entries.items()
                      if len(k) >= 1 and (v - k)]
        candidates.sort(key=lambda x: len(x[1]) - len(x[0]), reverse=True)
        candidates = candidates[:max_extend]

        extensions = 0
        new_gain_total = 0
        probes = 0

        for key, val in candidates:
            if time.perf_counter() > deadline:
                break

            key_list = list(key)
            assigned = {abs(l) for l in val}
            # Probe free vars
            free = [v for v in range(1, self.n_vars + 1)
                    if v not in assigned and v not in bb_set]

            new_gain = []
            for v in free[:50]:  # cap probes per entry
                if time.perf_counter() > deadline:
                    break

                for pol in [v, -v]:
                    probes += 1
                    res, _, _ = self._kissat_call(
                        optimal_dimacs, key_list + [-pol], atom)
                    if res == "UNSAT":
                        # pol is forced under key
                        new_gain.append(pol)
                        self.D.seed([-l for l in key] + [pol],
                                    original=False)
                        self.D.add(key, val | frozenset([pol]))
                        break  # found polarity, next var

            if new_gain:
                extensions += 1
                new_gain_total += len(new_gain)
                self.D.chain(max_rounds=1)
                self.D.conflicts()
                optimal_dimacs = self._build_optimal_dimacs()
                if vocal:
                    print(f"  extend: key={len(key)} +{len(new_gain)} "
                          f"new lits, total gain={len(val)-len(key)+len(new_gain)}")

        ms = (time.perf_counter() - t0) * 1000
        if vocal:
            print(f"  extend: {extensions} entries extended, "
                  f"+{new_gain_total} lits, {probes} probes, {ms:.0f}ms")
        self._log(f"extend: ext={extensions} +gain={new_gain_total} "
                  f"probes={probes} {ms:.0f}ms")

        return {
            "extensions": extensions,
            "new_gain": new_gain_total,
            "probes": probes,
            "ms": round(ms, 1),
        }

    def prove(self, budget: float = 5.0, atom: float = 0.1,
              vocal: bool = False) -> dict:
        """One round of systematic entry promotion.

        For each entry {a,b} → {a,b,c}, try removing each assumption:
            kissat(optimal, [b, -c] + D.deduce([b])) UNSAT → promote

        When a direct prove times out, adds BCP deductions as context
        to help Kissat. If the contextualized probe still times out,
        the entry is skipped.

        Returns dict with promotions, new_backbones, probes, ms.
        """
        t0 = time.perf_counter()
        deadline = t0 + budget

        optimal_dimacs = self._build_optimal_dimacs()
        bb_before = len(self.backbones)

        # Candidates: entries with key_size >= 2 that have gain
        # Sort DESCENDING — minimize longest clauses first
        # (long clauses have most room for removal, and shortened
        # clauses have the most impact on deduction power)
        candidates = [(k, v) for k, v in self.D.entries.items()
                      if len(k) >= 2 and (v - k)]
        candidates.sort(key=lambda x: len(x[0]), reverse=True)

        promotions = 0
        probes = 0
        timeouts = 0

        for key, val in candidates:
            if time.perf_counter() > deadline or self._stopped():
                break

            gain = list(val - key)
            key_list = list(key)

            for lit in key_list:
                if time.perf_counter() > deadline or self._stopped():
                    break

                smaller = [l for l in key_list if l != lit]
                if not smaller:
                    continue

                # BCP context: deduce from the remaining assumptions
                trail = self.D.deduce(frozenset(smaller))
                if self.D.contradicts(trail):
                    # smaller alone contradicts → lit was redundant AND
                    # smaller itself is unsatisfiable → learn negation
                    for g in gain:
                        self.D.seed([-l for l in smaller] + [g],
                                    original=False)
                    self.D.add(frozenset(smaller),
                               frozenset(smaller) | frozenset(gain))
                    promotions += 1
                    self.D.chain(max_rounds=1)
                    self.D.conflicts()
                    optimal_dimacs = self._build_optimal_dimacs()
                    if vocal:
                        self._log(f"promote(bcp): |key| {len(key)}→"
                                  f"{len(smaller)}")
                        print(f"  [{promotions}] |key| {len(key)}→"
                              f"{len(smaller)} gain={len(gain)} "
                              f"bb={len(self.backbones)} "
                              f"t={self.tension:.3f} (bcp)")
                    break

                # Contextualized assumptions: smaller + BCP deductions
                context = list(trail - frozenset(smaller))

                # Does smaller still force ALL gain lits?
                all_forced = True
                for g in gain:
                    if g in trail:
                        continue  # already deduced by BCP — free

                    probes += 1
                    # Try direct probe first
                    res, _, _ = self._kissat_call(
                        optimal_dimacs, smaller + [-g], atom)
                    if res == "TIMEOUT" and context:
                        # Add BCP context to help Kissat
                        probes += 1
                        res, _, _ = self._kissat_call(
                            optimal_dimacs,
                            smaller + context + [-g], atom)
                        if res == "TIMEOUT":
                            timeouts += 1
                    if res != "UNSAT":
                        all_forced = False
                        break

                if all_forced:
                    # Promotion — seed stronger clauses
                    for g in gain:
                        self.D.seed([-l for l in smaller] + [g],
                                    original=False)
                    self.D.add(frozenset(smaller),
                               frozenset(smaller) | frozenset(gain))
                    promotions += 1

                    self.D.chain(max_rounds=1)
                    self.D.conflicts()

                    # Rebuild optimal with new knowledge
                    optimal_dimacs = self._build_optimal_dimacs()

                    if vocal:
                        new_ks = len(smaller)
                        bb_now = len(self.backbones)
                        self._log(f"promote: |key| {len(key)}→{new_ks}, "
                                  f"gain={len(gain)}, bb={bb_now}")
                        print(f"  [{promotions}] |key| {len(key)}→{new_ks} "
                              f"gain={len(gain)} bb={bb_now} "
                              f"t={self.tension:.3f}")

                    break  # key is invalid after mutation, next candidate

        bb_after = len(self.backbones)
        new_bb = bb_after - bb_before
        ms = (time.perf_counter() - t0) * 1000

        if vocal:
            print(f"  prove: {promotions} promotions, {new_bb} new backbones, "
                  f"{probes} probes, {timeouts} timeouts, {ms:.0f}ms")

        self._log(f"prove: promotions={promotions} bb+={new_bb} "
                  f"probes={probes} timeouts={timeouts} {ms:.0f}ms")

        return {
            "promotions": promotions,
            "new_backbones": new_bb,
            "timeouts": timeouts,
            "probes": probes,
            "ms": round(ms, 1),
        }

    # ── Core: solve ───────────────────────────────────────

    def solve(self, budget: float = 10.0) -> SATResult:
        """Run Kissat on current optimal formula."""
        t0 = time.perf_counter()

        # Check dictionary first
        status, sol = self.D.solve()
        if status in ("SAT", "UNSAT"):
            self.result = self._make_result(status, sol, t0)
            return self.result

        optimal_dimacs = self._build_optimal_dimacs()
        res, model, kms = self._kissat_call(optimal_dimacs, [], budget)

        self._log(f"solve: {res} in {kms:.0f}ms")
        self.result = self._make_result(res, model, t0)
        return self.result

    # ── Core: run (automated loop) ────────────────────────

    def run(self, budget: float = 60.0, max_rounds: int = 50,
            atom: float = 0.2, vocal: bool = False) -> SATResult:
        """Probe → prove → solve loop until done.

        Each round:
          1. probe: discover backbones via failed literal probing (parallel with Kissat)
          2. prove: promote entries using new backbone knowledge
          3. Kissat: try to solve the enriched optimal formula
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        t0 = time.perf_counter()

        # Check if already solved by dictionary
        status, sol = self.D.solve()
        if status in ("SAT", "UNSAT"):
            self.result = self._make_result(status, sol, t0)
            return self.result

        # Fast path: try Kissat direct first (1s cap)
        kissat_budget = min(1.0, budget * 0.1)
        optimal_snap = self._build_optimal_dimacs()
        res, model, kms = self._kissat_call(optimal_snap, [], kissat_budget)
        if res in ("SAT", "UNSAT"):
            self._log(f"run: {res} by kissat direct in {kms:.0f}ms")
            if vocal:
                print(f"  Kissat direct: {res} in {kms:.0f}ms")
            self.result = self._make_result(res, model, t0)
            return self.result

        # Shared cancel flag — probe checks this to bail early
        self._cancel = False

        for rnd in range(max_rounds):
            remaining = budget - (time.perf_counter() - t0)
            if remaining < 2.0:
                break

            # Phase 1: probe + Kissat in parallel
            # Probe respects self._cancel; Kissat is a subprocess
            # (killed by timeout naturally)
            probe_budget = min(remaining * 0.5, 20.0)
            solve_budget = min(remaining * 0.5, 15.0)
            optimal_snap = self._build_optimal_dimacs()

            pool = ThreadPoolExecutor(max_workers=2)
            probe_f = pool.submit(self.probe, budget=probe_budget,
                                  atom=atom, vocal=vocal)
            kissat_f = pool.submit(self._kissat_call, optimal_snap,
                                   [], solve_budget)

            solved = False
            for f in as_completed([probe_f, kissat_f]):
                if f is kissat_f:
                    res, model, kms = f.result()
                    if res in ("SAT", "UNSAT"):
                        self._cancel = True  # signal probe to stop
                        self._log(f"run R{rnd}: {res} by kissat "
                                  f"in {kms:.0f}ms")
                        if vocal:
                            print(f"  R{rnd}: {res} by Kissat "
                                  f"in {kms:.0f}ms")
                        self.result = self._make_result(
                            res, model, t0)
                        solved = True
                        break

            pool.shutdown(wait=False)
            if solved:
                return self.result

            pb = probe_f.result()

            # Check dictionary after probe
            status, sol = self.D.solve()
            if status in ("SAT", "UNSAT"):
                self._log(f"run R{rnd}: {status} by dictionary "
                          f"after probe")
                if vocal:
                    print(f"  R{rnd}: {status} by dictionary collapse")
                self.result = self._make_result(status, sol, t0)
                return self.result

            # Phase 2: if probes found backbones, prove can now promote
            if pb["backbones_found"] > 0:
                remaining = budget - (time.perf_counter() - t0)
                prove_budget = min(remaining * 0.3, 5.0)
                if prove_budget > 1.0:
                    pr = self.prove(budget=prove_budget, atom=atom,
                                    vocal=vocal)
                    status, sol = self.D.solve()
                    if status in ("SAT", "UNSAT"):
                        self.result = self._make_result(status, sol, t0)
                        return self.result

            if vocal:
                print(f"  R{rnd}: bb={len(self.backbones)} "
                      f"t={self.tension:.3f} "
                      f"entries={self.entries} "
                      f"probe={pb['backbones_found']}bb "
                      f"{pb['timeouts']}to")

            # No progress check
            progress = (pb["backbones_found"] > 0
                        or pb.get("clauses_learned", 0) > 0)
            if not progress and pb["timeouts"] == 0:
                self._log(f"run: stalled at R{rnd}")
                if vocal:
                    print(f"  stalled — no progress")
                break

        # Budget or rounds exhausted
        total_ms = (time.perf_counter() - t0) * 1000
        self._log(f"run: TIMEOUT after {total_ms:.0f}ms")
        self.result = SATResult(
            result="TIMEOUT", budget=budget,
            total_ms=total_ms, n_vars=self.n_vars, n_clauses=self.n_clauses,
            tension=self.tension, entries=self.entries,
            backbones=len(self.backbones),
        )
        return self.result

    # ── Helpers ───────────────────────────────────────────

    def _build_optimal_dimacs(self) -> str:
        """Export full dictionary as DIMACS — uncapped."""
        clauses = list(self.D.clauses)

        # Backbone units
        for lit in self.D.backbones():
            clauses.append([lit])

        # All dictionary entries as clauses (no key_size cap)
        seen = {frozenset(c) for c in clauses}
        for key, val in self.D.entries.items():
            if len(key) < 1:
                continue
            neg_key = [-l for l in key]
            for g in val - key:
                cl = neg_key + [g]
                fs = frozenset(cl)
                if fs not in seen:
                    clauses.append(cl)
                    seen.add(fs)

        lines = [f"p cnf {self.n_vars} {len(clauses)}"]
        for c in clauses:
            lines.append(" ".join(str(l) for l in c) + " 0")
        return "\n".join(lines) + "\n"

    def _kissat_call(self, dimacs: str, assumptions: list[int],
                     budget: float) -> tuple[str, list | None, float]:
        """Run Kissat subprocess."""
        import subprocess
        import tempfile

        # Prepend assumptions as unit clauses
        if assumptions:
            lines = dimacs.splitlines()
            new_lines = []
            for line in lines:
                if line.startswith("p cnf"):
                    parts = line.split()
                    orig_c = int(parts[3])
                    new_lines.append(
                        f"p cnf {self.n_vars} {orig_c + len(assumptions)}")
                else:
                    new_lines.append(line)
            hdr = next(i for i, l in enumerate(new_lines)
                       if l.startswith("p cnf"))
            for lit in assumptions:
                new_lines.insert(hdr + 1, f"{lit} 0")
            dimacs = "\n".join(new_lines) + "\n"

        fd, path = tempfile.mkstemp(suffix=".cnf")
        t0 = time.perf_counter()
        try:
            with os.fdopen(fd, "w") as f:
                f.write(dimacs)

            if budget < 1.0:
                cmd = [self._kissat_path, path, "--quiet"]
                timeout = budget + 0.2
            else:
                cmd = [self._kissat_path, path,
                       f"--time={max(1, int(budget))}", "--quiet"]
                timeout = budget + 5

            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout)
            ms = (time.perf_counter() - t0) * 1000

            result = "TIMEOUT"
            model = None

            if proc.returncode == 10:
                result = "SAT"
            elif proc.returncode == 20:
                result = "UNSAT"

            if result == "SAT":
                model = []
                for line in proc.stdout.splitlines():
                    if line.startswith("v "):
                        for tok in line[2:].split():
                            val = int(tok)
                            if val != 0:
                                model.append(val)

            return result, model, ms

        except subprocess.TimeoutExpired:
            return "TIMEOUT", None, (time.perf_counter() - t0) * 1000
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _make_result(self, status: str, assignment, t0) -> SATResult:
        total_ms = (time.perf_counter() - t0) * 1000
        bb = self.backbones
        proof = None
        if status == "UNSAT":
            proof = SATProof(
                backbones=bb, tension=self.tension,
                entries=self.entries, method="session",
            )
        return SATResult(
            result=status,
            solved_by="session",
            total_ms=total_ms,
            n_vars=self.n_vars, n_clauses=self.n_clauses,
            assignment=sorted(assignment, key=abs) if assignment else None,
            proof=proof,
            tension=self.tension,
            entries=self.entries,
            backbones=len(bb),
        )

    def _log(self, msg: str):
        self.log.append(f"[{time.perf_counter():.3f}] {msg}")

    def __repr__(self):
        return (f"SATSession({self.n_vars}v, {self.n_clauses}c, "
                f"entries={self.entries}, bb={len(self.backbones)}, "
                f"t={self.tension:.3f}, status={self.status})")


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
        worker_count=r.get("workers_dispatched", r.get("workers_total", r.get("worker_count", 0))),
        ui=r.get("ui", ""),
        audit=r.get("audit"),
        n_vars=n_vars or r.get("n_vars", 0),
        n_clauses=n_clauses or r.get("n_clauses", 0),
    )
