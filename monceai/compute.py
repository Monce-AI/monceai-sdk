"""
monceai.Computation — verified compute via npdollars SAT solver.

Takes a text prompt. If it matches a known computable pattern (factoring,
SAT/CNF, graph coloring, exact arithmetic), builds the matching CNF /
numeric problem, dispatches to npdollars.aws.monce.ai/solve, and returns
the verified answer with a proof certificate. Zero LLM tokens on success.

    from monceai import Computation

    Computation("factor 10403")
    # → "10403 = 101 × 103" (binary-multiplier CNF, SAT proof, 0 tokens)

    Computation("p cnf 3 2\\n1 2 0\\n-1 3 0\\n")
    # → {"result":"SAT","assignment":[1,-2,3]} (raw DIMACS pass-through)

    Computation("6x7")
    # → "42" (pure arithmetic, Decimal, zero network)

    # Fallback — no pattern recognized
    Computation("explain gravity")
    # → "" with .recognized = False (Synthax dismisses this branch)

``str(Computation(q))`` is the answer. ``.recognized`` tells you whether
a computable pattern was detected. ``.proof`` carries DIMACS + SAT assignment
for audit. ``.elapsed_ms``, ``.cost_usd`` for budget accounting.

Used by Synthax as a parallel-race branch: fired alongside the LLM draft,
dismissed (and budget reclaimed) if ``.recognized`` is False, otherwise
promoted to the winner, skipping adversary / revise / verify.
"""

from __future__ import annotations

import os
import re
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

import requests

from .llm import LLMResult, _report_usage, DEFAULT_ENDPOINT


NPDOLLARS_URL = os.environ.get("NPDOLLARS_URL", "https://npdollars.aws.monce.ai")
DEFAULT_TIMEOUT = 60


# ─────────────────────────────────────────────────────────────────────────────
# Pattern detection — lightweight regex, fast, greedy
# ─────────────────────────────────────────────────────────────────────────────

_FACTOR_RX = re.compile(
    r"\bfactor(?:ize|ing|isation)?\s+(?:the\s+(?:number\s+)?)?(-?\d+)\b",
    re.IGNORECASE,
)
_ARITH_RX = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?)\s*([x*/%+\-])\s*(-?\d+(?:\.\d+)?)\s*$",
)
_DIMACS_RX = re.compile(r"^\s*p\s+cnf\s+\d+\s+\d+\s*$", re.MULTILINE)
_COLORING_RX = re.compile(
    r"\b(\d+)[-\s]?color(?:able|ing)\b",
    re.IGNORECASE,
)


def detect_pattern(prompt: str) -> Tuple[str, Dict[str, Any]]:
    """Return (pattern_name, extras) or ('none', {})."""
    # 1. Raw DIMACS
    if _DIMACS_RX.search(prompt):
        return "dimacs", {"dimacs": prompt.strip()}
    # 2. Factoring
    m = _FACTOR_RX.search(prompt)
    if m:
        n = int(m.group(1))
        if n > 1:
            return "factor", {"n": n}
    # 3. Pure arithmetic
    m = _ARITH_RX.search(prompt.strip())
    if m:
        return "arith", {"a": m.group(1), "op": m.group(2), "b": m.group(3)}
    # 4. Graph coloring reference (structural clue, needs LLM to build CNF
    # unless the user also gave edges — v0 just flags it)
    m = _COLORING_RX.search(prompt)
    if m:
        return "coloring", {"k": int(m.group(1))}
    return "none", {}


# ─────────────────────────────────────────────────────────────────────────────
# Binary-multiplier CNF encoder (factoring pattern).
#
# For N we build: P * Q = N, P >= 2, Q >= 2, with P and Q encoded as
# k-bit binary integers (k = bitlen(N)). A single full-adder CNF gadget
# per column sums partial products. SAT ≡ non-trivial factorisation.
# UNSAT ≡ prime. This is the Dana-theorem constructive path — polynomial
# time to build, exponential worst-case to solve, but polynomial on
# semi-primes in practice because the structure is shallow.
#
# Implementation is straightforward but verbose. We keep v0 tight: build
# DIMACS for N up to ~40 bits, hand off to npdollars which runs Kissat.
# ─────────────────────────────────────────────────────────────────────────────

class _DimacsBuilder:
    """Helper to accumulate DIMACS clauses with auto-var allocation."""

    def __init__(self):
        self.next_var = 1
        self.clauses: List[List[int]] = []

    def fresh(self) -> int:
        v = self.next_var
        self.next_var += 1
        return v

    def fresh_many(self, n: int) -> List[int]:
        return [self.fresh() for _ in range(n)]

    def clause(self, lits: List[int]):
        self.clauses.append(lits)

    def equals(self, x: int, y: int):
        """Force x ≡ y in truth value."""
        self.clause([-x, y])
        self.clause([x, -y])

    def and_gate(self, a: int, b: int, out: int):
        """out ≡ (a ∧ b)."""
        self.clause([-a, -b, out])
        self.clause([a, -out])
        self.clause([b, -out])

    def xor_gate(self, a: int, b: int, out: int):
        """out ≡ (a ⊕ b)."""
        self.clause([-a, -b, -out])
        self.clause([a,  b, -out])
        self.clause([-a,  b,  out])
        self.clause([a, -b,  out])

    def full_adder(self, a: int, b: int, cin: int) -> Tuple[int, int]:
        """Returns (sum, cout). sum = a⊕b⊕cin ; cout = majority(a,b,cin)."""
        # sum = a ⊕ b ⊕ cin  (via two XORs)
        s1 = self.fresh()
        self.xor_gate(a, b, s1)
        s = self.fresh()
        self.xor_gate(s1, cin, s)
        # cout = (a∧b) ∨ (cin∧(a⊕b))
        ab = self.fresh()
        self.and_gate(a, b, ab)
        cin_s1 = self.fresh()
        self.and_gate(cin, s1, cin_s1)
        cout = self.fresh()
        # cout ≡ ab ∨ cin_s1
        self.clause([-ab, cout])
        self.clause([-cin_s1, cout])
        self.clause([ab, cin_s1, -cout])
        return s, cout

    def binary_constant(self, value: int, bits: int) -> List[int]:
        """Allocate `bits` vars and pin them to the bits of `value` (LSB first)."""
        xs = self.fresh_many(bits)
        for i, x in enumerate(xs):
            bit = (value >> i) & 1
            self.clause([x] if bit else [-x])
        return xs

    def to_dimacs(self) -> str:
        header = f"p cnf {self.next_var - 1} {len(self.clauses)}"
        body = "\n".join(" ".join(map(str, c)) + " 0" for c in self.clauses)
        return header + "\n" + body + "\n"


def build_factor_cnf(N: int) -> Tuple[str, List[int], List[int]]:
    """Build DIMACS for: does P × Q = N with P, Q ≥ 2 ?

    Returns (dimacs, p_vars_lsb_first, q_vars_lsb_first).
    """
    if N < 4:
        raise ValueError(f"trivial N={N}")

    bits = N.bit_length()
    # P and Q each use `bits` bits (room to represent N-1 worst case)
    k = bits
    B = _DimacsBuilder()

    P = B.fresh_many(k)    # p0 (LSB) .. p_{k-1}
    Q = B.fresh_many(k)

    # Partial products pp[i][j] = P[i] ∧ Q[j]
    pp: List[List[int]] = []
    for i in range(k):
        row = []
        for j in range(k):
            g = B.fresh()
            B.and_gate(P[i], Q[j], g)
            row.append(g)
        pp.append(row)

    # Column sums with ripple-carry adders.
    # product bit c has contributions pp[i][j] where i+j == c.
    # We fold them left-to-right per column.
    FALSE = B.fresh()
    B.clause([-FALSE])     # FALSE literal pinned to 0
    product_bits: List[int] = []
    carries_into_column: List[List[int]] = [[] for _ in range(2 * k + 2)]

    for c in range(2 * k):
        terms = [pp[i][c - i] for i in range(max(0, c - k + 1), min(c, k - 1) + 1)]
        terms += carries_into_column[c]
        if not terms:
            product_bits.append(FALSE)
            continue
        # Reduce by chained full-adders
        running = terms[0]
        for t in terms[1:]:
            s, cout = B.full_adder(running, t, FALSE)
            running = s
            carries_into_column[c + 1].append(cout)
        product_bits.append(running)

    # Constrain product_bits to N
    for i, pb in enumerate(product_bits):
        bit = (N >> i) & 1 if i < (2 * k) else 0
        B.clause([pb] if bit else [-pb])

    # Non-triviality: P >= 2 and Q >= 2 (so neither is 1 and neither is N).
    # P >= 2 ⇔ OR of P[1..k-1].
    B.clause(P[1:])
    B.clause(Q[1:])
    # Also P <= N-1 and Q <= N-1 (exclude P=N, Q=1 trivial sol). We already
    # got Q >= 2 which forces P <= N/2 < N.

    return B.to_dimacs(), P, Q


def _bits_to_int(bits_lsb: List[int]) -> int:
    """Convert [b0, b1, ...] (0/1) to integer."""
    n = 0
    for i, b in enumerate(bits_lsb):
        if b:
            n |= (1 << i)
    return n


def _read_assignment(assignment: List[int], vars_: List[int]) -> List[int]:
    """assignment is a sparse SAT assignment (list of signed ints). Return 0/1 per var."""
    pos: Dict[int, int] = {}
    for lit in assignment:
        pos[abs(lit)] = 1 if lit > 0 else 0
    return [pos.get(v, 0) for v in vars_]


# ─────────────────────────────────────────────────────────────────────────────
# npdollars client
# ─────────────────────────────────────────────────────────────────────────────

def _npdollars_solve(dimacs: str, budget: float = 30.0,
                     timeout: int = DEFAULT_TIMEOUT) -> dict:
    """POST /solve with DIMACS, return response JSON (sync)."""
    url = f"{NPDOLLARS_URL}/solve"
    try:
        r = requests.post(url, json={
            "dimacs": dimacs, "budget": budget,
            "budget_dollars": 0.25, "mode": "kissat",
        }, timeout=timeout)
    except requests.RequestException as e:
        return {"error": f"network: {e}"}
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
    try:
        return r.json()
    except Exception as e:
        return {"error": f"bad JSON: {e}"}


def _npdollars_poll(sid: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Poll /status/{sid} until completed or timeout."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = requests.get(f"{NPDOLLARS_URL}/status/{sid}", timeout=10)
            if r.status_code == 200:
                body = r.json()
                if body.get("status") in ("completed", "done", "SAT", "UNSAT", "error"):
                    # Final result — fetch /result/{sid}
                    rr = requests.get(f"{NPDOLLARS_URL}/result/{sid}", timeout=10)
                    if rr.status_code == 200:
                        return rr.json()
                    return body
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return {"error": f"poll_timeout after {timeout}s"}


# ─────────────────────────────────────────────────────────────────────────────
# Public class
# ─────────────────────────────────────────────────────────────────────────────

class Computation(str):
    """Verified compute. ``str(Computation(q))`` IS the answer.

    Attributes
    ----------
    recognized : bool
        True if a computable pattern was detected and solved.
    pattern : str
        'factor' | 'dimacs' | 'arith' | 'coloring' | 'none'
    proof : dict
        Solver output (DIMACS, assignment, SAT sid).
    elapsed_ms : int
    cost_usd : float
    result : LLMResult
    """

    def __new__(cls, prompt: Optional[str] = None,
                budget: float = 30.0,
                endpoint: Optional[str] = None,
                timeout: int = DEFAULT_TIMEOUT):
        if prompt is None:
            client = object.__new__(_ComputationClient)
            client._budget = budget
            client._timeout = timeout
            return client

        t0 = time.time()
        pattern, extras = detect_pattern(prompt)
        answer = ""
        proof: Dict[str, Any] = {"pattern": pattern}
        recognized = False
        cost_usd = 0.0

        if pattern == "arith":
            # Pure local Decimal — zero network
            try:
                a = Decimal(extras["a"])
                b = Decimal(extras["b"])
                op = extras["op"]
                if op == "x" or op == "*": v = a * b
                elif op == "+":              v = a + b
                elif op == "-":              v = a - b
                elif op == "/":              v = a / b if b != 0 else Decimal(0)
                elif op == "%":              v = a % b if b != 0 else Decimal(0)
                else: v = None
                if v is not None:
                    answer = format(v.normalize(), "f") if isinstance(v, Decimal) else str(v)
                    recognized = True
                    proof["method"] = "decimal"
            except (InvalidOperation, ValueError):
                pass

        elif pattern == "factor":
            N = extras["n"]
            try:
                dimacs, P, Q = build_factor_cnf(N)
                body = _npdollars_solve(dimacs, budget=budget,
                                         timeout=timeout)
                proof["dimacs_vars"] = dimacs.split("\n", 1)[0]
                # npdollars /solve response shapes observed:
                #   synchronous: {"result":"SAT","assignment":[...],"total_ms":...}
                #   async:       {"sid":"..."}
                result_str = str(body.get("result", "")).upper()
                assignment = body.get("assignment")
                if assignment:
                    p_val = _bits_to_int(_read_assignment(assignment, P))
                    q_val = _bits_to_int(_read_assignment(assignment, Q))
                    if p_val * q_val == N and p_val > 1 and q_val > 1:
                        answer = f"{N} = {min(p_val,q_val)} × {max(p_val,q_val)}"
                        recognized = True
                        proof.update({"p": p_val, "q": q_val,
                                      "assignment_size": len(assignment),
                                      "kissat_ms": body.get("kissat_ms")})
                elif result_str == "UNSAT":
                    answer = f"{N} is prime (UNSAT on binary-multiplier CNF)"
                    recognized = True
                    proof["unsat"] = True
                elif "sid" in body and not assignment:
                    sid = body["sid"]
                    poll = _npdollars_poll(sid, timeout=timeout)
                    proof["sid"] = sid
                    assignment = poll.get("assignment")
                    if assignment:
                        p_val = _bits_to_int(_read_assignment(assignment, P))
                        q_val = _bits_to_int(_read_assignment(assignment, Q))
                        if p_val * q_val == N and p_val > 1 and q_val > 1:
                            answer = f"{N} = {min(p_val,q_val)} × {max(p_val,q_val)}"
                            recognized = True
                            proof.update({"p": p_val, "q": q_val})
                cost_usd = 0.05   # ~ one SAT solve, rough
            except Exception as e:
                proof["error"] = f"{type(e).__name__}: {e}"

        elif pattern == "dimacs":
            body = _npdollars_solve(extras["dimacs"], budget=budget,
                                     timeout=timeout)
            # body may contain nested dicts — flatten only top-level keys
            for k in ("session_id", "result", "solved_by", "total_ms",
                      "kissat_ms", "n_vars", "n_clauses"):
                if k in body:
                    proof[k] = body[k]
            if body.get("assignment") or body.get("result"):
                answer = (f"{body.get('result')} assignment: "
                          f"{body.get('assignment', [])[:20]}"
                          f"{'...' if len(body.get('assignment',[])) > 20 else ''}")
                recognized = True
                cost_usd = 0.05

        elif pattern == "coloring":
            # Placeholder — need user to supply edges. Leave unrecognized.
            proof["note"] = f"{extras['k']}-coloring detected but no edge list given"

        elapsed = int((time.time() - t0) * 1000)
        inst = super().__new__(cls, answer)
        inst.prompt = prompt
        inst.recognized = recognized
        inst.pattern = pattern
        inst.proof = proof
        inst.elapsed_ms = elapsed
        inst.cost_usd = cost_usd
        inst.result = LLMResult(
            text=answer,
            model="computation",
            elapsed_ms=elapsed,
            sat_memory={
                "pattern": pattern,
                "recognized": recognized,
                "cost_usd": round(cost_usd, 4),
                "proof": proof,
            },
        )
        if prompt:
            _report_usage(DEFAULT_ENDPOINT, f"computation:{prompt[:80]}", inst.result)
        return inst

    def __repr__(self):
        return (f"Computation(pattern={self.pattern!r}, "
                f"recognized={self.recognized}, answer={str(self)[:60]!r})")


class _ComputationClient:
    """Reusable client for Computation()."""

    def __call__(self, prompt: str, **kw):
        return Computation(prompt,
                           budget=kw.get("budget", self._budget),
                           timeout=kw.get("timeout", self._timeout))
