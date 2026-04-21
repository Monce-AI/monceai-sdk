#!/usr/bin/env python3
"""extract_pipeline.py — quality enhancement on top of selfservice Extraction.

One file, one class: ``Extract(file, factory_id=..., user_id=...)``.

Design:
    1. ``Extraction`` (selfservice.aws.monce.ai) does the raw lift — lines,
       client, header, trust — with full user memory (prior_memories) fed
       in as priming. Nothing re-implements VLM or JSON decoding here.
    2. Each extracted field is UPGRADED by ``Matching(..., factory_id=...)``
       against the factory's catalog. Low-confidence hits fall back to a
       Json arbitration pass over the SDK's top-N candidates.
    3. Output is reshaped to the ``POST /extract`` payload of
       ``https://claude.aws.monce.ai`` v3.10 — drop-in replacement.
    4. ``Outlook.remember`` logs the run so the next Extraction call for
       the same user_id recalls what the factory prefers.

Prompts are triple-quoted f-strings keyed off ``factory_id`` — one FACTORY
table drives prompts, matching fields, and normalization toggles.

Usage:
    python examples/extract_pipeline.py quote.pdf --factory 4 --user-id 7a3f9b2c
    python examples/extract_pipeline.py a.pdf b.pdf --factory 3 --user-id demo
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from monceai import Charles, Concierge, Extraction, Json, Matching, Outlook

PIPELINE_VERSION = "extract_pipeline-1.1.0"


# ─────────────────────────────────────────────────────────────────────
# FACTORY TABLE — the single source of truth.
# Adding a factory = adding a row.
# ─────────────────────────────────────────────────────────────────────

FACTORY: dict[int, dict[str, Any]] = {
    1:  {"name": "VIT",         "profile": "dwg_specialist",
         "rule": "flat + coated IGU, DWG notation",
         "fields": ("verre1", "verre2", "intercalaire", "remplissage"),
         "default_gas": None, "spacer_color": None},
    3:  {"name": "Monce",       "profile": "default",
         "rule": "standard IGU, coated glass stays on verre1",
         "fields": ("verre1", "verre2", "verre3", "intercalaire",
                    "intercalaire2", "remplissage", "remplissage2",
                    "façonnage_arete"),
         "default_gas": None, "spacer_color": None},
    4:  {"name": "VIP",         "profile": "actif_pvc",
         "rule": "PVC-window IGU, spacer implicitly BLANC when no color printed",
         "fields": ("verre1", "verre2", "intercalaire", "remplissage",
                    "façonnage_arete"),
         "default_gas": "Argon", "spacer_color": "blanc"},
    9:  {"name": "Eurovitrage", "profile": "simple_glazing",
         "rule": "preserve printed glass order — NO coated-to-verre1 swap",
         "fields": ("verre1", "verre2", "intercalaire", "remplissage"),
         "default_gas": None, "spacer_color": None},
    10: {"name": "TGVI",        "profile": "tgvi_specialist",
         "rule": "flat-glass transformer — verre1 holds the full designation verbatim",
         "fields": ("verre1",),
         "default_gas": None, "spacer_color": None},
    13: {"name": "VIC",         "profile": "default",
         "rule": "IGU with occasional triple glazing",
         "fields": ("verre1", "verre2", "verre3", "intercalaire",
                    "intercalaire2", "remplissage", "remplissage2"),
         "default_gas": None, "spacer_color": None},
}


def factory(fid: int) -> dict[str, Any]:
    return FACTORY.get(fid, FACTORY[3])


# ─────────────────────────────────────────────────────────────────────
# DYNAMIC PROMPTS — triple-quoted, f-string interpolated per factory.
# ─────────────────────────────────────────────────────────────────────

def context_prompt(factory_id: int, prior_memories: list[str]) -> str:
    """Priming context sent to Extraction via the `context` field.

    Selfservice uses this verbatim to shape the extraction. Factory rules
    + recalled memories become the extraction's operating frame.
    """
    f = factory(factory_id)
    bullets = "\n".join(f"  - {m}" for m in prior_memories[:10]) \
        if prior_memories else "  (none on file)"
    return f"""
Factory: {f['name']} (factory_id={factory_id}, profile={f['profile']})
Rule:    {f['rule']}
Active matching fields: {", ".join(f['fields'])}
Spacer color default:   {f['spacer_color'] or 'none'}
Gas default:            {f['default_gas'] or 'none'}

Prior memories for this user:
{bullets}

Extract verbatim. Skip shipping / packaging / forfait / totals. Use null
when a value is not clearly printed — never guess.
""".strip()


def arbitration_prompt(factory_id: int, raw: str, candidates: list[dict]) -> str:
    f = factory(factory_id)
    return f"""
You are arbitrating a fuzzy article match for factory {f['name']}
(factory_id={factory_id}).

Raw value from the document:
    {raw!r}

Candidate catalog entries (top-N, from Matching cascade):
{json.dumps(candidates, ensure_ascii=False, indent=2)}

Pick the single best match OR return num_article=null if none is a clear
fit. Return strict JSON:

{{
  "num_article":  str | null,
  "denomination": str | null,
  "confidence":   float 0..1
}}

Prefer exact token overlap with the raw value; never invent article
numbers that aren't in the candidate list.
""".strip()


def synthesis_prompt(payload: list[dict]) -> str:
    return f"""
Merge these {len(payload)} document row-lists into ONE deduplicated order.
Two rows are the same iff they share repere AND dimensions (±5mm).
On conflict: prefer PDF > email > text.

Return strict JSON:
{{
  "merged_rows":        [...same schema as input rows...],
  "conflicts":          [ {{"field": str, "values": [any, any], "resolution": str}} ],
  "duplicates_removed": int
}}

--- DOCUMENTS ---
{json.dumps(payload, ensure_ascii=False)}
""".strip()


def narration_prompt(factory_id: int, n_docs: int, n_rows: int,
                     client_name: str, n_conflicts: int) -> str:
    f = factory(factory_id)
    return f"""
Write ONE sentence (max 25 words) summarising this extraction run for
factory {f['name']} (factory_id={factory_id}):
  docs={n_docs}, rows={n_rows}, client={client_name}, conflicts={n_conflicts}.
Plain text, no markdown, no preamble.
""".strip()


# ─────────────────────────────────────────────────────────────────────
# Matching upgrade — the quality enhancement over raw Extraction.
# ─────────────────────────────────────────────────────────────────────

_SDK_FIELD = {
    "verre1": "verre", "verre2": "verre", "verre3": "verre",
    "intercalaire": "intercalaire", "intercalaire2": "intercalaire",
    "remplissage": "remplissage", "remplissage2": "remplissage",
    "faconnage_arete": "faconnage", "façonnage_arete": "faconnage",
}


def upgrade_matches(rows: list[dict], *, factory_id: int) -> list[dict]:
    """Fire one Matching future per (row, field), arbitrate low confidence.

    Matching(..., factory_id=f) runs each call through the factory's
    catalog — snake_exact → fuzzy → haiku arbitration cascade inside the
    SDK. Construction fires immediately so all futures run in parallel;
    wall clock is the slowest single call.
    """
    f = factory(factory_id)
    pending: list[tuple[int, str, Any, str]] = []

    for i, row in enumerate(rows):
        for internal in f["fields"]:
            v = row.get(internal)
            if not isinstance(v, str) or not v:
                continue
            sdk_field = _SDK_FIELD.get(internal, "verre")
            pending.append((i, internal,
                            Matching(v, field=sdk_field,
                                     factory_id=factory_id), v))

    matches: list[dict] = []
    for row_idx, fld, m, raw in pending:
        conf = float(m.get("confidence") or 0.0)
        num, denom, method = m.get("num_article"), m.get("denomination"), "snake"

        if conf < 0.75:
            meta = getattr(m, "result", None)
            cands = ((meta.sat_memory or {}).get("candidates")
                     if meta and getattr(meta, "sat_memory", None) else None) or []
            if cands:
                picked = dict(Json(arbitration_prompt(factory_id, raw, cands)))
                if picked.get("num_article"):
                    conf = max(conf, 0.3) * float(picked.get("confidence") or 0.5)
                    num = picked["num_article"]
                    denom = picked.get("denomination")
                    method = "haiku_fallback"

        matches.append({
            "row": row_idx, "field": fld, "raw": raw,
            "num_article": num, "denomination": denom,
            "confidence": round(conf, 4), "method": method,
        })
    return matches


def upgrade_client(raw_client: dict, *, factory_id: int) -> dict:
    """Promote a raw client dict to a factory-matched client.

    Fires up to 4 parallel Matching futures (nom / logo / raison / siret),
    picks argmax(confidence). Keeps the raw extraction fields intact.
    """
    siret = raw_client.get("siret") or raw_client.get("siren") \
        or raw_client.get("siret_siren")
    futs: list[tuple[str, str, Any]] = []
    for label, value, field in [
        ("nom",            raw_client.get("name") or raw_client.get("nom"), None),
        ("logo_text",      raw_client.get("logo_text"),                     None),
        ("raison_sociale", raw_client.get("raison_sociale") or raw_client.get("raison_social"), None),
        ("siret",          siret,                                            "siret"),
    ]:
        if not value:
            continue
        m = Matching(value, field=field, factory_id=factory_id) if field \
            else Matching(value, factory_id=factory_id)
        futs.append((label, value, m))

    cascade: list[dict] = []
    best: dict | None = None
    for label, value, m in futs:
        entry = {
            "source_field":  label,
            "source_value":  value,
            "numero_client": m.get("numero_client"),
            "nom_matched":   m.get("nom") or m.get("denomination"),
            "confidence":    float(m.get("confidence") or 0.0),
            "method":        m.get("method") or "unknown",
        }
        cascade.append(entry)
        if best is None or entry["confidence"] > best["confidence"]:
            best = entry

    best = best or {"numero_client": None, "nom_matched": None,
                    "confidence": 0.0, "method": "none"}
    return {
        "nom_extracted":  raw_client.get("name") or raw_client.get("nom"),
        "raison_sociale": raw_client.get("raison_sociale") or raw_client.get("raison_social"),
        "logo_text":      raw_client.get("logo_text"),
        "email":          raw_client.get("email"),
        "telephone":      raw_client.get("telephone") or raw_client.get("phone"),
        "contact_name":   raw_client.get("contact_name") or raw_client.get("contact"),
        "siret":          siret,
        "adresse":        raw_client.get("adresse") or raw_client.get("address"),
        "numero_client":  best["numero_client"],
        "nom_matched":    best["nom_matched"],
        "confidence":     best["confidence"],
        "method":         best["method"],
        "cascade":        cascade,
    }


# ─────────────────────────────────────────────────────────────────────
# Prod /extract shape helpers
# ─────────────────────────────────────────────────────────────────────

def to_measurement(row: dict, source: str) -> dict:
    """Selfservice `line` → prod `measurement`."""
    def s(v):
        if v is None: return None
        if isinstance(v, bool): return str(v).lower()
        return str(v)
    out = {
        "height":          s(row.get("height_mm") or row.get("height") or row.get("hauteur")),
        "width":           s(row.get("width_mm")  or row.get("width")  or row.get("largeur")),
        "quantity":        s(row.get("quantity") or row.get("quantite") or row.get("qty")),
        "confidence":      float(row.get("confidence") or 0.85),
        "reference":       row.get("reference"),
        "repere":          row.get("repere"),
        "verre1":          row.get("verre1"),
        "intercalaire":    row.get("intercalaire"),
        "remplissage":     row.get("remplissage"),
        "verre2":          row.get("verre2"),
        "façonnage_arete": row.get("façonnage_arete") or row.get("faconnage_arete") or row.get("faconnage"),
        "source":          source,
    }
    for opt in ("verre3", "intercalaire2", "remplissage2"):
        v = row.get(opt)
        if v is not None:
            out[opt] = v
    return out


def apply_factory_normalization(row: dict, factory_id: int) -> dict:
    """Enforce factory-specific defaults that selfservice may not apply."""
    f = factory(factory_id)
    r = dict(row)
    if f["spacer_color"]:
        for fld in ("intercalaire", "intercalaire2"):
            v = r.get(fld)
            if isinstance(v, str) and v and not any(
                    c in v.lower() for c in ("blanc", "noir", "gris", "brun")):
                r[fld] = f"{v} {f['spacer_color']}".strip()
    if f["default_gas"] and not r.get("remplissage"):
        r["remplissage"] = f["default_gas"]
    return r


# ─────────────────────────────────────────────────────────────────────
# THE ONE CLASS — Extract
# ─────────────────────────────────────────────────────────────────────

class Extract(dict):
    """Memory-augmented extraction with factory-aware field matching.

    Returns a dict that's identical in shape to ``POST /extract`` on
    ``claude.aws.monce.ai`` v3.10, so the caller can drop us in as a
    local replacement and the downstream UI stays unchanged.

        ex = Extract("quote.pdf", factory_id=4, user_id="7a3f9b2c")
        ex["extracted_data"]["value"]["measurements"]
        ex["extracted_data"]["client_matching"]
        ex["metadata"]["routing_decision"]
    """

    def __new__(cls, sources: Any, *,
                factory_id: int = 3,
                user_id: str = "anon",
                industry: str = "glass",
                auto_memory: bool = False,
                vocal: bool = True,
                notify: bool = False) -> "Extract":
        t0 = time.perf_counter()
        src_list = sources if isinstance(sources, list) else [sources]
        src_list = [str(s) if isinstance(s, Path) else s for s in src_list]

        if vocal:
            print(f"\n[extract] factory={factory_id} "
                  f"user_id={user_id} docs={len(src_list)}", file=sys.stderr)

        # ── Step 1 — recall prior memories so the extraction is primed ──
        ol = Outlook(user_id=user_id, auto_memory=auto_memory)
        try:
            prior = ol.recall(q=f"factory_{factory_id}", limit=10)
            prior_memories = [m.get("text") or "" for m in prior if m.get("text")]
        except Exception as e:
            if vocal: print(f"[outlook recall] {e}", file=sys.stderr)
            prior_memories = []

        # ── Step 2 — fire Extraction (the heavy lift) per source ──
        per_doc: list[dict] = []
        context = context_prompt(factory_id, prior_memories)
        for i, src in enumerate(src_list):
            name = _source_name(src, i)
            if vocal:
                print(f"\n[doc {i+1}/{len(src_list)}] {name}", file=sys.stderr)
            t = time.perf_counter()
            try:
                sfs = Extraction(
                    source=src, user_id=user_id,
                    industry=industry, context=context,
                    auto_memory=auto_memory,
                )
            except Exception as e:
                if vocal: print(f"[selfservice] {e}", file=sys.stderr)
                per_doc.append({
                    "name": name, "lines": [], "client": {},
                    "trust": {"score": 0, "routing": "ERROR"},
                    "header": {}, "errors": [str(e)], "elapsed_ms": 0,
                })
                continue
            if vocal:
                print(f"  selfservice: task={sfs.task_id} "
                      f"lines={len(sfs.lines)} trust={sfs.trust.get('score')} "
                      f"insights={len(sfs.insights)} "
                      f"{int((time.perf_counter()-t)*1000)}ms",
                      file=sys.stderr)
            per_doc.append({
                "name":       name,
                "lines":      sfs.lines,
                "client":     sfs.client,
                "trust":      sfs.trust,
                "header":     sfs.header,
                "insights":   sfs.insights,
                "prior":      sfs.prior_memories,
                "task_id":    sfs.task_id,
                "elapsed_ms": sfs.duration_ms,
                "errors":     [],
            })

        # ── Step 3 — per-doc upgrade (factory normalization + Matching) ──
        for d in per_doc:
            d["lines"] = [apply_factory_normalization(r, factory_id)
                          for r in d["lines"]]
            d["matches"] = upgrade_matches(d["lines"], factory_id=factory_id)
            d["client_matched"] = upgrade_client(d["client"], factory_id=factory_id)

        # ── Step 4 — cross-doc synthesis (Json merge for >1 doc) ──
        synth = cls._synthesize(per_doc, factory_id=factory_id)

        # ── Step 5 — aggregate trust + reshape to /extract payload ──
        payload = cls._assemble(per_doc, synth, factory_id=factory_id,
                                user_id=user_id, t0=t0)

        # ── Step 6 — remember this run on the Outlook side ──
        try:
            ed = payload["extracted_data"]
            ol.remember(
                text=(f"factory={factory_id} docs={len(per_doc)} "
                      f"rows={len(ed['value']['measurements'])} "
                      f"trust={ed['confidence']:.2f} "
                      f"route={payload['metadata']['routing_decision']}"),
                source="extract_pipeline",
                tags=["extraction", f"factory_{factory_id}",
                      payload["metadata"]["routing_decision"]],
            )
        except Exception as e:
            if vocal: print(f"[outlook remember] {e}", file=sys.stderr)

        inst = super().__new__(cls)
        dict.__init__(inst, payload)
        inst._factory_id = factory_id
        inst._user_id = user_id
        inst._outlook = ol
        if notify:
            try: cls._notify(payload)
            except Exception as e:
                print(f"[concierge] {e}", file=sys.stderr)
        return inst

    def __init__(self, *a, **kw): pass

    # ── Accessors on the prod shape ────────────────────────────────

    @property
    def factory_id(self) -> int: return self._factory_id
    @property
    def user_id(self) -> str:    return self._user_id
    @property
    def outlook(self) -> Outlook: return self._outlook

    @property
    def measurements(self) -> list[dict]:
        return ((self.get("extracted_data") or {}).get("value") or {}) \
            .get("measurements") or []

    @property
    def client_matching(self) -> dict:
        return (self.get("extracted_data") or {}).get("client_matching") or {}

    @property
    def trust(self) -> float:
        return float((self.get("extracted_data") or {}).get("confidence") or 0.0)

    @property
    def route(self) -> str:
        return (self.get("metadata") or {}).get("routing_decision") or "pending"

    # ── Feedback passthrough (Outlook layer) ───────────────────────

    def accept(self, note: str | None = None) -> dict:
        return self._outlook.remember(
            f"ACCEPTED {self.get('extraction_id')} " + (note or ""),
            source="extract_pipeline",
            tags=["feedback", "accept"],
        )

    def reject(self, reason: str | None = None) -> dict:
        return self._outlook.remember(
            f"REJECTED {self.get('extraction_id')} " + (reason or ""),
            source="extract_pipeline",
            tags=["feedback", "reject"],
        )

    # ── Internals ──────────────────────────────────────────────────

    @staticmethod
    def _synthesize(per_doc: list[dict], *, factory_id: int) -> dict:
        t0 = time.perf_counter()
        if not per_doc:
            return {"measurements": [], "conflicts": [],
                    "duplicates_removed": 0, "synthesis_time_ms": 0}
        if len(per_doc) == 1:
            d = per_doc[0]
            return {
                "measurements":       [to_measurement(r, d["name"])
                                       for r in d["lines"]],
                "conflicts":          [],
                "duplicates_removed": 0,
                "synthesis_time_ms":  round((time.perf_counter() - t0) * 1000),
            }
        payload = [{"source": d["name"], "rows": d["lines"]}
                   for d in per_doc]
        try:
            merged = dict(Json(synthesis_prompt(payload)))
            rows = merged.get("merged_rows") or []
            if not rows: raise ValueError("no merged_rows")
            return {
                "measurements": [
                    to_measurement(r, r.get("source") or per_doc[0]["name"])
                    for r in rows if isinstance(r, dict)
                ],
                "conflicts":          merged.get("conflicts", []),
                "duplicates_removed": int(merged.get("duplicates_removed", 0)),
                "synthesis_time_ms":  round((time.perf_counter() - t0) * 1000),
            }
        except Exception:
            measurements = [to_measurement(r, d["name"])
                            for d in per_doc for r in d["lines"]
                            if isinstance(r, dict)]
            return {
                "measurements":       measurements,
                "conflicts":          [],
                "duplicates_removed": 0,
                "synthesis_time_ms":  round((time.perf_counter() - t0) * 1000),
            }

    @staticmethod
    def _assemble(per_doc: list[dict], synth: dict, *,
                  factory_id: int, user_id: str, t0: float) -> dict:
        measurements = synth["measurements"]
        primary = per_doc[0] if per_doc else None

        # Trust aggregation — row-weighted across docs.
        total_rows = sum(max(len(d["lines"]), 1) for d in per_doc) or 1
        agg_trust = sum(
            (d["trust"].get("score", 0) / 100.0) * max(len(d["lines"]), 1)
            for d in per_doc
        ) / total_rows
        # Blend in matching confidence (20% client / 80% articles, per prod)
        if primary:
            cc = float(primary["client_matched"].get("confidence") or 0.0)
            acs = [m["confidence"] for d in per_doc for m in d["matches"]]
            avg_m = sum(acs) / len(acs) if acs else 0.0
            matching_trust = 0.20 * cc + 0.80 * avg_m
            agg_trust = 0.5 * agg_trust + 0.5 * matching_trust

        any_errors = any(d["errors"] for d in per_doc)
        route = "auto_approved" if agg_trust >= 0.90 and not any_errors \
            else "human_review"

        value = {
            "project_title":  (primary or {}).get("header", {}).get("project_title"),
            "measurements":   measurements,
            "client_infos":   _client_infos(primary),
            "demand_infos":   (primary or {}).get("header") or {},
            "unit_detection": {
                "detected_unit":
                    (primary or {}).get("header", {}).get("unit", "mm"),
                "mul_by":     1.0,
                "confidence": 0.9,
            },
        }
        matching = _matching_by_row(per_doc)
        client_matching = _client_matching(primary)

        client_name = (primary or {}).get("client_matched", {}).get("nom_matched") \
            or "unknown client"
        try:
            agent_summary = str(Charles(narration_prompt(
                factory_id, len(per_doc), len(measurements),
                client_name, len(synth["conflicts"]))))
        except Exception:
            agent_summary = (f"Processed {len(per_doc)} document(s) for "
                             f"{client_name}, {len(measurements)} rows.")

        handle_meta = {
            "total_files":        len(per_doc),
            "processed_files":    sum(1 for d in per_doc if not d["errors"]),
            "failed_files":       sum(1 for d in per_doc if d["errors"]),
            "failed_filenames":   [d["name"] for d in per_doc if d["errors"]],
            "sources":            [d["name"] for d in per_doc],
            "agent_turns":        0,
            "agent_summary":      agent_summary,
            "conflicts_resolved": len(synth["conflicts"]),
            "duplicates_removed": synth["duplicates_removed"],
            "email_content_used": False,
            "synthesis_time_ms":  synth["synthesis_time_ms"],
            "prior_memories":     (primary or {}).get("prior") or [],
            "insights":           (primary or {}).get("insights") or [],
            "selfservice_task_ids": [d.get("task_id") for d in per_doc
                                     if d.get("task_id")],
        }
        extraction_id = str(uuid.uuid4())
        return {
            "extraction_id":  extraction_id,
            "status":         "completed",
            "extracted_data": {
                "value":             value,
                "matching":          matching,
                "client_matching":   client_matching,
                "confidence":        round(agg_trust, 4),
                "status":            route,
                "_handle_metadata":  handle_meta,
                "trust_score":       int(round(agg_trust * 100)),
                "has_stage8":        False,
                "trust_improvement": None,
            },
            "metadata": {
                "factory_id":       factory_id,
                "user_id":          user_id,
                "pipeline_version": PIPELINE_VERSION,
                "stages_completed": 7,
                "model_mode":       "balanced",
                "prompt_profile":   factory(factory_id)["profile"],
                "latency_ms":       round((time.perf_counter() - t0) * 1000),
                "routing_decision": route,
                "total_files":      len(per_doc),
                "processed_files":  sum(1 for d in per_doc if not d["errors"]),
                "extraction_id":    extraction_id,
                "mode":             "multi" if len(per_doc) > 1 else "single",
            },
            "error": None,
        }

    @staticmethod
    def _notify(payload: dict) -> None:
        ed, meta = payload["extracted_data"], payload["metadata"]
        Concierge.remember(
            f"extract_pipeline factory={meta['factory_id']} "
            f"id={payload['extraction_id']} "
            f"rows={len(ed['value']['measurements'])} "
            f"trust={ed['confidence']:.2%} route={meta['routing_decision']}",
            source="extract_pipeline",
            tags=["extraction", meta["routing_decision"]],
        )


# ─────────────────────────────────────────────────────────────────────
# small helpers
# ─────────────────────────────────────────────────────────────────────

def _source_name(src: Any, i: int) -> str:
    if isinstance(src, (str, Path)):
        return os.path.basename(str(src))
    if isinstance(src, tuple) and len(src) == 2:
        return str(src[0])
    return f"source_{i}"


def _client_infos(d: dict | None) -> dict:
    if not d:
        return {"nom": None, "logo_text": None, "raison_social": "",
                "siret_siren": "", "rcs": "", "email": None,
                "telephone": None, "adresse": None,
                "contact_name": None, "numero_client": None}
    c = d["client_matched"]
    return {
        "nom":           c.get("nom_extracted"),
        "logo_text":     c.get("logo_text"),
        "raison_social": c.get("raison_sociale") or "",
        "siret_siren":   c.get("siret") or "",
        "rcs":           "",
        "email":         c.get("email"),
        "telephone":     c.get("telephone"),
        "adresse":       c.get("adresse"),
        "contact_name":  c.get("contact_name"),
        "numero_client": c.get("numero_client"),
    }


def _client_matching(d: dict | None) -> dict:
    if not d:
        return {"numero_client": None, "nom": None, "confidence": 0.0}
    c = d["client_matched"]
    return {
        "numero_client": c.get("numero_client"),
        "nom":           c.get("nom_matched"),
        "confidence":    float(c.get("confidence") or 0.0),
    }


def _matching_by_row(per_doc: list[dict]) -> dict:
    out: dict[str, dict[str, dict]] = {}
    offset = 0
    for d in per_doc:
        for local in range(len(d["lines"])):
            out.setdefault(str(offset + local + 1), {})
        for m in d["matches"]:
            gi = str(offset + (m.get("row") or 0) + 1)
            out.setdefault(gi, {})
            out[gi][m["field"]] = {
                "num_article":  m.get("num_article"),
                "denomination": m.get("denomination"),
                "suggested":    m.get("method") == "haiku_fallback",
                "confidence":   round(float(m.get("confidence") or 0.0), 4),
                "method":       m.get("method") or "snake",
            }
        offset += len(d["lines"])
    return out


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sources", nargs="+")
    ap.add_argument("--factory",     type=int, default=3)
    ap.add_argument("--user-id",     default="anon")
    ap.add_argument("--industry",    default="glass")
    ap.add_argument("--auto-memory", action="store_true")
    ap.add_argument("--json",        action="store_true")
    ap.add_argument("--notify",      action="store_true")
    args = ap.parse_args()

    ex = Extract(args.sources, factory_id=args.factory,
                 user_id=args.user_id, industry=args.industry,
                 auto_memory=args.auto_memory, notify=args.notify)

    print("\n" + "=" * 72)
    print(f"FACTORY {ex.factory_id}  ({factory(ex.factory_id)['name']})")
    print(f"trust: {ex.trust:.2%}   route: {ex.route}")
    print(f"rows:  {len(ex.measurements)}")
    print(f"client: {ex.client_matching}")

    if args.json:
        print("\n--- JSON ---")
        print(json.dumps(dict(ex), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
