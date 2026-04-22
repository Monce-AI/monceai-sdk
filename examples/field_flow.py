"""Monce Field V1 — MonceOS demo, real RIOU data.

Runs against https://monceapp.aws.monce.ai (live, no mocks) using clients and
articles pulled from the actual factory 4 (VIP / RIOU Glass) database via
data.aws.monce.ai.

Each section maps to one of the 6 pains from docs/product/01-master-pain.md
in the monce-fa engineering brief.

    pip install -e /Users/charlesdana/Documents/monceai
    python examples/field_flow.py

Real factory 4 clients used below (from Matching against snake.aws):
    - ACTIF PVC (#55298)
    - SARL GIRARD JEAN-MARIE (#90189)
    - EVM N.V. (#6920)

Real factory 4 articles:
    - 44.2 rTherm (#63442)
    - 16 TPS noir (#99190)
    - Gaz Argon (#12000)

Expected wall time: ~30-40s (one charles-json extraction + matching + agents).
"""

from __future__ import annotations

import time

from monceai import (
    MonceOS,
    Matching,
    Calc,
    Concierge,
    Moncey,
)


def section(title: str) -> None:
    print()
    print("=" * 78)
    print(f"  {title}")
    print("=" * 78)


# ─────────────────────────────────────────────────────────────────────────────
# ONE CONSTRUCTOR — factory_id, tenant, framework_id bound for the session.
# ─────────────────────────────────────────────────────────────────────────────
section("MonceOS — one constructor, bound scope")

os = MonceOS(
    factory_id=4,                       # VIP / RIOU Glass
    tenant="riou",
    framework_id="field_riou_test",     # 5-extraction CR schema
)
print(os)


# Real factory 4 client: ACTIF PVC (#55298). Real article: 44.2 rTherm (#63442).
# Real pain from RIOU's comment feed (data.aws.monce.ai): MANQUE PLUSIEURS LIGNES,
# ERREUR INTERCALAIRE, AA manquant — reported by Mélanie HAROU, Sylvain Cazalet,
# Victoria LECOQ. The transcript references these same issues.
TRANSCRIPT = """
Visite chez ACTIF PVC ce matin. J'ai vu Jean-Marc Girard, le responsable achats,
un ancien. Il veut un devis pour du 44.2 rTherm avec intercalaire 16 TPS noir,
environ 18 500 euros sur 95 metres carres, pour vendredi prochain au plus tard.
Il m'a aussi dit que sur les dernieres commandes ils avaient eu des problemes
d'intercalaire qui manquait — il faudrait qu'on regarde avec la production.
J'ai rencontre pour la premiere fois Stephanie Bernard, la nouvelle assistante
commerciale, tres sympa. Ambiance positive, ils veulent qu'on reparle des
faconnages AA la semaine prochaine.
""".strip()


# ═════════════════════════════════════════════════════════════════════════════
# PAIN 1 — "Field reps don't fill the CRM"
#   Rep speaks 2 minutes. MonceOS structures.
# ═════════════════════════════════════════════════════════════════════════════
section("Pain 1 — the rep talks, we structure")

t = time.time()
cr = os.capture(transcript=TRANSCRIPT, today="2026-04-22", visit_id="v-actif-pvc-001")
print(f"capture: {time.time() - t:.1f}s  (model={cr.model})")
print(f"sentiment: {cr.sentiment}")
print(f"summary: {cr.summary}")
print()
print(f"next_step: what={cr.next_step.what!r}")
print(f"           when={cr.next_step.when!r}")


# ═════════════════════════════════════════════════════════════════════════════
# PAIN 3 — "Actions taken in the visit never reach the back office"
#   Each action → owner_team + deadline + priority + amount.
# ═════════════════════════════════════════════════════════════════════════════
section("Pain 3 — every action is routable")

print(f"{'OWNER':<12} {'PRIORITY':<8} {'DEADLINE':<12} {'AMOUNT EUR':>10}  DESCRIPTION")
print("-" * 78)
for a in cr.actions:
    amt = f"{a.amount_eur:.0f}" if a.amount_eur else "—"
    print(f"{a.owner_team:<12} {a.priority:<8} {str(a.deadline):<12} {amt:>10}  {a.description[:45]}")


# ═════════════════════════════════════════════════════════════════════════════
# AMOUNTS — NP-verified arithmetic. Calc, not the LLM.
# ═════════════════════════════════════════════════════════════════════════════
section("Amounts — NP-verified, not guessed")

for a in cr.actions:
    if a.amount_eur:
        ht = a.amount_eur
        ttc = float(Calc(f"{ht}x1.20"))
        print(f"  {a.description[:40]:<40}  HT={ht:>8}  TTC={ttc:>8.2f}")
    else:
        print(f"  {a.description[:40]:<40}  (no amount)")


# ═════════════════════════════════════════════════════════════════════════════
# PAIN 2 — "Reps discover an account 5 minutes before a visit"
#   Client resolution against the real factory 4 table.
# ═════════════════════════════════════════════════════════════════════════════
section("Pain 2 — client resolved against the factory table")

m_client = Matching("ACTIF PVC", factory_id=4)
print(f"Account lookup : ACTIF PVC")
print(f"  numero_client: {m_client.get('numero_client')}")
print(f"  nom canonique: {m_client.get('nom')}")
print(f"  confidence   : {m_client.get('confidence')}")
print(f"  method       : {m_client.get('method')}")


# ═════════════════════════════════════════════════════════════════════════════
# Article matching — real factory 4 catalog
# ═════════════════════════════════════════════════════════════════════════════
section("Article catalog — real factory 4 articles")

queries = [
    ("44.2 rTherm",   "verre"),
    ("16 TPS noir",   "intercalaire"),
    ("Argon",         "remplissage"),
]
print(f"{'QUERY':<15} {'FIELD':<14} {'#ARTICLE':<10} {'DENOMINATION':<35} CONF")
print("-" * 78)
for q, fld in queries:
    m = Matching(q, field=fld, factory_id=4)
    print(f"{q:<15} {fld:<14} {str(m.get('num_article')):<10} "
          f"{str(m.get('denomination'))[:35]:<35} {m.get('confidence')}")


# ═════════════════════════════════════════════════════════════════════════════
# PAIN 4 — "Directors fly blind"
#   One stable JSON shape → trivial aggregation.
# ═════════════════════════════════════════════════════════════════════════════
section("Pain 4 — one CR shape, dashboard-ready")

payload = cr.to_json()
print(payload)
print()
print(f"(payload size: {len(payload)} bytes, tenant={cr.tenant!r}, factory={cr.factory_id})")


# ═════════════════════════════════════════════════════════════════════════════
# PAIN 5 — "Rep turnover costs 6 months"
#   Every CR is tenant-scoped + persistent (iter 5 adds S3).
# ═════════════════════════════════════════════════════════════════════════════
section("Pain 5 — tenant-scoped memory")

print(f"  tenant      : {cr.tenant}")
print(f"  factory_id  : {cr.factory_id}")
print(f"  visit_id    : {cr.visit_id}")
print(f"  created_at  : {cr.created_at}")
print()
print("  On iter 5 (os.store.*), every CR writes to:")
print(f"    s3://<bucket>/{cr.tenant}/factory-{cr.factory_id}/cr/{cr.visit_id}.json")
print("  New rep opens the ACTIF PVC folder on day 1. Memory stays.")


# ═════════════════════════════════════════════════════════════════════════════
# PAIN 6 — "The CRM is a €100-250/seat tax"
#   The rep filled zero fields.
# ═════════════════════════════════════════════════════════════════════════════
section("Pain 6 — zero fields filled")

print("  Fields touched by the rep : 0")
print("  Minutes of data entry     : 0")
print(f"  Structured outputs        : {1 + len(cr.actions) + len(cr.contacts_met)} "
      f"(1 summary + {len(cr.actions)} actions + {len(cr.contacts_met)} contacts)")


# ═════════════════════════════════════════════════════════════════════════════
# BONUS — Concierge doubles down on Pain 5: Q&A over the account's memory.
# When a rep leaves, the replacement opens the account and asks:
#   "what did we promise ACTIF PVC?" — memory answers.
# ═════════════════════════════════════════════════════════════════════════════
section("Bonus — Moncey (glass domain) + Concierge (account memory)")

t = time.time()
glass = Moncey("44.2 rTherm/16 TPS noir/4 Float", factory_id=4)
print(f"Moncey ({time.time()-t:.1f}s) — glass domain decoder:")
print(str(glass))
print()

t = time.time()
kb = Concierge(
    "What are the recent issues reported on factory 4 VIP extractions? "
    "Anything about intercalaire or missing lines?"
)
print(f"Concierge ({time.time()-t:.1f}s) — Q&A over factory 4 memory:")
print(str(kb))


# ═════════════════════════════════════════════════════════════════════════════
# THE FOUR LINES — what Field's backend actually needs to write.
# ═════════════════════════════════════════════════════════════════════════════
section("The four lines — Field V1 AI stack in full")

print("""
    from monceai import MonceOS

    os = MonceOS(factory_id=4, tenant='riou', framework_id='field_riou_test')
    cr = os.capture(transcript=stt_output)         # ~10s, typed, validated
    for a in cr.actions: route_to_team(a)          # enum → inbox
    save_to_s3(cr.to_json())                       # tenant-scoped, permanent

    # Everything else in the Field repo is plumbing:
    #   Postgres schema · S3 bucket · PWA screens · Cognito · SES email
""")

print("=" * 78)
print("  Demo complete.")
print("=" * 78)
