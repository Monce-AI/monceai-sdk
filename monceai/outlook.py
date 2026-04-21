"""
monceai.Outlook — memory-augmented extraction for email / Outlook workflows.

Wraps selfservice.aws.monce.ai with a high-level API that fits the Outlook
plugin's mental model: ingest an email, extract its attachments, remember
what happened, recall later.

    from monceai import Outlook

    ol = Outlook(user_id="7a3f9b2c", auto_memory=True)

    # Extract attachments from an email
    ex = ol.extract_email(
        attachments=[pdf_bytes, ("invoice.xlsx", xlsx_bytes)],
        subject="Devis cloisonneur VIP",
        body="Peux-tu me traiter ca comme d'hab?",
    )
    ex.lines               # extracted rows
    ex.insights            # Haiku-distilled bullets (auto_memory=True)

    # Memory ops
    ol.remember("client always wants 44.2 rTherm as intercalaire")
    ol.recall("VIP cloisonneur patterns")
    ol.forget("outdated pattern")

    # Past activity
    ol.history(limit=10)
    ol.memories(limit=50)
    ol.stats()

    # Chat grounded on user memory
    ol.chat("What does this user usually do with VIP files?")

AUTO-MEMORY REFLEX
    When auto_memory=True (default False), every extract_email() call:
    1. Auto-recalls relevant prior memories (by email subject).
    2. Runs the selfservice /v1/extract with insight distillation (Haiku).
    3. Writes distilled bullets back to memory as 'insight' entries.

    Toggle at runtime: ol.auto_memory = False
"""

from __future__ import annotations

import os
from typing import Any, Iterable, Optional, Union

import requests

from .extraction import SELFSERVICE_ENDPOINT, Extraction


class Outlook:
    """High-level memory-aware extraction client for Outlook / email."""

    def __init__(
        self,
        user_id: str,
        auto_memory: bool = False,
        endpoint: Optional[str] = None,
        timeout: int = 300,
    ):
        if not user_id or not isinstance(user_id, str):
            raise ValueError("Outlook requires user_id (str)")
        self.user_id = user_id
        self.auto_memory = bool(auto_memory)
        self.endpoint = (endpoint or SELFSERVICE_ENDPOINT).rstrip("/")
        self.timeout = timeout

    # ── Extraction ─────────────────────────────────────────────────────────

    def extract_email(
        self,
        attachments: Iterable[Union[bytes, tuple[str, bytes], str, os.PathLike]],
        subject: Optional[str] = None,
        body: Optional[str] = None,
        industry: Optional[str] = None,
        auto_memory: Optional[bool] = None,
    ) -> Extraction:
        """Extract attachments with full email context.

        attachments: list of bytes, (filename, bytes) tuples, or filesystem paths.
        subject / body: email metadata (used for recall + insight distillation).
        auto_memory: overrides the instance default for this call.

        Returns an Extraction (dict-like) with .lines, .insights, .trust, etc.
        """
        atts = list(attachments)
        if not atts:
            raise ValueError("extract_email: no attachments provided")

        effective_auto = self.auto_memory if auto_memory is None else bool(auto_memory)
        return Extraction(
            source=atts,
            user_id=self.user_id,
            industry=industry,
            email_subject=subject,
            email_body=body,
            auto_memory=effective_auto,
            endpoint=self.endpoint,
            timeout=self.timeout,
        )

    def extract(
        self,
        source: Union[str, bytes, os.PathLike, list],
        filename: Optional[str] = None,
        industry: Optional[str] = None,
        context: Optional[str] = None,
        auto_memory: Optional[bool] = None,
    ) -> Extraction:
        """Non-email path — extract a single file or list of files."""
        effective_auto = self.auto_memory if auto_memory is None else bool(auto_memory)
        return Extraction(
            source=source,
            user_id=self.user_id,
            filename=filename,
            industry=industry,
            context=context,
            auto_memory=effective_auto,
            endpoint=self.endpoint,
            timeout=self.timeout,
        )

    # ── Memory ops ─────────────────────────────────────────────────────────

    def remember(
        self,
        text: str,
        source: str = "user",
        tags: Optional[list[str]] = None,
    ) -> dict:
        """Store a memory for this user."""
        body = {"user_id": self.user_id, "text": text, "source": source}
        if tags:
            body["tags"] = tags
        r = requests.post(f"{self.endpoint}/v1/remember", json=body, timeout=20)
        r.raise_for_status()
        return r.json()

    def forget(self, query: str) -> int:
        """Forget any memory matching `query` (substring, case-insensitive)."""
        r = requests.post(
            f"{self.endpoint}/v1/forget",
            json={"user_id": self.user_id, "query": query},
            timeout=20,
        )
        r.raise_for_status()
        return int(r.json().get("forgotten", 0))

    def recall(self, q: str = "", limit: int = 10) -> list[dict]:
        """Keyword-scored memory search. Empty q returns recent memories."""
        r = requests.get(
            f"{self.endpoint}/v1/recall",
            params={"user_id": self.user_id, "q": q, "limit": limit},
            timeout=20,
        )
        r.raise_for_status()
        return list(r.json().get("memories") or [])

    def memories(self, limit: int = 50, tag: Optional[str] = None) -> list[dict]:
        """All memories for this user (optionally filtered by tag)."""
        params: dict[str, Any] = {"user_id": self.user_id, "limit": limit}
        if tag:
            params["tag"] = tag
        r = requests.get(f"{self.endpoint}/v1/memories", params=params, timeout=20)
        r.raise_for_status()
        return list(r.json().get("memories") or [])

    def history(self, limit: int = 50) -> list[dict]:
        """Past extractions (most recent first)."""
        r = requests.get(
            f"{self.endpoint}/v1/history",
            params={"user_id": self.user_id, "limit": limit},
            timeout=20,
        )
        r.raise_for_status()
        return list(r.json().get("extractions") or [])

    def stats(self) -> dict:
        """User-level counts."""
        r = requests.get(
            f"{self.endpoint}/v1/user/{self.user_id}/stats", timeout=20
        )
        r.raise_for_status()
        return r.json()

    # ── Chat ───────────────────────────────────────────────────────────────

    def chat(self, message: str) -> dict:
        """Memory-grounded Q&A (Sonnet).

        Returns {"reply": str, "latency_ms": int, ...}. The reply is shaped
        by the user's memory + extraction history — never crosses user lines.
        """
        r = requests.post(
            f"{self.endpoint}/v1/chat",
            json={"user_id": self.user_id, "message": message},
            timeout=120,
        )
        r.raise_for_status()
        return r.json()

    # ── Repr ───────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"Outlook(user_id={self.user_id!r}, auto_memory={self.auto_memory}, "
            f"endpoint={self.endpoint!r})"
        )
