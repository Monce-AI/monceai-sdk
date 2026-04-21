"""
monceai.Extraction — memory-augmented extraction via selfservice.aws.monce.ai.

One-shot: file → structured lines + trust + insights + memory.

    from monceai import Extraction

    ex = Extraction("quote.pdf", user_id="7a3f9b2c")
    ex.lines                # list[dict] — extracted rows
    ex.trust                # {"score": 87, "routing": "auto_accept"}
    ex.client               # {"name": "RIOU GLASS", ...}
    ex.header               # {"document_type": "devis", "language": "fr", ...}
    ex.insights             # list[str] — Haiku-distilled memory bullets (if auto_memory)
    ex.prior_memories       # list[str] — auto-recalled user context used as hint
    ex.task_id              # for polling / history lookups
    ex.duration_ms

Also accepts:
    Extraction(b"%PDF-1.4...", user_id="...")       # raw bytes
    Extraction(path_or_bytes, filename="foo.pdf",   # explicit filename
               user_id="...", industry="glass",
               auto_memory=True, email_subject="...", email_body="...")

The instance IS a dict (pretty-prints JSON). `ex.result` holds the full
payload from the server; convenience accessors above are shortcuts.
"""

from __future__ import annotations

import json as _json
import os
import time
from typing import Optional, Union

import requests

SELFSERVICE_ENDPOINT = os.getenv("SELFSERVICE_ENDPOINT", "https://selfservice.aws.monce.ai")


def _coerce_file(
    source: Union[str, bytes, os.PathLike],
    filename: Optional[str] = None,
) -> tuple[str, bytes, str]:
    """Return (filename, bytes, content_type) from a path or raw bytes."""
    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
        name = filename or "document.pdf"
    else:
        path = os.fspath(source)
        name = filename or os.path.basename(path)
        with open(path, "rb") as f:
            data = f.read()

    # Guess content-type from extension
    ext = os.path.splitext(name)[1].lower()
    ct = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".csv": "text/csv",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".msg": "application/vnd.ms-outlook",
    }.get(ext, "application/octet-stream")
    return name, data, ct


class Extraction(dict):
    """Memory-augmented one-shot extraction. The instance IS a dict."""

    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)

    def __init__(
        self,
        source: Union[str, bytes, os.PathLike, list],
        user_id: str,
        filename: Optional[str] = None,
        industry: Optional[str] = None,
        context: Optional[str] = None,
        email_subject: Optional[str] = None,
        email_body: Optional[str] = None,
        auto_memory: bool = False,
        endpoint: Optional[str] = None,
        timeout: int = 300,
    ):
        super().__init__()
        if not user_id or not isinstance(user_id, str):
            raise ValueError("Extraction requires user_id (str)")

        ep = (endpoint or SELFSERVICE_ENDPOINT).rstrip("/")
        url = f"{ep}/v1/extract"

        # Accept list of sources for multi-file extraction
        sources = source if isinstance(source, list) else [source]
        files = []
        for i, src in enumerate(sources):
            if isinstance(src, tuple) and len(src) == 2:
                # (filename, bytes)
                f_name, f_bytes, f_ct = _coerce_file(src[1], filename=src[0])
            else:
                f_name, f_bytes, f_ct = _coerce_file(
                    src, filename=filename if i == 0 else None
                )
            files.append(("files", (f_name, f_bytes, f_ct)))

        data = {"user_id": user_id, "auto_memory": "true" if auto_memory else "false"}
        if industry:
            data["industry"] = industry
        if context:
            data["context"] = context
        if email_subject:
            data["email_subject"] = email_subject
        if email_body:
            data["email_body"] = email_body

        t = time.time()
        resp = requests.post(url, data=data, files=files, timeout=timeout)
        elapsed = int((time.time() - t) * 1000)

        if resp.status_code != 200:
            raise RuntimeError(
                f"Selfservice {resp.status_code}: {resp.text[:400]}"
            )

        body = resp.json()
        self.update(body)
        self._endpoint = ep
        self._user_id = user_id
        self._roundtrip_ms = elapsed

    # ── Shortcuts ──────────────────────────────────────────────────────────
    @property
    def task_id(self) -> str:
        return self.get("task_id", "")

    @property
    def user_id(self) -> str:
        return self.get("user_id", self._user_id)

    @property
    def duration_ms(self) -> int:
        return int(self.get("duration_ms") or self._roundtrip_ms)

    @property
    def result(self) -> dict:
        return self.get("result") or {}

    @property
    def lines(self) -> list:
        return self.result.get("lines") or []

    @property
    def header(self) -> dict:
        return self.result.get("header") or {}

    @property
    def client(self) -> dict:
        return self.result.get("client") or {}

    @property
    def trust(self) -> dict:
        return self.result.get("trust") or {}

    @property
    def validation(self) -> dict:
        return self.result.get("validation") or {}

    @property
    def vertical(self) -> Optional[str]:
        return self.result.get("vertical")

    @property
    def insights(self) -> list[str]:
        return list(self.get("insights") or [])

    @property
    def prior_memories(self) -> list[str]:
        return list(self.get("prior_memories") or [])

    # ── Feedback / follow-up actions ──────────────────────────────────────
    def feedback(self, kind: str, payload: Optional[dict] = None) -> dict:
        """Record feedback on this extraction. kind ∈ {accept, reject, correct, note}."""
        url = f"{self._endpoint}/v1/feedback"
        body = {
            "user_id": self._user_id,
            "task_id": self.task_id,
            "kind": kind,
            "payload": payload or {},
        }
        r = requests.post(url, json=body, timeout=20)
        r.raise_for_status()
        return r.json()

    def accept(self, note: Optional[str] = None) -> dict:
        return self.feedback("accept", {"note": note} if note else {})

    def reject(self, reason: Optional[str] = None) -> dict:
        return self.feedback("reject", {"reason": reason} if reason else {})

    def correct(self, **payload) -> dict:
        return self.feedback("correct", payload)

    # ── Export ────────────────────────────────────────────────────────────
    def __str__(self) -> str:
        return _json.dumps(dict(self), ensure_ascii=False, indent=2)

    def __repr__(self) -> str:
        return (
            f"Extraction(task_id={self.task_id!r}, user_id={self.user_id!r}, "
            f"lines={len(self.lines)}, trust={self.trust.get('score')}, "
            f"routing={self.trust.get('routing')!r})"
        )
