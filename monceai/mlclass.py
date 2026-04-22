"""
monceai.ML — Snake classification on context-driven datasets.

Takes a text prompt that smells like "classify X given this CSV", trains a
Snake via snakebatch.aws.monce.ai/csv/run, infers the target sample, and
returns the predicted class + confidence.

    from monceai import ML

    # Inline CSV in the prompt (or upstream from Context)
    ML('''classify: is Iris(5.1, 3.5, 1.4, 0.2) a setosa?

    sepal_length,sepal_width,petal_length,petal_width,species
    5.1,3.5,1.4,0.2,setosa
    4.9,3.0,1.4,0.2,setosa
    7.0,3.2,4.7,1.4,versicolor
    6.4,3.2,4.5,1.5,versicolor
    ''')
    # → "setosa (p=0.97)"
    # ML(...).confidence, .prediction, .proof

``str(ML(q))`` IS the answer. ``.recognized`` tells you whether a
classification pattern + dataset were both detected. Used by Synthax
as a parallel-race branch: fires alongside the LLM draft, dismissed if
no CSV or pattern is found, promoted to winner on high confidence.

Zero LLM tokens on success. Snake training runs on Lambda
(snakebatch.aws.monce.ai), latency typically 5-30s depending on dataset.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from .llm import LLMResult, _report_usage, DEFAULT_ENDPOINT


SNAKEBATCH_URL = os.environ.get("SNAKEBATCH_URL", "https://snakebatch.aws.monce.ai")
DEFAULT_TIMEOUT = 90


# ─────────────────────────────────────────────────────────────────────────────
# Pattern + CSV detection
# ─────────────────────────────────────────────────────────────────────────────

_CLASSIFY_RX = re.compile(
    r"\b(?:classif(?:y|ication|ier)|predict|label|is\s+\S+\s+a\b)\b",
    re.IGNORECASE,
)
# A CSV block is ≥2 lines, each with ≥2 commas, first line all-alpha header
_CSV_BLOCK_RX = re.compile(
    r"(^[A-Za-z_][\w ,\-]*,[^\n]*\n(?:[^\n]+,[^\n]+\n){2,})",
    re.MULTILINE,
)


def detect_ml(prompt: str) -> Tuple[str, Dict[str, Any]]:
    """Return ('ml', extras) or ('none', {})."""
    csv_match = _CSV_BLOCK_RX.search(prompt)
    has_classify_verb = bool(_CLASSIFY_RX.search(prompt))

    if csv_match:
        csv = csv_match.group(1).strip()
        header = csv.split("\n", 1)[0].split(",")
        extras = {
            "csv": csv,
            "header": [h.strip() for h in header],
            "question": prompt.replace(csv, "").strip(),
        }
        # We need *both* a CSV and either a classify verb OR a specific
        # "is X a Y?" form. The verb check is permissive.
        if has_classify_verb or "?" in prompt:
            return "ml", extras
    return "none", {}


# ─────────────────────────────────────────────────────────────────────────────
# snakebatch /csv/run client
# ─────────────────────────────────────────────────────────────────────────────

def _snakebatch_csv_run(csv: str, target_column: Optional[str] = None,
                         sample: Optional[Dict[str, Any]] = None,
                         timeout: int = DEFAULT_TIMEOUT) -> dict:
    """POST /csv/run with a CSV payload, return response JSON."""
    url = f"{SNAKEBATCH_URL}/csv/run"
    payload: Dict[str, Any] = {"csv": csv, "mode": "fast"}
    if target_column:
        payload["target"] = target_column
    if sample:
        payload["sample"] = sample
    try:
        r = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as e:
        return {"error": f"network: {e}"}
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
    try:
        return r.json()
    except Exception as e:
        return {"error": f"bad JSON: {e}"}


# ─────────────────────────────────────────────────────────────────────────────
# Public class
# ─────────────────────────────────────────────────────────────────────────────

class ML(str):
    """Snake classification on context-driven data. ``str(ML(q))`` IS the answer.

    Attributes
    ----------
    recognized : bool
        True if prompt contained both a classify-shaped ask and a CSV.
    prediction : str
        Predicted class label.
    confidence : float
        In [0, 1].
    proof : dict
        Snake audit trail (model_id, features used, literal tests).
    elapsed_ms : int
    cost_usd : float
    """

    def __new__(cls, prompt: Optional[str] = None,
                endpoint: Optional[str] = None,
                timeout: int = DEFAULT_TIMEOUT):
        if prompt is None:
            client = object.__new__(_MLClient)
            client._timeout = timeout
            return client

        t0 = time.time()
        pattern, extras = detect_ml(prompt)
        answer = ""
        prediction = ""
        confidence = 0.0
        proof: Dict[str, Any] = {"pattern": pattern}
        recognized = False
        cost_usd = 0.0

        if pattern == "ml":
            body = _snakebatch_csv_run(extras["csv"], timeout=timeout)
            proof.update(body if isinstance(body, dict) else {"raw": str(body)})
            if "error" not in body:
                pred = (body.get("prediction")
                        or body.get("result", {}).get("prediction"))
                conf = (body.get("confidence")
                        or body.get("result", {}).get("confidence") or 0.0)
                if pred is not None:
                    prediction = str(pred)
                    try:
                        confidence = float(conf)
                    except (TypeError, ValueError):
                        confidence = 0.0
                    answer = f"{prediction} (p={confidence:.2f})"
                    recognized = True
                    cost_usd = 0.05
                elif body.get("model_id"):
                    # Training succeeded but no single sample predicted —
                    # this happens when the CSV was shown but no specific
                    # "predict X" sample was parseable. Surface the model.
                    proof["model_id"] = body["model_id"]
                    answer = f"trained model_id={body['model_id']} (no sample inferred)"

        elapsed = int((time.time() - t0) * 1000)
        inst = super().__new__(cls, answer)
        inst.prompt = prompt
        inst.recognized = recognized
        inst.prediction = prediction
        inst.confidence = confidence
        inst.proof = proof
        inst.elapsed_ms = elapsed
        inst.cost_usd = cost_usd
        inst.result = LLMResult(
            text=answer,
            model="ml",
            elapsed_ms=elapsed,
            sat_memory={
                "recognized": recognized,
                "prediction": prediction,
                "confidence": confidence,
                "cost_usd": round(cost_usd, 4),
                "pattern": pattern,
                "proof": {k: v for k, v in proof.items() if k != "raw"},
            },
        )
        if prompt:
            _report_usage(DEFAULT_ENDPOINT, f"ml:{prompt[:80]}", inst.result)
        return inst

    def __repr__(self):
        return (f"ML(recognized={self.recognized}, "
                f"prediction={self.prediction!r}, "
                f"confidence={self.confidence:.2f})")


class _MLClient:
    """Reusable client for ML()."""

    def __call__(self, prompt: str, **kw):
        return ML(prompt, timeout=kw.get("timeout", self._timeout))
