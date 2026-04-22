"""
monceai.Google — tiny google.fr scraper + Haiku synthesizer.

Takes any text prompt, hits https://www.google.fr/search?q=..., parses the
top results, and returns a Haiku-synthesized paragraph of the search
knowledge. str(Google(prompt)) IS the synthesis, ready to feed downstream.

    from monceai import Google

    r = Google("prix verre 44.2 rTherm 2026")
    str(r)           # "Le verre 44.2 rTherm se situe autour de XX €/m²..."
    r.results        # [{'title', 'url', 'snippet'}, ...]
    r.raw_html       # original HTML for debugging

    # Chain with Synthax for grounded reasoning
    from monceai import Synthax
    ctx = Google("rTherm 2026 prix")
    s = Synthax(f"Answer with sources: what is the market price? Context:\\n{ctx}")

    # Client mode — parallel futures
    g = Google()
    a = g("SAT solver Kissat")
    b = g("polynomial SAT techniques")
    print(a, b)

No key required for the Google scrape. The Haiku synthesis call hits the
free MonceApp gateway like every other text module. Zero deps beyond
``requests``. Fragile by nature — Google can change their HTML any day.
Use for personal / low-volume workflows. Production should use Brave or
SerpAPI behind the same class interface (one-line swap).
"""

from __future__ import annotations

import os
import re
import time
from html import unescape
from typing import Any, List, Optional

import requests

from .llm import _chat, _resolve_model, _report_usage, DEFAULT_ENDPOINT, LLMResult


_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Safari/605.1.15"
)
_DEFAULT_NUM = 8
_DEFAULT_TIMEOUT = 10


# ─────────────────────────────────────────────────────────────────────────────
# Scraper — tiny, regex-based, google.fr
# ─────────────────────────────────────────────────────────────────────────────

def _google_search(query: str, num: int = _DEFAULT_NUM,
                   timeout: int = _DEFAULT_TIMEOUT) -> tuple[list, str]:
    """Search the web via fallback chain, return (results, raw_html).

    Why not google.com/search directly: Google serves a JS-only shell
    to non-interactive clients — plain requests.get returns 90KB of
    scaffolding with zero rendered results. So we route through
    search backends that do serve usable HTML to plain requests:

        1. DuckDuckGo HTML endpoint (best quality, clean parsing)
        2. Bing HTML fallback (when DDG rate-limits the IP — common
           from AWS/GCP/Azure ranges that DDG flags as bot traffic)

    The public class stays named ``Google`` — the intent is "search
    the web" regardless of which backend answered. Swappable to
    Brave/Serper later behind the same interface.
    """
    # Try DDG first
    results, html = _ddg_search(query, num=num, timeout=timeout)
    if results:
        return results, html

    # Fallback to Bing — tolerates datacenter IPs far better than DDG
    results_b, html_b = _bing_search(query, num=num, timeout=timeout)
    if results_b:
        return results_b, html_b

    # Return whatever we had for debugging
    return [], html or html_b


def _ddg_search(query: str, num: int, timeout: int) -> tuple[list, str]:
    url = "https://html.duckduckgo.com/html/"
    data = {"q": query, "kl": "fr-fr"}
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    try:
        resp = requests.post(url, data=data, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        return [], f"<ddg-error: {e}>"
    html = resp.text or ""
    if resp.status_code != 200:
        return [], html
    return _parse_ddg_html(html, num), html


def _bing_search(query: str, num: int, timeout: int) -> tuple[list, str]:
    url = "https://www.bing.com/search"
    params = {"q": query, "setlang": "fr", "count": num}
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        return [], f"<bing-error: {e}>"
    html = resp.text or ""
    if resp.status_code != 200:
        return [], html
    return _parse_bing_html(html, num), html


_BING_RESULT_RX = re.compile(
    r'<li class="b_algo"[^>]*>.*?'
    r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>\s*</h2>'
    r'.*?<(?:p|div)[^>]*class="[^"]*b_(?:caption|snippet)[^"]*"[^>]*>(.*?)</(?:p|div)>',
    re.DOTALL,
)
_BING_TITLE_ONLY_RX = re.compile(
    r'<li class="b_algo"[^>]*>.*?'
    r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.DOTALL,
)


def _parse_bing_html(html: str, num: int) -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()
    for m in _BING_RESULT_RX.finditer(html):
        url = _unwrap_bing_redirect(m.group(1))
        title, snippet = _strip_tags(m.group(2)), _strip_tags(m.group(3))
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= num:
            break
    if not results:
        for m in _BING_TITLE_ONLY_RX.finditer(html):
            url = _unwrap_bing_redirect(m.group(1))
            title = _strip_tags(m.group(2))
            if not url.startswith(("http://", "https://")) or url in seen:
                continue
            seen.add(url)
            results.append({"title": title, "url": url, "snippet": ""})
            if len(results) >= num:
                break
    return results


_DDG_RESULT_RX = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
    r'.*?<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
    re.DOTALL,
)
# Fallback when snippet is missing — just title + url
_DDG_TITLE_ONLY_RX = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.DOTALL,
)


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", unescape(s or "")).strip()


def _unwrap_bing_redirect(url: str) -> str:
    """Bing wraps external links as bing.com/ck/a?...&u=a1<base64>&...
    Unwrap the base64'd real URL."""
    if "bing.com/ck/" not in url:
        return url
    try:
        from urllib.parse import urlparse, parse_qs
        import base64
        clean = url.replace("&amp;", "&")
        qs = parse_qs(urlparse(clean).query)
        enc = (qs.get("u") or [""])[0]
        if enc.startswith("a1"):
            enc = enc[2:]
        if enc:
            # add padding
            decoded = base64.b64decode(enc + "===").decode("utf-8", errors="ignore")
            if decoded.startswith(("http://", "https://")):
                return decoded
    except Exception:
        pass
    return url


def _unwrap_ddg_redirect(url: str) -> str:
    """DDG returns //duckduckgo.com/l/?uddg=<encoded target>. Unwrap it."""
    if "duckduckgo.com/l/" in url or url.startswith("//duckduckgo.com/l/"):
        m = re.search(r"uddg=([^&]+)", url)
        if m:
            from urllib.parse import unquote
            return unquote(m.group(1))
    # Protocol-relative → https
    if url.startswith("//"):
        return "https:" + url
    return url


def _parse_ddg_html(html: str, num: int) -> list[dict]:
    """Parse DDG's HTML endpoint. Returns up to `num` hits."""
    results: list[dict] = []
    seen_urls: set[str] = set()

    for m in _DDG_RESULT_RX.finditer(html):
        url = _unwrap_ddg_redirect(m.group(1))
        title = _strip_tags(m.group(2))
        snippet = _strip_tags(m.group(3))
        if not url.startswith(("http://", "https://")):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= num:
            break

    # Fallback if the strict regex missed everything (DDG tweaks HTML)
    if not results:
        for m in _DDG_TITLE_ONLY_RX.finditer(html):
            url = _unwrap_ddg_redirect(m.group(1))
            title = _strip_tags(m.group(2))
            if not url.startswith(("http://", "https://")):
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            results.append({"title": title, "url": url, "snippet": ""})
            if len(results) >= num:
                break

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Haiku synthesis — compress search results into one contextualized paragraph
# ─────────────────────────────────────────────────────────────────────────────

_SYNTH_PROMPT = (
    "You are summarizing Google search results for a user. Produce a single "
    "clean paragraph (3-6 sentences, French if the query is French) that "
    "captures the gist of what the web says about this question. Cite key "
    "sources inline with [1], [2] referring to the numbered results below. "
    "Do NOT invent facts — if sources disagree, say so. If results look "
    "empty or irrelevant, say that honestly.\n\n"
    "QUERY: {query}\n\n"
    "RESULTS:\n{results}\n\n"
    "SYNTHESIS:"
)


def _format_results_for_prompt(results: list[dict]) -> str:
    if not results:
        return "(no results)"
    lines = []
    for i, r in enumerate(results, 1):
        title = (r.get("title") or "")[:180]
        url = r.get("url") or ""
        snip = (r.get("snippet") or "")[:280]
        lines.append(f"[{i}] {title}\n    {url}\n    {snip}".rstrip())
    return "\n\n".join(lines)


def _synthesize(query: str, results: list[dict], endpoint: str,
                timeout: int = 30) -> LLMResult:
    prompt = _SYNTH_PROMPT.format(
        query=query,
        results=_format_results_for_prompt(results),
    )
    return _chat(
        text=prompt,
        model=_resolve_model("haiku"),
        endpoint=endpoint,
        timeout=timeout,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Google — public class (str subclass, blocks-on-construct, lazy client mode)
# ─────────────────────────────────────────────────────────────────────────────

class Google(str):
    """Google search → Haiku synthesis. ``str(Google(q))`` is the synthesis.

    Single-shot:
        Google("prix 44.2 rTherm 2026")

    Reusable client (lazy futures, like Charles/Moncey):
        g = Google()
        a = g("Kissat SAT solver")
        b = g("monceai SDK")
        print(a, b)
    """

    def __new__(cls, query: Optional[str] = None, num: int = _DEFAULT_NUM,
                endpoint: Optional[str] = None, timeout: int = 60):
        if query is None:
            client = object.__new__(_GoogleClient)
            client._endpoint = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
            client._num = num
            client._timeout = timeout
            return client

        ep = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
        t0 = time.time()
        results, raw_html = _google_search(query, num=num, timeout=min(timeout, 15))
        t_search = int((time.time() - t0) * 1000)

        if not results:
            # Still call Haiku — it will honestly say "no results"
            pass

        synth = _synthesize(query, results, endpoint=ep,
                            timeout=max(15, timeout - t_search // 1000))
        elapsed = int((time.time() - t0) * 1000)

        instance = super().__new__(cls, synth.text or "(no synthesis)")
        instance.query = query
        instance.results = results
        instance.raw_html = raw_html
        instance.search_ms = t_search
        instance.result = LLMResult(
            text=synth.text,
            model="google+haiku",
            elapsed_ms=elapsed,
            sat_memory={
                "search_ms": t_search,
                "num_results": len(results),
                "query": query,
                "synth_tokens": (synth.input_tokens + synth.output_tokens),
            },
            input_tokens=synth.input_tokens,
            output_tokens=synth.output_tokens,
            raw=synth.raw,
        )
        _report_usage(ep, f"google:{query[:80]}", instance.result)
        return instance

    def __repr__(self):
        return (f"Google(query={self.query!r}, "
                f"results={len(self.results)}, "
                f"text={str(self)[:60]!r})")


class _GoogleFuture:
    """Lazy future for Google client mode."""

    def __init__(self, query, endpoint, num, timeout):
        import threading
        self._query = query
        self._result = None
        self._text = None
        self._done = threading.Event()

        def _compute():
            g = Google(query, num=num, endpoint=endpoint, timeout=timeout)
            self._result = g
            self._text = str(g)
            self._done.set()

        threading.Thread(target=_compute, daemon=True).start()

    @property
    def result(self):
        self._done.wait()
        return self._result

    def __str__(self):
        self._done.wait()
        return self._text or ""

    def __repr__(self):
        if self._done.is_set():
            return (self._text or "")[:60]
        return f"[googling {self._query[:30]}...]"

    def __format__(self, spec): return format(str(self), spec)
    def __add__(self, other): return str(self) + other
    def __radd__(self, other): return other + str(self)
    def __len__(self): return len(str(self))
    def __bool__(self): self._done.wait(); return bool(self._text)


class _GoogleClient:
    """Reusable client returned by Google() with no args."""

    def __call__(self, query, **kw):
        return _GoogleFuture(
            query, self._endpoint,
            kw.get("num", self._num),
            kw.get("timeout", self._timeout),
        )

    def __repr__(self):
        return f"Google(endpoint={self._endpoint!r})"
