"""os.capture — transcript → CR.

Uses the proprietary `Json` class (from monceai import Json) which routes to
charles-json (4-payload Monce model: haiku memory + haiku csv + haiku cnf →
Sonnet synthesis), not raw Haiku or Sonnet.

Iter 2: transcript-only path. Audio path (STT) lands later.
"""

from __future__ import annotations

import json as _json
from datetime import datetime
from typing import Optional

from ..llm import Json
from .types import CR


SCHEMA_INSTRUCTION = """You extract structured B2B sales visit reports from French or English transcripts.

Required shape (every key, exact names):
{
  "summary": "2-3 sentences in the rep's language",
  "actions": [
    {
      "description": "what to do",
      "owner_team": one of ["sales_ops","service","quoting","logistics"],
      "deadline": "YYYY-MM-DD" or null,
      "amount_eur": number or null,
      "priority": one of ["high","medium","low"]
    }
  ],
  "contacts_met": [
    {"name": "Full Name", "role": "title", "is_new": true|false}
  ],
  "sentiment": one of ["positive","neutral","negative"],
  "next_step": {"what": "...", "when": "YYYY-MM-DD"}
}

Rules:
- Never invent. If a field is unknown, use null (not a guess).
- amount_eur is a number or null. Never a string.
- Dates in ISO 8601. Compute from TODAY if the transcript says "vendredi prochain" etc.
- sentiment is exactly one of positive, neutral, negative. No hedging.
- is_new = true unless the transcript explicitly mentions the contact was met before.
- If the transcript is under 30 seconds of usable speech, return {"error": "recording_too_short"}.
"""


def capture_from_transcript(
    os_handle,
    transcript: str,
    *,
    today: Optional[str] = None,
    visit_id: Optional[str] = None,
) -> CR:
    """Transcript → CR via the proprietary `Json` class (charles-json)."""
    today = today or datetime.utcnow().strftime("%Y-%m-%d")
    prompt = (
        f"{SCHEMA_INSTRUCTION}\n\n"
        f"TODAY: {today}\n\n"
        f"TRANSCRIPT:\n{transcript.strip()}\n"
    )

    # Json is a dict subclass; blocks until charles-json responds and parses.
    t0 = datetime.utcnow()
    j = Json(prompt, factory_id=os_handle.factory_id, timeout=os_handle.timeout)
    body = dict(j)
    result = j.result  # LLMResult: .model, .elapsed_ms, .text

    common = dict(
        transcript=transcript,
        model=result.model,
        elapsed_ms=result.elapsed_ms,
        raw_json=result.text,
        factory_id=os_handle.factory_id,
        tenant=getattr(os_handle, "tenant", None),
        visit_id=visit_id,
        created_at=t0.isoformat() + "Z",
    )

    if body.get("error") == "recording_too_short":
        return CR(summary="", sentiment="neutral", schema_error="recording_too_short", **common)

    if not body:
        return CR(schema_error="json_parse_failed", **common)

    cr = CR.from_json(body)
    for k, v in common.items():
        setattr(cr, k, v)
    return cr
