"""Typed data contracts between MonceOS and bricks.

CR, Action, Contact, NextStep, Brief. Stable JSON shape.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, List, Optional

SENTIMENTS = {"positive", "neutral", "negative"}
PRIORITIES = {"high", "medium", "low"}
OWNER_TEAMS = {"sales_ops", "service", "quoting", "logistics"}


def _clamp(value: Any, allowed: set, default: str) -> str:
    if isinstance(value, str) and value.lower() in allowed:
        return value.lower()
    # soft mapping — common model drifts
    if isinstance(value, str):
        v = value.lower()
        if "sale" in v or "pricing" in v or "commercial" in v:
            if "sales_ops" in allowed:
                return "sales_ops"
            if "quoting" in allowed:
                return "quoting"
        if "quote" in v or "devis" in v:
            return "quoting"
        if "service" in v or "support" in v or "client" in v:
            return "service"
        if "logistic" in v or "shipping" in v or "transport" in v:
            return "logistics"
    return default


@dataclass
class Contact:
    name: str
    role: Optional[str] = None
    is_new: bool = False
    numero_client: Optional[str] = None
    match_confidence: Optional[float] = None

    @classmethod
    def from_dict(cls, d: dict) -> "Contact":
        return cls(
            name=d.get("name", "").strip(),
            role=d.get("role"),
            is_new=bool(d.get("is_new", False)),
            numero_client=d.get("numero_client"),
            match_confidence=d.get("match_confidence"),
        )


@dataclass
class Action:
    description: str
    owner_team: str = "sales_ops"
    deadline: Optional[str] = None    # ISO 8601
    amount_eur: Optional[float] = None
    priority: str = "medium"

    @classmethod
    def from_dict(cls, d: dict) -> "Action":
        amt = d.get("amount_eur")
        if isinstance(amt, str):
            try:
                amt = float(amt.replace(",", "."))
            except ValueError:
                amt = None
        return cls(
            description=d.get("description", "").strip(),
            owner_team=_clamp(d.get("owner_team"), OWNER_TEAMS, "sales_ops"),
            deadline=d.get("deadline"),
            amount_eur=amt,
            priority=_clamp(d.get("priority"), PRIORITIES, "medium"),
        )


@dataclass
class NextStep:
    what: Optional[str] = None
    when: Optional[str] = None          # ISO 8601

    @classmethod
    def from_dict(cls, d: dict) -> "NextStep":
        if not d:
            return cls()
        return cls(what=d.get("what"), when=d.get("when"))


@dataclass
class CR:
    """Compte-rendu. The 5-extraction contract."""
    summary: str = ""
    actions: List[Action] = field(default_factory=list)
    contacts_met: List[Contact] = field(default_factory=list)
    sentiment: str = "neutral"
    next_step: NextStep = field(default_factory=NextStep)

    # provenance
    transcript: str = ""
    model: str = ""
    elapsed_ms: int = 0
    raw_json: str = ""
    factory_id: int = 0
    tenant: Optional[str] = None
    visit_id: Optional[str] = None
    created_at: str = ""
    schema_error: Optional[str] = None

    @classmethod
    def from_json(cls, body: dict) -> "CR":
        return cls(
            summary=body.get("summary", "").strip(),
            actions=[Action.from_dict(a) for a in (body.get("actions") or []) if isinstance(a, dict)],
            contacts_met=[Contact.from_dict(c) for c in (body.get("contacts_met") or []) if isinstance(c, dict)],
            sentiment=_clamp(body.get("sentiment"), SENTIMENTS, "neutral"),
            next_step=NextStep.from_dict(body.get("next_step") or {}),
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def __str__(self) -> str:
        return self.to_json()


@dataclass
class Brief:
    """Pre-visit brief. Numbers-first."""
    account_id: str = ""
    account_name: str = ""
    as_of: str = ""
    priorities: List[str] = field(default_factory=list)
    open_quotes: List[dict] = field(default_factory=list)
    open_claims: List[dict] = field(default_factory=list)
    recent_orders: List[dict] = field(default_factory=list)
    unfulfilled_promises: List[dict] = field(default_factory=list)
    contacts_known: List[dict] = field(default_factory=list)
    attention_line: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
