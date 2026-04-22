"""
monceai.Matching — universal client & article resolver.

Source of truth:
    snake.aws.monce.ai/batch          (articles, single + array)
    snake.aws.monce.ai/batch_client   (clients, single + array)
    claude.aws.monce.ai/stage_0       (PDF / image / email → client)

Constructor-to-resolution: ``Matching(arg, ...)`` blocks and IS the result.
The only deferred form is ``Matching(factory_id=...)`` (no query) which
returns a reusable client that fires parallel futures.

    from monceai import Matching

    # single article
    r = Matching("44.2 rTherm", factory_id=4, field="verre")
    r["num_article"], r["confidence"], r["method"]

    # array article — one /batch call, results in input order
    rs = Matching(["44.2 rTherm", "4/16/4"], factory_id=4, field="verre")
    rs[0]["num_article"]

    # client by free text (auto-parses nom/siret/email/…)
    Matching("LGB Menuiserie SAS, SIRET 552 100 554 00025", factory_id=4)

    # client by known fields
    Matching({"nom": "LGB", "email": "contact@lgb.fr"}, factory_id=4)

    # document → client (PDF / image / docx / eml / msg)
    Matching(Path("quote.pdf"), factory_id=4)

    # auto mode (no field, no kind) → heuristic + optional LLM router
    Matching("Riou Group", factory_id=4)            # → kind="client"
    Matching("44.2 rTherm WE noir", factory_id=4)   # → kind="article"

    # reusable client (deferred)
    m = Matching(factory_id=4)
    a = m("44.2 rTherm", field="verre")
    b = m("Riou")
    a["num_article"]; b["numero_client"]

    # accuracy assessment
    report = Matching.assess(pairs, factory_id=4)    # see assess()

Returns a dict subclass — indexing, ``**unpack``, ``json.dumps`` all work.
``.result`` carries the LLMResult (tokens, elapsed, raw, sat_memory).
"""

from __future__ import annotations

import json as _json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Optional, Tuple, Union

import requests

from .llm import LLMResult, _coerce_input, _report_usage


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints & constants
# ─────────────────────────────────────────────────────────────────────────────

SNAKE_URL = os.environ.get("SNAKE_AWS_URL", "https://snake.aws.monce.ai")
CLAUDE_URL = os.environ.get("CLAUDE_AWS_URL", "https://claude.aws.monce.ai")
CLAUDE_USER = os.environ.get("CLAUDE_AWS_USER", "monce")
CLAUDE_PASS = os.environ.get("CLAUDE_AWS_PASS", "Data@Monce")
MONCEAPP_URL = os.environ.get("MONCEAPP_URL", "https://monceapp.aws.monce.ai")
CONCIERGE_URL = os.environ.get("CONCIERGE_URL", "https://concierge.aws.monce.ai")
DEFAULT_TIMEOUT = 30
BATCH_TIMEOUT = 300                  # /batch is CPU-heavy on the server side
FILE_TIMEOUT = 180
BATCH_MAX = 500                       # split huge lists into server-friendly chunks
LLM_ARBITRATION_TIMEOUT = 8

CLIENT_FIELDS = (
    "nom", "logo_text", "raison_social", "siret_siren",
    "email", "adresse", "telephone", "numero_client",
)

ARTICLE_FIELDS = (
    "verre", "verre1", "verre2", "verre3",
    "intercalaire", "intercalaire1", "intercalaire2",
    "remplissage", "gaz",
    "faconnage", "façonnage_arete",
    "global",
)

# Extensions that route to /stage_0 multipart path
_DOC_EXTS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff",
    ".gif", ".bmp", ".docx", ".xlsx", ".xls", ".msg", ".eml",
}


# ─────────────────────────────────────────────────────────────────────────────
# Text heuristics for auto-routing (zero network, ~1ms)
# ─────────────────────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_SIRET_RE = re.compile(r"\b(?:\d[\s.-]?){9,14}\b")
_PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s.-]?)?"
    r"(?:\(?\d{1,4}\)?[\s.-]?)?"
    r"\d{2}[\s.-]?\d{2}[\s.-]?\d{2}[\s.-]?\d{2}"
)
_RCS_RE = re.compile(r"RCS\s+[A-Za-zÀ-ÿ-]+\s+[A-Z]?\s*\d[\d\s]*", re.IGNORECASE)

_PREAMBLE_RE = re.compile(
    r"^\s*(?:match\s+this\s+client|match|client|identify|find|who\s+is|"
    r"société|company)\s*[:\-—–]?\s*",
    re.IGNORECASE,
)
_LABEL_STRIP_RE = re.compile(
    r"\b(?:siret|siren|rcs|email|e-mail|tel|tél|téléphone|phone|"
    r"nom|client|raison\s+sociale|adresse)\s*[:\-]?\s*",
    re.IGNORECASE,
)
_COMPANY_SUFFIX_RE = re.compile(
    r"\b(?:SAS|SARL|SA|EURL|SNC|SCI|SCP|SASU|EIRL|GmbH|Ltd|LLC|Inc|"
    r"BV|SpA|AG|KG|OHG|SRL|EEIG|GIE|Coop|Coopérative)\b",
    re.IGNORECASE,
)
_MENUISERIE_WORDS = (
    "menuiserie", "miroiterie", "vitrerie",
    "aluminium", "aluminum", "bâtiment", "batiment",
    "construction", "industries", "industrie", "group", "groupe",
)
_STRONG_GLASS = (
    "rtherm", "rsun", "lowe", "low-e", "low e", "stadip", "antelio",
    "stopsol", "feuillet", "feuillete", "feuilleté",
    "tps", "thermix", "warm edge", "argon", "krypton",
)
_SINGLE_THICKNESS_RE = re.compile(r"^\s*\d{1,3}(?:[.,]\d)?\s*$")
_STACK_RE = re.compile(
    r"\b\d{1,3}(?:[.,]\d)?\s*/\s*\d{1,3}(?:[.,]\d)?\s*/\s*\d{1,3}(?:[.,]\d)?\b"
)
_DIM_ONLY_RE = re.compile(r"^\s*\d{1,3}(?:[.,]\d)?\s*(?:mm)?\s*$", re.IGNORECASE)


def _clean_digits(s: str) -> str:
    return re.sub(r"[\s.-]", "", s)


def parse_client_text(text: str) -> dict:
    """Free text → best-guess client fields {nom, email, siret_siren, telephone}.

    Pure-regex, no network. Used to shape /batch_client input and to
    sharpen re-ranking with side fields.
    """
    parsed: dict = {}
    remaining = _PREAMBLE_RE.sub("", text or "").strip()

    m = _EMAIL_RE.search(remaining)
    if m:
        parsed["email"] = m.group(0)
        remaining = remaining.replace(m.group(0), " ", 1)

    m = _RCS_RE.search(remaining)
    if m:
        parsed["rcs"] = m.group(0).strip()
        remaining = remaining.replace(m.group(0), " ", 1)

    m = _SIRET_RE.search(remaining)
    if m:
        digits = _clean_digits(m.group(0))
        if len(digits) in (9, 14):
            parsed["siret_siren"] = digits
            remaining = remaining.replace(m.group(0), " ", 1)

    m = _PHONE_RE.search(remaining)
    if m and len(_clean_digits(m.group(0))) >= 9:
        parsed["telephone"] = m.group(0).strip()
        remaining = remaining.replace(m.group(0), " ", 1)

    remaining = _LABEL_STRIP_RE.sub(" ", remaining)
    tokens = [t.strip(" -\t") for t in re.split(r"[/|,;\n]", remaining)
              if t.strip(" -\t")]
    if tokens:
        candidates = [t for t in tokens if re.search(r"[A-Za-zÀ-ÿ]", t)]
        nom = max(candidates, key=len) if candidates else tokens[0]
        nom = re.sub(r"\s*[-—]+\s*$", "", nom).strip()
        if nom:
            parsed["nom"] = nom
    return parsed


def looks_like_client(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    if _EMAIL_RE.search(t) or _RCS_RE.search(t):
        return True
    m = _SIRET_RE.search(t)
    if m and len(_clean_digits(m.group(0))) in (9, 14):
        return True
    m = _PHONE_RE.search(t)
    if m and len(_clean_digits(m.group(0))) >= 9:
        return True
    if _COMPANY_SUFFIX_RE.search(t):
        return True
    low = t.lower()
    if _STACK_RE.search(t) or any(s in low for s in _STRONG_GLASS):
        return False
    words = re.findall(r"[A-Za-zÀ-ÿ]+", t)
    if len(words) >= 2 and any(kw in low for kw in _MENUISERIE_WORDS):
        return True
    return False


def looks_like_article(text: str) -> bool:
    """Strong positive signal for an article: needs a glass marker or dims."""
    if not text:
        return False
    t = text.strip()
    if _SINGLE_THICKNESS_RE.match(t) or _DIM_ONLY_RE.match(t):
        return True
    if _STACK_RE.search(t):
        return True
    low = t.lower()
    if any(s in low for s in _STRONG_GLASS):
        return True
    return False


def classify(text: str) -> str:
    """Return 'client' | 'article' | 'ambiguous'. No network.

    Only commits to a kind when there is a *positive* signal. A bare short
    token like "RIOU" → "ambiguous" (triggers parallel race in auto mode),
    never silently defaulted to article.
    """
    is_c = looks_like_client(text)
    is_a = looks_like_article(text)
    if is_c and not is_a:
        return "client"
    if is_a and not is_c:
        return "article"
    return "ambiguous"


# ─────────────────────────────────────────────────────────────────────────────
# Upstream HTTP
# ─────────────────────────────────────────────────────────────────────────────

def _post(url: str, *, json_body: Optional[dict] = None,
          files=None, data=None, auth=None, timeout: int = DEFAULT_TIMEOUT) -> dict:
    try:
        resp = requests.post(url, json=json_body, files=files, data=data,
                             auth=auth, timeout=timeout)
        if resp.status_code != 200:
            return {"_error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        return resp.json()
    except requests.exceptions.Timeout:
        return {"_error": "timeout"}
    except Exception as e:
        return {"_error": str(e)}


def _batch_articles(texts: list[str], factory_id: int, field: str,
                    *, use_fuzzy: bool, top_k: int, snake_threshold: float,
                    use_llm: bool, timeout: int) -> list[dict]:
    """POST /batch — chunks automatically at BATCH_MAX."""
    results: list[dict] = []
    for i in range(0, len(texts), BATCH_MAX):
        chunk = texts[i:i + BATCH_MAX]
        payload = {
            "queries": [
                {"text": t, "row_id": str(i + j), "field_type": field}
                for j, t in enumerate(chunk)
            ],
            "factory_id": factory_id,
            "use_fuzzy": use_fuzzy,
            "use_llm": use_llm,
            "top_k": top_k,
            "snake_threshold": snake_threshold,
        }
        body = _post(f"{SNAKE_URL}/batch", json_body=payload,
                     timeout=max(timeout, BATCH_TIMEOUT))
        if body.get("_error"):
            for j, t in enumerate(chunk):
                results.append({"row_id": str(i + j), "query": t,
                                "match": None, "candidates": [],
                                "_error": body["_error"]})
            continue
        by_id = {str(r.get("row_id")): r for r in (body.get("results") or [])}
        for j, t in enumerate(chunk):
            rid = str(i + j)
            results.append(by_id.get(rid) or {"row_id": rid, "query": t,
                                              "match": None, "candidates": []})
    return results


def _batch_clients(texts: list[str], factory_id: int, *,
                   use_fuzzy: bool, top_k: int, snake_threshold: float,
                   mode: str, timeout: int) -> list[dict]:
    results: list[dict] = []
    for i in range(0, len(texts), BATCH_MAX):
        chunk = texts[i:i + BATCH_MAX]
        payload = {
            "queries": [{"text": t, "row_id": str(i + j)}
                        for j, t in enumerate(chunk)],
            "factory_id": factory_id,
            "top_k": top_k,
            "use_fuzzy": use_fuzzy,
            "snake_threshold": snake_threshold,
            "mode": mode,
        }
        body = _post(f"{SNAKE_URL}/batch_client", json_body=payload,
                     timeout=max(timeout, BATCH_TIMEOUT))
        if body.get("_error"):
            for j, t in enumerate(chunk):
                results.append({"row_id": str(i + j), "query": t,
                                "match": None, "candidates": [],
                                "_error": body["_error"]})
            continue
        by_id = {str(r.get("row_id")): r for r in (body.get("results") or [])}
        for j, t in enumerate(chunk):
            rid = str(i + j)
            results.append(by_id.get(rid) or {"row_id": rid, "query": t,
                                              "match": None, "candidates": []})
    return results


def _stage_0_file(file_bytes: bytes, filename: str, factory_id: int,
                  *, email_content: Optional[str] = None,
                  model_mode: str = "balanced",
                  timeout: int = FILE_TIMEOUT) -> dict:
    """POST /stage_0 with file → {client_matching, client_infos, candidates}."""
    files = {"file": (filename, file_bytes)}
    data = {"factory_id": str(factory_id), "model_mode": model_mode}
    if email_content:
        data["email_content"] = email_content
    return _post(f"{CLAUDE_URL}/stage_0", files=files, data=data,
                 auth=(CLAUDE_USER, CLAUDE_PASS), timeout=timeout)


# ─────────────────────────────────────────────────────────────────────────────
# Input coercion
# ─────────────────────────────────────────────────────────────────────────────

def _is_docish(arg: Any) -> Optional[Tuple[str, bytes]]:
    """Return (filename, bytes) if arg is a document path / bytes-like, else None.

    Documents = pdf/png/jpg/webp/tif/gif/bmp/docx/xlsx/xls/msg/eml.
    Plain strings that happen to be filenames don't trigger — we only match
    when the arg is a Path, bytes, file-like, or a string that exists on disk
    with a recognized extension.
    """
    # Path object
    if isinstance(arg, Path):
        if arg.suffix.lower() in _DOC_EXTS and arg.is_file():
            return arg.name, arg.read_bytes()
        return None
    # bytes with file-like signature (PDF %PDF-, PNG \x89PNG, etc.)
    if isinstance(arg, (bytes, bytearray)):
        head = bytes(arg[:8])
        if head.startswith(b"%PDF"):
            return "document.pdf", bytes(arg)
        if head.startswith(b"\x89PNG"):
            return "image.png", bytes(arg)
        if head.startswith(b"\xff\xd8\xff"):
            return "image.jpg", bytes(arg)
        if head.startswith(b"PK"):       # zip: docx/xlsx
            return "document.docx", bytes(arg)
        return None
    # file-like
    if hasattr(arg, "read"):
        data = arg.read()
        name = getattr(arg, "name", "upload.bin")
        if isinstance(data, bytes):
            return os.path.basename(str(name)), data
        return None
    # string: only treat as file if it exists on disk
    if isinstance(arg, str):
        if len(arg) < 1024 and os.path.exists(arg):
            ext = os.path.splitext(arg)[1].lower()
            if ext in _DOC_EXTS:
                with open(arg, "rb") as f:
                    return os.path.basename(arg), f.read()
        return None
    return None


# ─────────────────────────────────────────────────────────────────────────────
# LLM arbitration — parallel monceapp /v1/chat + concierge /chat on top-k
# ─────────────────────────────────────────────────────────────────────────────
#
# Fired only when local confidence lands in [llm_floor, 0.95). Below the floor
# the candidates are garbage — LLM can't rescue. At/above 0.95 snake is already
# sure — LLM is a tax. The sweet spot is the ambiguous middle.
#
# Both arbiters see the same prompt + top-k. They vote independently. Agreement
# locks the pick. Disagreement keeps the local rerank choice and surfaces the
# tie in the audit trail.

_ARB_PROMPT_ARTICLE = (
    "You arbitrate a glass-article match. The user extracted the text below "
    "from a document. Snake returned these candidates (ordered by its own "
    "confidence). Pick the single best num_article for the extracted text, "
    "or reply NONE if no candidate fits.\n"
    "\n"
    "Extracted: {query}\n"
    "Candidates:\n{choices}\n"
    "\n"
    "Reply with one token: the num_article, or NONE."
)

_ARB_PROMPT_CLIENT = (
    "You arbitrate a client match. The user extracted the text below from a "
    "document. Pick the single best numero_client, or reply NONE.\n"
    "\n"
    "Extracted: {query}\n"
    "Candidates:\n{choices}\n"
    "\n"
    "Reply with one token: the numero_client, or NONE."
)


def _format_choices(cands: list[dict], kind: str, limit: int = 8) -> str:
    lines = []
    for i, c in enumerate(cands[:limit]):
        if kind == "article":
            cid = c.get("num_article")
            label = c.get("denomination") or ""
        else:
            cid = c.get("numero_client")
            label = c.get("nom") or ""
        lines.append(f"  - {cid}: {label}")
    return "\n".join(lines)


_ID_RE = re.compile(r"[A-Za-z]*(\d+)")


def _extract_id(reply: str, cand_ids: set[str]) -> Optional[str]:
    """Pull the candidate ID out of a free-text LLM reply. Accepts numbers
    interleaved with markdown, quotes, or prose. Returns None on NONE / miss.
    """
    if not reply:
        return None
    if "NONE" in reply.upper():
        return None
    # Direct token match first (whitespace / punctuation delimited)
    for tok in re.split(r"[\s,;:.\"'`\-\[\]\(\)]+", reply):
        if tok in cand_ids:
            return tok
    # Numeric extraction fallback
    for m in _ID_RE.findall(reply):
        if m in cand_ids:
            return m
    return None


def _monceapp_vote(query: str, cands: list[dict], kind: str,
                   factory_id: int, timeout: int) -> Optional[str]:
    """POST monceapp /v1/chat (model=concise) with query + candidates.
    Returns the picked candidate ID or None.
    """
    prompt = (_ARB_PROMPT_ARTICLE if kind == "article"
              else _ARB_PROMPT_CLIENT).format(
        query=query, choices=_format_choices(cands, kind),
    )
    try:
        r = requests.post(
            f"{MONCEAPP_URL}/v1/chat",
            data={"message": prompt,
                  "model_id": "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
                  "factory_id": str(factory_id), "lang": "en"},
            timeout=timeout,
        )
        if r.status_code != 200:
            return None
        body = r.json()
        reply = (body.get("reply") or body.get("text")
                 or body.get("response") or "")
    except Exception:
        return None
    cand_ids = {str(c.get("num_article") if kind == "article"
                    else c.get("numero_client"))
                for c in cands if (c.get("num_article") or c.get("numero_client"))}
    return _extract_id(reply, cand_ids)


def _concierge_vote(query: str, cands: list[dict], kind: str,
                    timeout: int) -> Optional[str]:
    """POST concierge /chat — it has the glass knowledge base."""
    prompt = (_ARB_PROMPT_ARTICLE if kind == "article"
              else _ARB_PROMPT_CLIENT).format(
        query=query, choices=_format_choices(cands, kind),
    )
    try:
        r = requests.post(
            f"{CONCIERGE_URL}/chat",
            json={"message": prompt},
            timeout=timeout,
        )
        if r.status_code != 200:
            return None
        reply = (r.json() or {}).get("reply") or ""
    except Exception:
        return None
    cand_ids = {str(c.get("num_article") if kind == "article"
                    else c.get("numero_client"))
                for c in cands if (c.get("num_article") or c.get("numero_client"))}
    return _extract_id(reply, cand_ids)


def _arbitrate_batch(shaped: list[dict], kind: str, factory_id: int,
                     floor: float, ceiling: float,
                     timeout: int = LLM_ARBITRATION_TIMEOUT,
                     max_workers: int = 24) -> None:
    """In-place patch of shaped rows whose confidence is in [floor, ceiling).

    Runs LLM arbitrations in parallel and mutates each row's id, confidence,
    method, tier. Rows outside the band are untouched — above-ceiling is
    trusted, below-floor is garbage the LLM can't rescue.
    """
    import concurrent.futures as cf

    id_key = "num_article" if kind == "article" else "numero_client"
    label_key = "denomination" if kind == "article" else "nom"

    targets: list[int] = []
    for i, row in enumerate(shaped):
        conf = float(row.get("confidence") or 0.0)
        if floor <= conf < ceiling and row.get("candidates"):
            targets.append(i)
    if not targets:
        return

    def _one(i: int) -> tuple[int, dict]:
        row = shaped[i]
        arb = _arbitrate(str(row.get("query") or ""), row["candidates"], kind,
                         factory_id=factory_id, timeout=timeout)
        return i, arb

    with cf.ThreadPoolExecutor(max_workers=min(max_workers, len(targets))) as pool:
        for i, arb in pool.map(_one, targets):
            shaped[i]["arbitration"] = arb
            # Only override when BOTH arbiters agree. Single-arbiter picks are
            # surfaced in the audit trail but don't mutate the match — they're
            # too noisy to trust unilaterally (one arbiter has ~70% recall).
            if not arb.get("agree"):
                continue
            pick = arb.get("picked")
            if not pick:
                continue
            picked_cand = next(
                (c for c in shaped[i]["candidates"]
                 if str(c.get(id_key)) == str(pick)),
                None,
            )
            if not picked_cand:
                continue
            shaped[i][id_key] = picked_cand.get(id_key)
            shaped[i][label_key] = (picked_cand.get(label_key)
                                    or shaped[i].get(label_key))
            shaped[i]["confidence"] = min(
                0.98, float(shaped[i].get("confidence") or 0.0) + 0.15,
            )
            shaped[i]["method"] = "llm_arb_agree"
            shaped[i]["tier"] = 2


def _arbitrate(query: str, cands: list[dict], kind: str,
               factory_id: int,
               timeout: int = LLM_ARBITRATION_TIMEOUT) -> dict:
    """Fire monceapp + concierge in parallel. Return {"picked", "agree",
    "monceapp", "concierge"}. picked=None means no consensus worth trusting.
    """
    import threading
    out: dict[str, Any] = {"monceapp": None, "concierge": None}

    def _a():
        out["monceapp"] = _monceapp_vote(query, cands, kind, factory_id, timeout)

    def _c():
        out["concierge"] = _concierge_vote(query, cands, kind, timeout)

    ta = threading.Thread(target=_a, daemon=True)
    tc = threading.Thread(target=_c, daemon=True)
    ta.start(); tc.start()
    ta.join(timeout + 1); tc.join(timeout + 1)

    ma = out["monceapp"]
    cg = out["concierge"]
    agree = (ma is not None) and (ma == cg)
    picked = ma if agree else (ma or cg)
    return {"picked": picked, "agree": agree,
            "monceapp": ma, "concierge": cg}


# ─────────────────────────────────────────────────────────────────────────────
# Token-subset reranker — snake-candidate rescue, pure CPU, no fuzzy
# ─────────────────────────────────────────────────────────────────────────────

_TOK_RE = re.compile(r"[a-z0-9.]+", re.IGNORECASE)


def _norm_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


def _tokens(raw: str) -> list[str]:
    """Tokenize accent-stripped text, nospace-aware.

    - Splits on camelCase boundaries before lowercasing ("rTherm" → "r therm")
    - Splits on digit↔letter boundaries ("44.2rTherm" → "44.2 r therm")
    - Splits on any non-alnum separator except dot (so "44.2" stays atomic)
    - Drops single-character tokens that aren't digits (reduces noise)
    """
    if not raw:
        return []
    s = _norm_accents(raw)
    # camelCase split: "rTherm" → "r Therm"
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
    s = s.lower()
    # digit ↔ letter boundary split
    s = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", s)
    toks = _TOK_RE.findall(s)
    # keep all digit-bearing tokens; drop single-char pure-letter noise
    return [t for t in toks if any(c.isdigit() for c in t) or len(t) > 1]


def _trigrams(t: str) -> set[str]:
    t = f"  {t}  "
    return {t[i:i + 3] for i in range(len(t) - 2)}


def _soft_token_match(q_tok: str, c_set: set[str]) -> tuple[str | None, float]:
    """For tokens absent from c_set, look for a trigram-overlapping neighbor.
    Returns (best_c_token, weight_in_[0..1]). Used to rescue mashed inputs
    like "VENUSAMBRESCINTILLANT" vs ["venus", "ambre", "scintillant"].
    """
    if not q_tok:
        return None, 0.0
    q_grams = _trigrams(q_tok)
    if not q_grams:
        return None, 0.0
    best_tok, best_score = None, 0.0
    for ct in c_set:
        if len(ct) < 3:
            continue
        c_grams = _trigrams(ct)
        inter = len(q_grams & c_grams)
        if inter == 0:
            continue
        # containment score favors candidate tokens fully covered by query
        score = inter / max(len(c_grams), 1)
        if score > best_score:
            best_score = score
            best_tok = ct
    return best_tok, best_score


def _score_tokens(q_toks: list[str], c_toks: list[str]) -> float:
    """Order-free token-subset score in [0, 1].

    Rewards high overlap with the candidate and penalizes query tokens that
    the candidate can't explain (extra noise). Numbers weight 2x. Unmatched
    query tokens get a trigram-containment rescue pass (nospace variants).
    """
    if not q_toks or not c_toks:
        return 0.0
    q_set = set(q_toks)
    c_set = set(c_toks)
    shared = q_set & c_set

    def w(t: str) -> float:
        return 2.0 if any(ch.isdigit() for ch in t) else 1.0

    shared_w = sum(w(t) for t in shared)
    # trigram rescue for candidate tokens not directly present
    missing_c = c_set - shared
    consumed: set[str] = set()
    for ct in missing_c:
        # find a query token whose trigrams cover this candidate token
        for qt in q_set - shared - consumed:
            if len(qt) < 4:
                continue
            inter = len(_trigrams(ct) & _trigrams(qt))
            if inter == 0:
                continue
            score = inter / max(len(_trigrams(ct)), 1)
            if score >= 0.6:
                shared_w += w(ct) * score
                consumed.add(qt)
                break

    c_w = sum(w(t) for t in c_set)
    q_w = sum(w(t) for t in q_set)
    if c_w == 0 or q_w == 0:
        return 0.0
    recall = shared_w / c_w
    precision = shared_w / q_w
    if recall == 0 or precision == 0:
        return 0.0
    return 2 * recall * precision / (recall + precision)


def _rerank_by_token_subset(query: str, candidates: list[dict],
                            key: str) -> Optional[tuple[dict, float]]:
    """Pick the best candidate by token-subset score. Returns (cand, score)
    or None if no candidate scored above 0. Pure CPU."""
    q_toks = _tokens(query)
    if not q_toks or not candidates:
        return None
    best: Optional[tuple[dict, float]] = None
    for c in candidates:
        text = c.get(key) or c.get("denomination") or c.get("nom") or ""
        if not text:
            continue
        s = _score_tokens(q_toks, _tokens(text))
        if best is None or s > best[1]:
            best = (c, s)
    if best is None or best[1] <= 0.0:
        return None
    return best


# ─────────────────────────────────────────────────────────────────────────────
# Normalization helpers — shape /batch, /batch_client, /stage_0 uniformly
# ─────────────────────────────────────────────────────────────────────────────

def _empty_article(query: str, field: str, err: Optional[str] = None) -> dict:
    out = {
        "kind": "article",
        "query": query,
        "field": field,
        "num_article": None,
        "denomination": None,
        "confidence": 0.0,
        "method": None,
        "tier": 0,
        "candidates": [],
    }
    if err:
        out["error"] = err
    return out


def _empty_client(query: str, err: Optional[str] = None) -> dict:
    out = {
        "kind": "client",
        "query": query,
        "numero_client": None,
        "nom": None,
        "confidence": 0.0,
        "method": None,
        "tier": 0,
        "candidates": [],
    }
    if err:
        out["error"] = err
    return out


def _shape_article(row: dict, field: str,
                   rerank_floor: float = 0.6,
                   llm_floor: Optional[float] = None,
                   llm_ceiling: float = 0.95,
                   factory_id: int = 3,
                   llm_timeout: int = LLM_ARBITRATION_TIMEOUT) -> dict:
    match = row.get("match") or {}
    cands = row.get("candidates") or []
    conf = float(match.get("confidence") or 0.0)
    method = match.get("method")
    tier = int(match.get("tier") or 0)
    num = match.get("num_article")
    denom = match.get("denomination")
    query = row.get("query")
    arb = None

    # Snake-only rescue: if the top match is weak, re-rank snake's own
    # candidates via token-subset scoring. Pure CPU.
    if (conf < rerank_floor) and cands and query:
        best = _rerank_by_token_subset(str(query), cands, key="denomination")
        if best is not None:
            b_cand, b_score = best
            if b_score > max(conf, 0.0):
                num = b_cand.get("num_article")
                denom = b_cand.get("denomination")
                conf = b_score
                method = "snake_rerank"
                tier = 1

    # LLM arbitration on the ambiguous middle: monceapp + concierge vote.
    if (llm_floor is not None and cands and query
            and llm_floor <= conf < llm_ceiling):
        arb = _arbitrate(str(query), cands, "article",
                         factory_id=factory_id, timeout=llm_timeout)
        pick = arb.get("picked")
        if pick:
            picked_cand = next(
                (c for c in cands if str(c.get("num_article")) == str(pick)),
                None,
            )
            if picked_cand:
                num = picked_cand.get("num_article")
                denom = picked_cand.get("denomination")
                # Agreement boosts confidence; solo vote nudges it
                conf = min(0.98, conf + (0.15 if arb.get("agree") else 0.05))
                method = ("llm_arb_agree" if arb.get("agree")
                          else "llm_arb_solo")
                tier = 2

    out = {
        "kind": "article",
        "query": query,
        "field": field,
        "num_article": num,
        "denomination": denom,
        "confidence": conf,
        "method": method,
        "tier": tier,
        "candidates": cands,
        "field_suggestions": row.get("field_suggestions"),
    }
    if arb is not None:
        out["arbitration"] = arb
    return out


def _shape_client(row: dict, query: str,
                  rerank_floor: float = 0.6,
                  llm_floor: Optional[float] = None,
                  llm_ceiling: float = 0.95,
                  factory_id: int = 3,
                  llm_timeout: int = LLM_ARBITRATION_TIMEOUT) -> dict:
    match = row.get("match") or {}
    cands = row.get("snake_candidates") or row.get("candidates") or []
    conf = float(match.get("confidence") or 0.0)
    method = match.get("method")
    tier = int(match.get("tier") or 0)
    num = match.get("numero_client")
    nom = match.get("nom")
    nom_abrege = match.get("nom_abrege")
    arb = None

    if (conf < rerank_floor) and cands and query:
        best = _rerank_by_token_subset(query, cands, key="nom")
        if best is not None:
            b_cand, b_score = best
            if b_score > max(conf, 0.0):
                num = b_cand.get("numero_client")
                nom = b_cand.get("nom") or nom
                nom_abrege = b_cand.get("nom_abrege") or nom_abrege
                conf = b_score
                method = "snake_rerank"
                tier = 1

    if (llm_floor is not None and cands and query
            and llm_floor <= conf < llm_ceiling):
        arb = _arbitrate(query, cands, "client",
                         factory_id=factory_id, timeout=llm_timeout)
        pick = arb.get("picked")
        if pick:
            picked_cand = next(
                (c for c in cands if str(c.get("numero_client")) == str(pick)),
                None,
            )
            if picked_cand:
                num = picked_cand.get("numero_client")
                nom = picked_cand.get("nom") or nom
                nom_abrege = picked_cand.get("nom_abrege") or nom_abrege
                conf = min(0.98, conf + (0.15 if arb.get("agree") else 0.05))
                method = ("llm_arb_agree" if arb.get("agree")
                          else "llm_arb_solo")
                tier = 2

    out = {
        "kind": "client",
        "query": query,
        "numero_client": num,
        "nom": nom,
        "nom_abrege": nom_abrege,
        "confidence": conf,
        "method": method,
        "tier": tier,
        "candidates": cands,
        "snake_candidates": row.get("snake_candidates"),
    }
    if arb is not None:
        out["arbitration"] = arb
    return out


def _shape_stage_0(body: dict, filename: str) -> dict:
    cm = body.get("client_matching") or {}
    return {
        "kind": "client",
        "query": filename,
        "numero_client": cm.get("numero_client"),
        "nom": cm.get("nom"),
        "confidence": float(cm.get("confidence") or 0.0),
        "method": cm.get("method") or "stage_0",
        "tier": cm.get("tier") or 0,
        "client_infos": body.get("client_infos"),
        "candidates": (body.get("candidates") or {}).get("snake") or [],
        "metadata": body.get("metadata") or {},
        "source": "stage_0",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Matching — constructor-to-resolution
# ─────────────────────────────────────────────────────────────────────────────

class Matching(dict):
    """Universal client & article resolver. See module docstring."""

    _CLIENT_FIELDS = CLIENT_FIELDS
    _ARTICLE_FIELDS = ARTICLE_FIELDS

    def __new__(cls,
                arg=None,
                *,
                factory_id: int = 3,
                field: Optional[str] = None,
                kind: str = "auto",
                endpoint: Optional[str] = None,
                snake_url: Optional[str] = None,
                claude_url: Optional[str] = None,
                confidence_floor: float = 0.6,
                snake_threshold: float = 0.15,
                top_k: int = 10,
                use_fuzzy: bool = False,
                use_llm: bool = False,
                llm_floor: Optional[float] = None,
                llm_ceiling: float = 0.95,
                llm_timeout: int = LLM_ARBITRATION_TIMEOUT,
                mode: str = "match",
                timeout: int = DEFAULT_TIMEOUT,
                email_content: Optional[str] = None,
                model_mode: str = "balanced"):
        # Reusable deferred client — only when no arg at all
        if arg is None:
            client = object.__new__(_MatchingClient)
            client._factory_id = factory_id
            client._snake_url = (snake_url or SNAKE_URL).rstrip("/")
            client._claude_url = (claude_url or CLAUDE_URL).rstrip("/")
            client._timeout = timeout
            return client
        return super().__new__(cls)

    def __init__(self,
                 arg=None,
                 *,
                 factory_id: int = 3,
                 field: Optional[str] = None,
                 kind: str = "auto",
                 endpoint: Optional[str] = None,
                 snake_url: Optional[str] = None,
                 claude_url: Optional[str] = None,
                 confidence_floor: float = 0.6,
                 snake_threshold: float = 0.15,
                 top_k: int = 10,
                 use_fuzzy: bool = False,
                 use_llm: bool = False,
                 llm_floor: Optional[float] = None,
                 llm_ceiling: float = 0.95,
                 llm_timeout: int = LLM_ARBITRATION_TIMEOUT,
                 mode: str = "match",
                 timeout: int = DEFAULT_TIMEOUT,
                 email_content: Optional[str] = None,
                 model_mode: str = "balanced"):
        super().__init__()
        if arg is None:
            self.result = LLMResult()
            return

        # `use_llm=True` shorthand: arbitrate the ambiguous middle [0.6, 0.95).
        # Explicit `llm_floor` overrides.
        if use_llm and llm_floor is None:
            llm_floor = 0.6

        # endpoint override (monceapp reporting + for the usage ping)
        report_ep = (endpoint or "https://monceapp.aws.monce.ai").rstrip("/")

        shape_kw = dict(llm_floor=llm_floor, llm_ceiling=llm_ceiling,
                        factory_id=factory_id, llm_timeout=llm_timeout)

        t0 = time.time()

        # ── 1. Document path (pdf/image/docx/email) → /stage_0 ────────────
        doc = _is_docish(arg)
        if doc is not None:
            filename, data = doc
            body = _stage_0_file(data, filename, factory_id,
                                 email_content=email_content,
                                 model_mode=model_mode, timeout=FILE_TIMEOUT)
            elapsed = int((time.time() - t0) * 1000)
            if body.get("_error"):
                self.update(_empty_client(filename, err=body["_error"]))
                self["source"] = "stage_0"
            else:
                self.update(_shape_stage_0(body, filename))
            self.result = LLMResult(
                text=self.get("nom") or "",
                model="matching.stage_0",
                elapsed_ms=elapsed,
                sat_memory={"factory_id": factory_id, "filename": filename,
                            "method": self.get("method")},
                raw=body,
            )
            _report_usage(report_ep, f"match:stage_0:{filename}", self.result)
            return

        # ── 2. Array path → single /batch call ────────────────────────────
        if isinstance(arg, (list, tuple)):
            queries = list(arg)
            # Disallow mixed documents inside a list — keep it simple
            kind_eff, field_eff = _resolve_kind_field(kind, field, queries)
            if kind_eff == "client":
                rows = _batch_clients(
                    [str(q) for q in queries], factory_id,
                    use_fuzzy=use_fuzzy, top_k=top_k,
                    snake_threshold=snake_threshold, mode=mode, timeout=timeout,
                )
                shaped = [_shape_client(r, str(q), **shape_kw)
                          for r, q in zip(rows, queries)]
            else:
                rows = _batch_articles(
                    [str(q) for q in queries], factory_id, field_eff,
                    use_fuzzy=use_fuzzy, top_k=top_k,
                    snake_threshold=snake_threshold, use_llm=use_llm,
                    timeout=timeout,
                )
                shaped = [_shape_article(r, field_eff, **shape_kw)
                          for r in rows]

            elapsed = int((time.time() - t0) * 1000)
            # Instance IS the batch — keyed by index + .items list
            self["results"] = shaped
            self["kind"] = kind_eff
            self["field"] = field_eff if kind_eff == "article" else None
            self["factory_id"] = factory_id
            self["stats"] = _batch_stats(shaped, confidence_floor)
            self.result = LLMResult(
                text="", model=f"matching.batch.{kind_eff}",
                elapsed_ms=elapsed,
                sat_memory={"count": len(shaped), "stats": self["stats"]},
                raw={"results": shaped},
            )
            _report_usage(report_ep,
                          f"match:batch:{kind_eff}:n={len(shaped)}",
                          self.result)
            return

        # ── 3. Dict input → client fields mode ────────────────────────────
        if isinstance(arg, dict):
            # Preserve passthrough keys, build query string from known fields
            self.update(arg)
            probe_text = _build_client_probe(arg)
            if not probe_text:
                self.result = LLMResult(
                    text="", model="matching.client",
                    sat_memory={"reason": "no_client_fields_in_dict"},
                )
                return
            rows = _batch_clients([probe_text], factory_id,
                                  use_fuzzy=use_fuzzy, top_k=top_k,
                                  snake_threshold=snake_threshold,
                                  mode=mode, timeout=timeout)
            shaped = _shape_client(rows[0] if rows else {}, probe_text,
                                   **shape_kw)
            elapsed = int((time.time() - t0) * 1000)
            # Enrich, don't clobber — merge shaped match fields onto the dict
            for k in ("numero_client", "confidence", "method", "tier",
                      "candidates", "nom_abrege"):
                if shaped.get(k) is not None:
                    self[k] = shaped[k]
            self["kind"] = "client"
            if "nom" not in self and shaped.get("nom"):
                self["nom"] = shaped["nom"]
            self.result = LLMResult(
                text=shaped.get("nom") or "", model="matching.client",
                elapsed_ms=elapsed,
                sat_memory={"factory_id": factory_id,
                            "method": shaped.get("method")},
                raw=shaped,
            )
            _report_usage(report_ep, f"match:dict:{probe_text[:60]}",
                          self.result)
            return

        # ── 4. String input → article or client (explicit or auto) ────────
        if not isinstance(arg, str):
            raise TypeError(f"Matching: unsupported input type {type(arg).__name__}")

        query = arg
        kind_eff, field_eff = _resolve_kind_field(kind, field, [query])

        if kind_eff == "article":
            rows = _batch_articles(
                [query], factory_id, field_eff,
                use_fuzzy=use_fuzzy, top_k=top_k,
                snake_threshold=snake_threshold, use_llm=use_llm,
                timeout=timeout,
            )
            shaped = _shape_article(rows[0] if rows else {"query": query},
                                    field_eff, **shape_kw)
            self.update(shaped)
            text_out = shaped.get("denomination") or ""
            model_tag = "matching.article"
        elif kind_eff == "client":
            rows = _batch_clients(
                [query], factory_id,
                use_fuzzy=use_fuzzy, top_k=top_k,
                snake_threshold=snake_threshold, mode=mode, timeout=timeout,
            )
            shaped = _shape_client(rows[0] if rows else {"query": query}, query,
                                   **shape_kw)
            self.update(shaped)
            text_out = shaped.get("nom") or ""
            model_tag = "matching.client"
        else:
            # Ambiguous — fire both in parallel via threads, return best
            shaped = _race_both(query, factory_id, field_eff, use_fuzzy,
                                top_k, snake_threshold, use_llm, mode, timeout,
                                shape_kw=shape_kw)
            self.update(shaped)
            text_out = shaped.get("nom") or shaped.get("denomination") or ""
            model_tag = "matching.auto"

        elapsed = int((time.time() - t0) * 1000)
        self.result = LLMResult(
            text=text_out, model=model_tag, elapsed_ms=elapsed,
            sat_memory={"factory_id": factory_id,
                        "method": self.get("method"),
                        "confidence": self.get("confidence")},
            raw=dict(self),
        )
        _report_usage(report_ep, f"match:{kind_eff}:{query[:60]}", self.result)

    # ── Batch convenience ────────────────────────────────────────────────

    @property
    def items_list(self) -> list[dict]:
        """For batch mode: the ordered list of per-row shaped dicts."""
        return self.get("results") or []

    def __repr__(self):
        try:
            return _json.dumps(dict(self), ensure_ascii=False, indent=2,
                               default=str)
        except Exception:
            return dict.__repr__(self)

    def __str__(self):
        return self.__repr__()

    # ─────────────────────────────────────────────────────────────────────
    # Accuracy assessment — classmethod so callers don't need an instance
    # ─────────────────────────────────────────────────────────────────────

    @classmethod
    def assess(cls,
               pairs: Iterable[Union[Tuple[str, str], dict]],
               *,
               factory_id: int = 3,
               field: Optional[str] = None,
               kind: str = "auto",
               top_k: int = 10,
               use_fuzzy: bool = False,
               use_llm: bool = False,
               llm_floor: Optional[float] = None,
               llm_ceiling: float = 0.95,
               llm_timeout: int = LLM_ARBITRATION_TIMEOUT,
               snake_threshold: float = 0.15,
               confidence_floor: float = 0.6,
               timeout: int = DEFAULT_TIMEOUT) -> dict:
        """Measure accuracy against a labelled dataset.

        pairs: iterable of ``(query, expected_id)`` or
               ``{"query": ..., "expected": ..., "kind": "article"|"client",
                 "field": "verre"|...}``.

        For ``kind="auto"``, we use the per-pair "kind" if present, else
        heuristic + explicit ``field`` to decide article vs client.

        Returns::

            {
              "n": int,
              "hit_top1": float,               # correct top-1
              "hit_topk": float,               # correct anywhere in top_k
              "coverage": float,               # non-null top-1 rate
              "mean_confidence": float,
              "by_method": {method: {"n", "hit_top1", "mean_conf"}},
              "by_tier":   {tier:   {"n", "hit_top1"}},
              "calibration": [(bin_lo, bin_hi, n, hit_rate), ...],
              "failures": [ {query, expected, got, confidence, method}, ... ],
              "latency_ms": int
            }
        """
        t0 = time.time()
        effective_floor = (0.6 if (use_llm and llm_floor is None)
                           else llm_floor)
        # Normalize pairs
        norm: list[dict] = []
        for p in pairs:
            if isinstance(p, dict):
                q = p.get("query")
                e = p.get("expected") or p.get("expected_id")
                k = p.get("kind") or kind
                f = p.get("field") or field
            else:
                q, e = p[0], p[1]
                k, f = kind, field
            norm.append({"query": q, "expected": str(e) if e is not None else None,
                         "kind": k, "field": f})

        # Group by (kind_effective, field_effective) for batch efficiency
        groups: dict[Tuple[str, Optional[str]], list[int]] = {}
        for i, n in enumerate(norm):
            ke, fe = _resolve_kind_field(n["kind"], n["field"], [n["query"]])
            n["_kind"], n["_field"] = ke, fe
            groups.setdefault((ke, fe), []).append(i)

        # Run each group as one /batch call
        for (ke, fe), idxs in groups.items():
            texts = [norm[i]["query"] for i in idxs]
            if ke == "client":
                rows = _batch_clients(texts, factory_id,
                                      use_fuzzy=use_fuzzy, top_k=top_k,
                                      snake_threshold=snake_threshold,
                                      mode="match", timeout=timeout)
                # Shape WITHOUT LLM first (fast, all CPU)
                shaped = [_shape_client(r, q) for r, q in zip(rows, texts)]
                if effective_floor is not None:
                    _arbitrate_batch(shaped, "client", factory_id,
                                     effective_floor, llm_ceiling, llm_timeout)
            else:
                rows = _batch_articles(texts, factory_id, fe or "global",
                                       use_fuzzy=use_fuzzy, top_k=top_k,
                                       snake_threshold=snake_threshold,
                                       use_llm=use_llm, timeout=timeout)
                shaped = [_shape_article(r, fe or "global") for r in rows]
                if effective_floor is not None:
                    _arbitrate_batch(shaped, "article", factory_id,
                                     effective_floor, llm_ceiling, llm_timeout)
            for i, s in zip(idxs, shaped):
                norm[i]["result"] = s

        # Score
        n = len(norm)
        hit1 = 0
        hitk = 0
        covered = 0
        conf_sum = 0.0
        by_method: dict[str, dict] = {}
        by_tier: dict[int, dict] = {}
        bins = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6),
                (0.6, 0.8), (0.8, 0.95), (0.95, 1.01)]
        bin_n = [0] * len(bins)
        bin_hit = [0] * len(bins)
        failures: list[dict] = []

        for row in norm:
            r = row.get("result") or {}
            expected = row["expected"]
            got = r.get("num_article") or r.get("numero_client")
            conf = float(r.get("confidence") or 0.0)
            method = r.get("method") or "none"
            tier = int(r.get("tier") or 0)
            cands = r.get("candidates") or []

            if got is not None:
                covered += 1
            conf_sum += conf

            is_hit1 = (expected is not None and got is not None
                       and str(got) == expected)
            if is_hit1:
                hit1 += 1
            # top-k hit (look through candidates)
            topk_ids = [str(c.get("num_article") or c.get("numero_client"))
                        for c in cands if c]
            if expected is not None and (is_hit1 or expected in topk_ids):
                hitk += 1

            # by_method / by_tier
            bm = by_method.setdefault(method, {"n": 0, "hit_top1": 0,
                                               "conf_sum": 0.0})
            bm["n"] += 1
            bm["hit_top1"] += int(is_hit1)
            bm["conf_sum"] += conf
            bt = by_tier.setdefault(tier, {"n": 0, "hit_top1": 0})
            bt["n"] += 1
            bt["hit_top1"] += int(is_hit1)

            # calibration
            for bi, (lo, hi) in enumerate(bins):
                if lo <= conf < hi:
                    bin_n[bi] += 1
                    bin_hit[bi] += int(is_hit1)
                    break

            if not is_hit1:
                failures.append({
                    "query": row["query"],
                    "expected": expected,
                    "got": got,
                    "confidence": conf,
                    "method": method,
                    "kind": row["_kind"],
                    "field": row["_field"],
                })

        for m in by_method.values():
            m["mean_conf"] = (m["conf_sum"] / m["n"]) if m["n"] else 0.0
            m["accuracy"] = (m["hit_top1"] / m["n"]) if m["n"] else 0.0
            del m["conf_sum"]
        for t in by_tier.values():
            t["accuracy"] = (t["hit_top1"] / t["n"]) if t["n"] else 0.0

        calibration = [
            (lo, hi, bin_n[i], (bin_hit[i] / bin_n[i]) if bin_n[i] else 0.0)
            for i, (lo, hi) in enumerate(bins)
        ]
        elapsed = int((time.time() - t0) * 1000)

        return {
            "n": n,
            "hit_top1": (hit1 / n) if n else 0.0,
            "hit_topk": (hitk / n) if n else 0.0,
            "coverage": (covered / n) if n else 0.0,
            "mean_confidence": (conf_sum / n) if n else 0.0,
            "by_method": by_method,
            "by_tier": by_tier,
            "calibration": calibration,
            "failures": failures[:200],        # cap — don't blow up the result
            "failures_total": len(failures),
            "confidence_floor": confidence_floor,
            "above_floor_accuracy": _above_floor_accuracy(norm, confidence_floor),
            "latency_ms": elapsed,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_kind_field(kind: str, field: Optional[str],
                        queries: list) -> Tuple[str, Optional[str]]:
    """Decide (kind, field) for a query or batch of queries."""
    if field is not None:
        if field not in ARTICLE_FIELDS:
            raise ValueError(
                f"Matching: unknown field {field!r}. Allowed: {ARTICLE_FIELDS}"
            )
        return "article", field
    if kind == "article":
        return "article", "global"
    if kind == "client":
        return "client", None
    # auto — use majority vote across queries
    votes = {"client": 0, "article": 0, "ambiguous": 0}
    for q in queries:
        votes[classify(str(q))] += 1
    if votes["client"] > votes["article"]:
        return "client", None
    if votes["article"] > votes["client"]:
        return "article", "global"
    # tie or all ambiguous — signal ambiguous so single-string path races both.
    # For batches we still need a concrete choice — default to article,
    # which is the more common case in glass workflows.
    if len(queries) == 1:
        return "ambiguous", None
    return "article", "global"


def _build_client_probe(d: dict) -> str:
    """Turn a dict of known client fields into a single probe string."""
    parts = []
    for k in ("nom", "raison_social", "logo_text", "siret_siren",
              "email", "telephone"):
        v = d.get(k)
        if v:
            parts.append(str(v))
    return " ".join(parts).strip()


def _race_both(query: str, factory_id: int, field: str,
               use_fuzzy: bool, top_k: int, snake_threshold: float,
               use_llm: bool, mode: str, timeout: int,
               shape_kw: Optional[dict] = None) -> dict:
    """Fire client + article in parallel; return highest-confidence winner."""
    import threading
    out: dict[str, Any] = {}
    skw = shape_kw or {}

    def _art():
        rows = _batch_articles([query], factory_id, field,
                               use_fuzzy=use_fuzzy, top_k=top_k,
                               snake_threshold=snake_threshold,
                               use_llm=use_llm, timeout=timeout)
        out["article"] = _shape_article(rows[0] if rows else {"query": query},
                                        field, **skw)

    def _cli():
        rows = _batch_clients([query], factory_id,
                              use_fuzzy=use_fuzzy, top_k=top_k,
                              snake_threshold=snake_threshold,
                              mode=mode, timeout=timeout)
        out["client"] = _shape_client(rows[0] if rows else {"query": query},
                                      query, **skw)

    ta = threading.Thread(target=_art, daemon=True)
    tc = threading.Thread(target=_cli, daemon=True)
    ta.start(); tc.start()
    ta.join(); tc.join()
    art = out.get("article", {})
    cli = out.get("client", {})
    art_c = art.get("confidence") or 0.0
    cli_c = cli.get("confidence") or 0.0
    if cli_c >= art_c and cli.get("numero_client"):
        winner = dict(cli)
        winner["kind"] = "client"
    else:
        winner = dict(art)
        winner["kind"] = "article"
    winner["both"] = {"article": art, "client": cli}
    return winner


def _batch_stats(shaped: list[dict], floor: float) -> dict:
    n = len(shaped)
    if not n:
        return {"n": 0}
    matched = sum(1 for s in shaped
                  if (s.get("num_article") or s.get("numero_client")))
    above = sum(1 for s in shaped if (s.get("confidence") or 0) >= floor)
    mean_conf = sum(float(s.get("confidence") or 0) for s in shaped) / n
    by_tier: dict[int, int] = {}
    for s in shaped:
        by_tier[int(s.get("tier") or 0)] = by_tier.get(int(s.get("tier") or 0), 0) + 1
    return {
        "n": n,
        "matched": matched,
        "matched_rate": matched / n,
        "above_floor": above,
        "above_floor_rate": above / n,
        "mean_confidence": mean_conf,
        "by_tier": by_tier,
    }


def _above_floor_accuracy(norm: list[dict], floor: float) -> dict:
    n_above = 0
    hit_above = 0
    for row in norm:
        r = row.get("result") or {}
        conf = float(r.get("confidence") or 0.0)
        if conf < floor:
            continue
        n_above += 1
        got = r.get("num_article") or r.get("numero_client")
        if row["expected"] is not None and got is not None \
                and str(got) == row["expected"]:
            hit_above += 1
    return {
        "n": n_above,
        "accuracy": (hit_above / n_above) if n_above else 0.0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Reusable client (Matching() with no arg)
# ─────────────────────────────────────────────────────────────────────────────

class _MatchingFuture:
    """Lazy Matching result. dict-like on access, blocks until resolved."""

    def __init__(self, arg, factory_id, field, kind, timeout, **kw):
        import threading
        self._arg = arg
        self._data: Optional[dict] = None
        self._result: Optional[LLMResult] = None
        self._done = threading.Event()

        def _compute():
            m = Matching(arg, factory_id=factory_id, field=field, kind=kind,
                         timeout=timeout, **kw)
            self._data = dict(m)
            self._result = getattr(m, "result", None)
            self._done.set()

        threading.Thread(target=_compute, daemon=True).start()

    @property
    def result(self):
        self._done.wait()
        return self._result

    def _block(self):
        self._done.wait()
        return self._data

    def __getitem__(self, key): return self._block()[key]
    def __contains__(self, key): return key in self._block()
    def __iter__(self): return iter(self._block())
    def __len__(self): return len(self._block())
    def keys(self): return self._block().keys()
    def values(self): return self._block().values()
    def items(self): return self._block().items()
    def get(self, key, default=None): return self._block().get(key, default)

    def __str__(self):
        return _json.dumps(self._block(), ensure_ascii=False, indent=2,
                           default=str)

    def __repr__(self):
        if self._done.is_set():
            return str(self)
        return f'[matching {str(self._arg)[:30]}...]'


class _MatchingClient:
    """Reusable client. Returned by Matching() with no query."""

    def __call__(self, arg, field: Optional[str] = None, kind: str = "auto",
                 **kw):
        return _MatchingFuture(
            arg,
            factory_id=kw.pop("factory_id", self._factory_id),
            field=field,
            kind=kind,
            timeout=kw.pop("timeout", self._timeout),
            **kw,
        )

    def __repr__(self):
        return (f'Matching(snake_url={self._snake_url!r}, '
                f'factory_id={self._factory_id})')
