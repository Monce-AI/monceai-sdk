"""
monceai.Classifier — fast, progressive N-label triage on any document pack.

Design
------
- **Simple constructor.** Feed labels, rules, and a bag of context: documents
  (paths / bytes / (name, bytes)), free text, and arbitrary side arrays
  (emails, prior notes, whatever you have). That's it.

- **Fires immediately.** The constructor returns in microseconds. A background
  thread runs the pipeline.

- **Progressive getter.** ``.preview`` (or ``.fast``) returns a Haiku-level
  verdict the instant Phase 1 finishes (typically 3-8s). ``.label`` and the
  rest of the strict verdict block on Phase 2 (Sonnet), capped at the global
  ``timeout`` (default 30s).

- **Always answers.** If Phase 2 doesn't finish in time, the Phase 1 verdict
  is promoted to ``.label`` and marked ``tentative=True``. No exception, no
  hang.

Usage
-----
    from monceai import Classifier

    clf = Classifier(
        labels=["order", "quote", "informative"],
        rules="order=pipeline-ready, quote=needs estimator, informative=else",
        documents=["email_po.pdf", ("drawing.png", png_bytes)],
        text="Peux-tu me traiter ca comme d'hab?",
        factory_id=4,
    )

    clf.preview       # <- fast Haiku label, ~5s
    clf.label         # <- reliable Sonnet label, ≤30s (or Haiku if timeout)
    clf.confidence
    clf.evidence
    clf.rationale
    clf.runner_up
    clf.tentative     # True if Phase 2 timed out

    # batch mode
    verdicts = Classifier.batch(
        [{"documents": [p]} for p in paths],
        labels=[...], rules="...",
        parallel=3,
    )
"""

from __future__ import annotations

import json as _json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterable, Optional, Union

from .llm import LLM, VLM, _guess_content_type, _chat


_VLM_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff",
             ".gif", ".bmp", ".pdf"}

DocLike = Union[str, bytes, "os.PathLike", tuple]


# ─────────────────────────────────────────────────────────────────────────────
# Document normalization
# ─────────────────────────────────────────────────────────────────────────────

def _normalize(doc: DocLike) -> tuple[str, bytes, str]:
    """(filename, data, kind) where kind ∈ {"image", "text"}."""
    if isinstance(doc, tuple) and len(doc) == 2:
        name, data = doc
        if isinstance(data, (bytes, bytearray)):
            ext = Path(name).suffix.lower()
            return name, bytes(data), "image" if ext in _VLM_EXTS else "text"
        return name, str(data).encode("utf-8", "replace"), "text"
    if isinstance(doc, (bytes, bytearray)):
        return "blob", bytes(doc), "image"
    if isinstance(doc, (str, os.PathLike)):
        p = Path(str(doc))
        if p.exists() and p.is_file():
            ext = p.suffix.lower()
            if ext in _VLM_EXTS:
                return p.name, p.read_bytes(), "image"
            try:
                return p.name, p.read_text(encoding="utf-8",
                                           errors="replace").encode("utf-8"), "text"
            except Exception:
                return p.name, p.read_bytes(), "text"
        # Treat as inline text
        return "inline.txt", str(doc).encode("utf-8", "replace"), "text"
    return "blob", str(doc).encode("utf-8", "replace"), "text"


# ─────────────────────────────────────────────────────────────────────────────
# VLM extraction per document — short, generic, fast
# ─────────────────────────────────────────────────────────────────────────────

_EXTRACT_PROMPT = (
    "Summarize this document in 5-10 short bullet points for triage. "
    "Include: document type, key entities (buyer/seller/parties), "
    "any reference numbers, presence of structured tables/line items, "
    "presence of drawings/schemas, and the overall intent. "
    "Return plain text — no JSON, no markdown fences."
)


def _pdf_first_page_png(data: bytes, dpi: int = 150) -> Optional[bytes]:
    """Rasterize the first page of a PDF to PNG. Returns None if fitz
    isn't installed or rendering fails."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return None
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        if doc.page_count == 0:
            return None
        page = doc.load_page(0)
        zoom = dpi / 72
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        png = pix.tobytes("png")
        doc.close()
        return png
    except Exception:
        return None


def _extract_one(name: str, data: bytes, kind: str,
                 factory_id: int, timeout: int) -> str:
    try:
        if kind == "image":
            # PDFs: the monceapp /v1/chat gateway doesn't forward PDF bytes
            # to Bedrock (its MEDIA_TYPES map is image-only). Render page 1
            # client-side to PNG so the VLM path works uniformly.
            ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
            if ext == "pdf":
                png = _pdf_first_page_png(data)
                if png is not None:
                    data = png
                    name = name.rsplit(".", 1)[0] + ".png"

            try:
                r = VLM(_EXTRACT_PROMPT, image=data,
                        image_type=_guess_content_type(name),
                        factory_id=factory_id, json=False, timeout=timeout)
                text = getattr(r, "text", "") or ""
            except Exception as e:
                text = f"VLM error: {e}"

            if "Model unavailable" in text or not text.strip():
                # Last-resort fallback via multipart upload
                try:
                    r2 = _chat(text=_EXTRACT_PROMPT, model="charles-json",
                               factory_id=factory_id, timeout=timeout,
                               file=data, filename=name, as_json=False)
                    text = getattr(r2, "text", "") or text
                except Exception:
                    pass

            return f"--- {name} ---\n{text[:1500]}"
        # text
        txt = data.decode("utf-8", "replace")[:1500]
        return f"--- {name} ---\n{txt}"
    except Exception as e:
        return f"--- {name} ---\n[extract error: {e}]"


# ─────────────────────────────────────────────────────────────────────────────
# Phase prompts
# ─────────────────────────────────────────────────────────────────────────────

def _build_context(labels, rules, text, extracts, extras, factory_id):
    label_list = ", ".join(f'"{l}"' for l in labels)
    parts = [
        f"Classification task. factory_id={factory_id}.",
        f"Labels (mutually exclusive): {label_list}",
        f"Rules:\n{rules}" if rules else "",
    ]
    if text:
        parts.append(f"[TEXT]\n{text[:4000]}")
    if extracts:
        parts.append("[DOCUMENTS]\n" + "\n\n".join(extracts))
    for k, v in (extras or {}).items():
        if v is None:
            continue
        if isinstance(v, (list, tuple)):
            payload = "\n".join(str(x)[:400] for x in v)
        elif isinstance(v, dict):
            payload = _json.dumps(v, ensure_ascii=False)[:2000]
        else:
            payload = str(v)[:2000]
        parts.append(f"[{k.upper()}]\n{payload}")
    return "\n\n".join(p for p in parts if p)


_FAST_SUFFIX = (
    "\n\nReturn STRICT JSON ONLY: "
    '{"label": "<one label>", "confidence": 0..1, '
    '"rationale": "<one short sentence>"}. No prose outside JSON.'
)

_DEEP_SUFFIX_TMPL = (
    "\n\nReturn STRICT JSON ONLY with keys: "
    'label (one of {labels}), confidence (0..1), '
    'rationale (1-2 sentences), '
    'evidence (array of ≤5 short concrete signals), '
    'flippers (array of ≤2 signals whose absence would flip the decision), '
    'runner_up (the second most likely label), '
    'pipeline_ready (bool). '
    "No prose outside JSON."
)


def _parse_json(text: str) -> Optional[dict]:
    if not text:
        return None
    try:
        return _json.loads(text)
    except Exception:
        pass
    try:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return _json.loads(text[start:end + 1])
    except Exception:
        return None
    return None


def _coerce_label(obj: Optional[dict], labels: list[str],
                  default: str) -> dict:
    if not isinstance(obj, dict):
        return {"label": default, "confidence": 0.0,
                "rationale": "parser fallback", "evidence": [],
                "flippers": [], "runner_up": default,
                "pipeline_ready": False}
    lbl = str(obj.get("label", "")).strip().lower()
    if lbl not in [l.lower() for l in labels]:
        lbl = default
    else:
        lbl = next(l for l in labels if l.lower() == lbl)
    try:
        conf = float(obj.get("confidence", 0.0))
    except Exception:
        conf = 0.0
    return {
        "label": lbl,
        "confidence": max(0.0, min(1.0, conf)),
        "rationale": str(obj.get("rationale", ""))[:500],
        "evidence": list(obj.get("evidence") or [])[:5],
        "flippers": list(obj.get("flippers") or [])[:2],
        "runner_up": str(obj.get("runner_up", "")) or default,
        "pipeline_ready": bool(obj.get("pipeline_ready", False)),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Classifier
# ─────────────────────────────────────────────────────────────────────────────

class Classifier:
    """Fast N-label triage over documents + text + arbitrary context.

    The constructor fires a background pipeline and returns immediately.
    Accessing ``.preview`` blocks on Phase 1 (Haiku). Accessing ``.label``
    blocks on Phase 2 (Sonnet) or falls back to Phase 1 at timeout.
    """

    def __init__(
        self,
        labels: list[str],
        rules: str = "",
        documents: Optional[Iterable[DocLike]] = None,
        text: Optional[str] = None,
        factory_id: int = 0,
        timeout: int = 30,
        fast_timeout: int = 12,
        extract_timeout: int = 25,
        extras: Optional[dict] = None,
        parallel: int = 4,
        fast_model: str = "charles-json",
        deep_model: str = "charles-json",
    ):
        if not labels or len(labels) < 2:
            raise ValueError("Classifier: provide at least 2 labels")
        self.labels = list(labels)
        self.rules = rules or ""
        self.text = text or ""
        self.factory_id = int(factory_id)
        self.timeout = int(timeout)
        self.fast_timeout = min(int(fast_timeout), self.timeout)
        self.extract_timeout = int(extract_timeout)
        self.extras = dict(extras or {})
        self.parallel = max(1, int(parallel))
        self.fast_model = fast_model
        self.deep_model = deep_model

        self._default = self.labels[-1]  # catch-all
        self._docs = [_normalize(d) for d in (documents or [])]

        # State
        self._phase1: Optional[dict] = None
        self._phase2: Optional[dict] = None
        self._p1_done = threading.Event()
        self._p2_done = threading.Event()
        self._extracts: list[str] = []
        self._t0 = time.time()
        self._elapsed_p1_ms = 0
        self._elapsed_ms = 0
        self._error: Optional[str] = None

        threading.Thread(target=self._run, daemon=True).start()

    # ── Pipeline ───────────────────────────────────────────────────────────

    def _run_phase1_light(self):
        """Fast verdict on text+filenames only — no VLM wait."""
        t1 = time.time()
        filenames = [d[0] for d in self._docs]
        light_ctx = _build_context(
            self.labels, self.rules, self.text,
            [f"--- {n} ---\n[attached: {n}]" for n in filenames],
            self.extras, self.factory_id,
        )
        try:
            r1 = LLM(light_ctx + _FAST_SUFFIX, model=self.fast_model,
                     timeout=self.fast_timeout)
            p1 = _coerce_label(_parse_json(getattr(r1, "text", "")),
                               self.labels, self._default)
        except Exception as e:
            p1 = _coerce_label(None, self.labels, self._default)
            p1["rationale"] = f"fast phase error: {e}"
        self._phase1 = p1
        self._elapsed_p1_ms = int((time.time() - t1) * 1000)
        self._p1_done.set()

    def _run(self):
        try:
            # Fire Phase 1 (light) in parallel with document extraction
            phase1_thread = threading.Thread(
                target=self._run_phase1_light, daemon=True)
            phase1_thread.start()

            if self._docs:
                with ThreadPoolExecutor(max_workers=self.parallel) as pool:
                    self._extracts = list(pool.map(
                        lambda d: _extract_one(d[0], d[1], d[2],
                                               self.factory_id,
                                               self.extract_timeout),
                        self._docs,
                    ))

            # Make sure preview is ready before Phase 2 starts
            phase1_thread.join(timeout=self.fast_timeout + 2)
            if not self._p1_done.is_set():
                self._phase1 = _coerce_label(None, self.labels, self._default)
                self._phase1["rationale"] = "fast phase timed out"
                self._elapsed_p1_ms = int((time.time() - self._t0) * 1000)
                self._p1_done.set()

            # Phase 2: full context, strict verdict, remaining budget
            remaining = self.timeout - (time.time() - self._t0)
            if remaining <= 2:
                self._phase2 = None
                return

            context = _build_context(
                self.labels, self.rules, self.text,
                self._extracts, self.extras, self.factory_id,
            )
            suffix = _DEEP_SUFFIX_TMPL.format(
                labels=", ".join(f'"{l}"' for l in self.labels))
            try:
                r2 = LLM(context + suffix, model=self.deep_model,
                         timeout=int(remaining))
                parsed = _parse_json(getattr(r2, "text", ""))
                if parsed is None and self._phase1 is not None:
                    # Fall back to Phase 1 rather than the default label
                    self._phase2 = None
                    self._error = "deep phase: unparseable — falling back to preview"
                    return
                self._phase2 = _coerce_label(parsed, self.labels, self._default)
            except Exception as e:
                self._error = f"deep phase error: {e}"
                self._phase2 = None
        except Exception as e:
            self._error = str(e)
            if self._phase1 is None:
                self._phase1 = _coerce_label(None, self.labels, self._default)
                self._phase1["rationale"] = f"pipeline error: {e}"
                self._p1_done.set()
        finally:
            self._elapsed_ms = int((time.time() - self._t0) * 1000)
            self._p2_done.set()

    # ── Getters ────────────────────────────────────────────────────────────

    @property
    def preview(self) -> dict:
        """Fast Haiku verdict. Blocks ≤ fast_timeout seconds."""
        self._p1_done.wait(self.fast_timeout + 1)
        if self._phase1 is None:
            return _coerce_label(None, self.labels, self._default)
        return dict(self._phase1)

    fast = preview  # alias

    @property
    def ready(self) -> bool:
        return self._p2_done.is_set()

    @property
    def ready_fast(self) -> bool:
        return self._p1_done.is_set()

    def wait(self, timeout: Optional[float] = None) -> "Classifier":
        """Block until Phase 2 completes (or timeout)."""
        self._p2_done.wait(timeout if timeout is not None
                           else self.timeout + 1)
        return self

    def _final(self) -> dict:
        self.wait()
        if self._phase2 is not None:
            v = dict(self._phase2)
            v["tentative"] = False
            return v
        v = dict(self._phase1 or _coerce_label(None, self.labels,
                                               self._default))
        v["tentative"] = True
        return v

    @property
    def label(self) -> str: return self._final()["label"]

    @property
    def confidence(self) -> float: return self._final()["confidence"]

    @property
    def rationale(self) -> str: return self._final()["rationale"]

    @property
    def evidence(self) -> list: return self._final()["evidence"]

    @property
    def flippers(self) -> list: return self._final()["flippers"]

    @property
    def runner_up(self) -> str: return self._final()["runner_up"]

    @property
    def pipeline_ready(self) -> bool: return self._final()["pipeline_ready"]

    @property
    def tentative(self) -> bool: return self._final()["tentative"]

    @property
    def elapsed_ms(self) -> int:
        self.wait()
        return self._elapsed_ms

    def to_dict(self) -> dict:
        v = self._final()
        return {
            **v,
            "factory_id": self.factory_id,
            "labels": list(self.labels),
            "n_documents": len(self._docs),
            "preview": dict(self._phase1 or {}),
            "elapsed_ms": self._elapsed_ms,
            "fast_ms": self._elapsed_p1_ms,
            "error": self._error,
        }

    def __repr__(self):
        if not self._p1_done.is_set():
            return f"Classifier(computing, {len(self._docs)} docs)"
        if not self._p2_done.is_set():
            p = self._phase1 or {}
            return (f"Classifier(preview={p.get('label')!r} "
                    f"conf={p.get('confidence', 0):.2f} … deep pending)")
        v = self._final()
        tag = " tentative" if v["tentative"] else ""
        return (f"Classifier(label={v['label']!r} "
                f"conf={v['confidence']:.2f}{tag})")

    def __str__(self):
        return self.label

    # ── Batch helper ───────────────────────────────────────────────────────

    @classmethod
    def batch(
        cls,
        jobs: list[dict],
        labels: list[str],
        rules: str = "",
        factory_id: int = 0,
        timeout: int = 30,
        parallel: int = 3,
        **kw,
    ) -> list[dict]:
        """Run many classifications in parallel.

        Each job is a dict with any of the constructor kwargs
        (``documents``, ``text``, ``extras``, per-job overrides).
        Returns a list of ``.to_dict()`` verdicts in the same order.
        """
        def _one(job: dict) -> dict:
            params = {
                "labels": labels, "rules": rules,
                "factory_id": factory_id, "timeout": timeout,
                **kw, **job,
            }
            return cls(**params).to_dict()

        with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
            return list(pool.map(_one, jobs))
