"""MonceOS core — constructor + _call.

Iter 1: minimal surface. Just enough to bind factory_id + tenant + framework_id
at construction and POST to /v1/chat with all four. No verbs yet.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

from .types import CR
from . import capture as _capture_mod

DEFAULT_ENDPOINT = "https://monceapp.aws.monce.ai"


@dataclass
class OSCall:
    """Result of a raw _call. Mirrors the /v1/chat response shape."""
    text: str
    model: str
    elapsed_ms: int
    factory_id: int
    framework_id: Optional[str]
    session_id: str
    sat_memory: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return self.text


class MonceOS:
    """One OS per (factory, tenant). Carries the binding for every sub-call."""

    def __init__(
        self,
        factory_id: int,
        tenant: Optional[str] = None,
        framework_id: Optional[str] = None,
        session_id: Optional[str] = None,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout: int = 120,
    ):
        self.factory_id = factory_id
        self.tenant = tenant
        self.framework_id = framework_id
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self._http = requests.Session()

    def __repr__(self) -> str:
        return (
            f"MonceOS(factory_id={self.factory_id}, tenant={self.tenant!r}, "
            f"framework_id={self.framework_id!r}, session={self.session_id!r})"
        )

    def _call(
        self,
        message: str,
        *,
        model: str = "charles-json",
        framework_id: Optional[str] = None,
        factory_id: Optional[int] = None,
        session_id: Optional[str] = None,
    ) -> OSCall:
        """Raw POST to /v1/chat with framework_id binding.

        Keys the backend expects: model_id, message, factory_id, framework_id,
        session_id. Everything except model_id and message is optional.
        """
        url = f"{self.endpoint}/v1/chat"
        data = {"model_id": model, "message": message}
        fid = factory_id if factory_id is not None else self.factory_id
        if fid:
            data["factory_id"] = str(fid)
        fwk = framework_id if framework_id is not None else self.framework_id
        if fwk:
            data["framework_id"] = fwk
        sid = session_id if session_id is not None else self.session_id
        if sid:
            data["session_id"] = sid

        t = time.time()
        resp = self._http.post(url, data=data, timeout=self.timeout)
        elapsed_ms = int((time.time() - t) * 1000)

        if resp.status_code != 200:
            return OSCall(
                text=f"HTTP {resp.status_code}: {resp.text[:200]}",
                model=model,
                elapsed_ms=elapsed_ms,
                factory_id=fid or 0,
                framework_id=fwk,
                session_id=sid or "",
                raw={"error": resp.text[:500]},
            )

        body = resp.json()
        return OSCall(
            text=body.get("reply", ""),
            model=body.get("model", model),
            elapsed_ms=body.get("elapsed_ms") or elapsed_ms,
            factory_id=body.get("factory_id") or fid or 0,
            framework_id=fwk,
            session_id=body.get("session_id") or sid or "",
            sat_memory=body.get("sat_memory") or {},
            usage=body.get("usage") or {},
            raw=body,
        )

    # ------------------------------------------------------------------ verbs

    def capture(
        self,
        *,
        transcript: Optional[str] = None,
        audio_bytes: Optional[bytes] = None,
        today: Optional[str] = None,
        visit_id: Optional[str] = None,
    ) -> CR:
        """Voice/transcript → structured CR.

        Routes through the proprietary `Json` class (charles-json), not raw
        Haiku/Sonnet. Iter 2: transcript path only.
        """
        if audio_bytes is not None:
            raise NotImplementedError("audio_bytes path lands in iter 9 (STT wiring)")
        if not transcript or not transcript.strip():
            raise ValueError("capture() requires transcript=... (non-empty)")
        return _capture_mod.capture_from_transcript(
            self, transcript, today=today, visit_id=visit_id,
        )
