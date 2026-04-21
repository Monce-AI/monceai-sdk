#!/usr/bin/env python3
"""extraction_quickstart.py — live tour of the v1.2.0 Extraction + Outlook API.

Runs six recipes against selfservice.aws.monce.ai, using a PDF path passed
on the CLI (or a sensible built-in fallback). Each recipe prints what it
did + what came back — no asserts, just a guided demo.

Usage:
    python examples/extraction_quickstart.py [path/to/file.pdf]

Environment:
    SELFSERVICE_ENDPOINT  default https://selfservice.aws.monce.ai
    QUICKSTART_USER_ID    default "quickstart"
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from monceai import Extraction, Outlook, Matching

ENDPOINT = os.environ.get("SELFSERVICE_ENDPOINT", "https://selfservice.aws.monce.ai")
USER_ID = os.environ.get("QUICKSTART_USER_ID", "quickstart")


def banner(n: int, title: str) -> None:
    print("\n" + "=" * 72)
    print(f" RECIPE {n} — {title}")
    print("=" * 72)


def recipe_1_single(pdf: Path) -> Extraction:
    """One PDF through the full reflex loop + independent Matching cross-check."""
    banner(1, "One-shot Extraction with auto_memory")

    ex = Extraction(
        pdf,
        user_id=USER_ID,
        industry="glass",
        email_subject=f"Quickstart: {pdf.name}",
        email_body="Please extract this document.",
        auto_memory=True,
        endpoint=ENDPOINT,
    )

    print(f"\nSHAPE")
    print(f"  isinstance(ex, dict) = {isinstance(ex, dict)}")
    print(f"  task_id              = {ex.task_id}")
    print(f"  duration_ms          = {ex.duration_ms}")

    print(f"\nEXTRACTED")
    print(f"  vertical             = {ex.result.get('vertical')}")
    print(f"  client               = {(ex.client or {}).get('name')}")
    print(f"  trust                = {ex.trust.get('score')} "
          f"({ex.trust.get('routing')})")
    print(f"  lines                = {len(ex.lines)}")

    if ex.insights:
        print(f"\nINSIGHTS (distilled by Haiku, written back to memory)")
        for b in ex.insights:
            print(f"  • {b}")

    if ex.prior_memories:
        print(f"\nPRIOR MEMORIES (auto-recalled before this extraction)")
        for m in ex.prior_memories:
            print(f"  • {m[:100]}")

    # Independent cross-check via the matching service.
    client_name = (ex.client or {}).get("name")
    if client_name:
        try:
            cross = Matching(client_name, factory_id=4, timeout=15)
            print(f"\nCROSS-CHECK (independent Matching call)")
            print(f"  monceai.Matching('{client_name}', factory_id=4)")
            print(f"    → {cross.get('nom') or cross.get('name')} "
                  f"#{cross.get('numero_client')} conf={cross.get('confidence')}")
        except Exception as e:
            print(f"\nCROSS-CHECK skipped: {e}")

    return ex


def recipe_2_feedback(ex: Extraction) -> None:
    """Feedback persists and shows up in memory."""
    banner(2, "Feedback — accept / reject / correct / note")

    entry = ex.accept(note="Quickstart: automated acceptance")
    print(f"\n  .accept(note=...) → stored memory entry tagged 'feedback':")
    print(f"    {entry['entry']['text']}")

    ol = Outlook(user_id=USER_ID, endpoint=ENDPOINT)
    feedback_mems = ol.memories(tag="feedback", limit=5)
    print(f"\n  Outlook.memories(tag='feedback') → {len(feedback_mems)} entries")


def recipe_3_outlook_ops(pdf: Path) -> None:
    """Outlook reflex loop — memory compounds as you run extractions."""
    banner(3, "Outlook reflex — remember / recall / extract_email")

    ol = Outlook(user_id=USER_ID, auto_memory=True, endpoint=ENDPOINT)

    before = ol.stats()
    print(f"\nBEFORE: memories={before['memories']}  "
          f"extractions={before['extractions']}  "
          f"conversations={before['conversations']}")

    # Record a domain preference the next extraction will recall.
    ol.remember(
        "Quickstart user prefers compact output and AUTO_APPROVE when possible",
        tags=["preference", "quickstart"],
    )

    # Extract — email subject hints the recall.
    ol.extract_email(
        attachments=[pdf],
        subject="Quickstart compact output run",
        body="Shorter is better.",
    )

    hits = ol.recall("compact output", limit=3)
    print(f"\nRECALL ('compact output') → {len(hits)} hits")
    for h in hits[:2]:
        print(f"  • {h.get('text', '')[:100]}")

    after = ol.stats()
    print(f"\nAFTER:  memories={after['memories']}  "
          f"extractions={after['extractions']}  "
          f"conversations={after['conversations']}")


def recipe_4_parallel(pdfs: list[Path]) -> None:
    """Parallel extractions with ThreadPoolExecutor, max_workers=4."""
    if len(pdfs) < 2:
        print("\n(recipe 4 skipped — needs ≥2 PDFs, pass more paths on the CLI)")
        return

    banner(4, "Parallel throughput — ThreadPoolExecutor(max_workers=4)")

    import concurrent.futures as cf
    import time

    def run_one(path, idx):
        return Extraction(
            path,
            user_id=f"{USER_ID}_p{idx}",
            industry="glass",
            auto_memory=False,       # keep parallel run memory-quiet
            endpoint=ENDPOINT,
            timeout=240,
        )

    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(run_one, p, i) for i, p in enumerate(pdfs[:4])]
        results = [f.result() for f in futures]
    wall = time.time() - t0

    print(f"\n{len(results)} files, parallel=4, wall={wall:.1f}s")
    for ex in results:
        print(f"  {ex.filename:<30} trust={ex.trust.get('score'):<4} "
              f"{ex.trust.get('routing'):<14} {ex.duration_ms}ms")


def recipe_5_multifile(pdfs: list[Path]) -> None:
    """Multi-file synthesis — one Extraction call, many files, merged result."""
    if len(pdfs) < 2:
        print("\n(recipe 5 skipped — needs ≥2 PDFs, pass more paths on the CLI)")
        return

    banner(5, "Multi-file synthesis")

    ol = Outlook(user_id=f"{USER_ID}_multi", endpoint=ENDPOINT)
    ex = ol.extract_email(
        attachments=pdfs[:2],
        subject="Quickstart multi-file batch",
        body="Two files, one extraction call.",
    )

    source_files = {ln.get("_source_file") for ln in ex.lines if ln.get("_source_file")}
    print(f"\n  input files       = {[p.name for p in pdfs[:2]]}")
    print(f"  merged lines      = {len(ex.lines)}")
    print(f"  distinct sources  = {len(source_files)}")
    print(f"  metadata          = file_count={ex.result.get('metadata', {}).get('file_count')}")
    print(f"  trust             = {ex.trust.get('score')} ({ex.trust.get('routing')})")


def recipe_6_chat() -> None:
    """Chat — Sonnet grounded on this user's memory (no other context)."""
    banner(6, "Memory-grounded chat")

    ol = Outlook(user_id=USER_ID, endpoint=ENDPOINT)
    reply = ol.chat("In 2 sentences, what have I been extracting today?")

    print(f"\n  latency_ms = {reply.get('latency_ms')}")
    print(f"  reply:")
    for line in (reply.get("reply") or "").splitlines():
        print(f"    {line}")


def resolve_pdfs(argv: list[str]) -> list[Path]:
    """Pick up CLI paths or fall back to a curated set we know works."""
    if len(argv) > 1:
        return [Path(p).expanduser().resolve() for p in argv[1:] if Path(p).exists()]

    fallbacks = [
        "~/Documents/Previous/MonceAi/PDFs/RIOU-VIN.pdf",
        "~/Documents/Previous/MonceAi/PDFs/RIOU-VIB.pdf",
    ]
    return [Path(p).expanduser() for p in fallbacks if Path(p).expanduser().exists()]


def main() -> int:
    pdfs = resolve_pdfs(sys.argv)
    if not pdfs:
        print("ERROR: no PDF found.\n"
              "Usage: python examples/extraction_quickstart.py <file.pdf> [more.pdf ...]")
        return 1

    print(f"Endpoint  : {ENDPOINT}")
    print(f"User ID   : {USER_ID}")
    print(f"PDFs      : {[p.name for p in pdfs]}")

    ex = recipe_1_single(pdfs[0])
    recipe_2_feedback(ex)
    recipe_3_outlook_ops(pdfs[0])
    recipe_4_parallel(pdfs)
    recipe_5_multifile(pdfs)
    recipe_6_chat()

    print("\n" + "=" * 72)
    print(f" DONE — inspect live at {ENDPOINT}/ui (enter user_id '{USER_ID}')")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
