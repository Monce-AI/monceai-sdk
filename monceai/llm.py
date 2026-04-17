"""
monceai.LLM — Cloud-backed LLM/VLM chat via MonceApp.

Text in, answer out. Three modes:
    LLM(prompt)                    — text answer (charles-science, any model)
    LLM(prompt, image=bytes)       — VLM answer (charles-json, Sonnet, Haiku)
    LLM(prompt, json=True)         — structured JSON answer (charles-json)

    from monceai import LLM

    answer = LLM("6x7")
    answer = LLM("factor 10403", model="charles-auma")
    answer = LLM("what is this?", image=open("photo.png","rb").read())
    answer = LLM("extract fields", image=img_bytes, json=True)

No API key required. MonceApp is free and open — zero auth on all endpoints.
LLM, VLM, and Charles work out of the box with `pip install monceai`.

Snake and SAT require API keys (SNAKE_API_KEY, SAT_API_KEY) because they
spin Lambda workers. LLM/VLM/Charles are free — Bedrock costs are on us.
"""

import base64
import json as _json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

import requests


def _report_usage(endpoint: str, prompt: str, result: "LLMResult"):
    """Fire-and-forget GET to /usage — populates the dashboard."""
    import threading
    def _do():
        try:
            sat = result.sat_memory or {}
            requests.get(f"{endpoint}/usage", params={
                "prompt": prompt[:100],
                "model": result.model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "elapsed_ms": result.elapsed_ms,
                "zero_llm": "1" if sat.get("zero_llm") else "0",
                "fast_path": "1" if sat.get("fast_path") else "0",
                "winner": sat.get("winner", ""),
            }, timeout=3)
        except Exception:
            pass
    threading.Thread(target=_do, daemon=True).start()


DEFAULT_ENDPOINT = "https://monceapp.aws.monce.ai"

MODELS = {
    "charles":           "charles",
    "charles-science":   "charles-science",
    "charles-auma":      "charles-auma",
    "charles-json":      "charles-json",
    "charles-architect": "charles-architect",
    "concise":           "concise",
    "cc":                "cc",
    "sonnet":            "eu.anthropic.claude-sonnet-4-6",
    "sonnet4":           "eu.anthropic.claude-sonnet-4-20250514-v1:0",
    "haiku":             "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
    "nova-pro":          "eu.amazon.nova-pro-v1:0",
    "nova-lite":         "eu.amazon.nova-lite-v1:0",
    "nova-micro":        "eu.amazon.nova-micro-v1:0",
}


def _resolve_model(model: str) -> str:
    return MODELS.get(model, model)


@dataclass
class LLMResult:
    text: str = ""
    model: str = ""
    session_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_ms: int = 0
    sat_memory: dict = field(default_factory=dict)
    tools_called: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def json(self) -> Optional[dict]:
        try:
            return _json.loads(self.text)
        except (ValueError, TypeError):
            return None

    @property
    def ok(self) -> bool:
        return bool(self.text) and "Model unavailable" not in self.text

    def __repr__(self):
        preview = self.text[:80].replace("\n", " ")
        return f"LLMResult(model={self.model!r}, tokens={self.input_tokens}+{self.output_tokens}, text={preview!r})"


class LLMSession:
    """
    Persistent chat session. Messages accumulate.

        session = LLMSession(model="charles")
        r1 = session.send("morning bruv")
        r2 = session.send("what did I just say?")
    """

    def __init__(self, model: str = "charles-science", factory_id: int = 0,
                 endpoint: str = None, api_key: str = None, session_id: str = None):
        self.endpoint = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
        self.api_key = api_key or os.environ.get("MONCEAPP_API_KEY")
        self.model = _resolve_model(model)
        self.factory_id = factory_id
        self.session_id = session_id or ""
        self._http = requests.Session()
        if self.api_key:
            self._http.headers["Authorization"] = f"Bearer {self.api_key}"

    def send(self, text: str, image: bytes = None, image_type: str = "image/png",
             timeout: int = 120) -> LLMResult:
        return _chat(
            text=text, image=image, image_type=image_type,
            model=self.model, factory_id=self.factory_id,
            session_id=self.session_id, endpoint=self.endpoint,
            session=self._http, timeout=timeout,
        )

    def __repr__(self):
        return f"LLMSession(model={self.model!r}, session={self.session_id!r})"


def _chat(text: str, image: bytes = None, image_type: str = "image/png",
          model: str = "charles-science", factory_id: int = 0,
          session_id: str = "", endpoint: str = None,
          session: requests.Session = None, timeout: int = 120,
          as_json: bool = False) -> LLMResult:

    url = f"{(endpoint or DEFAULT_ENDPOINT).rstrip('/')}/v1/chat"
    http = session or requests.Session()

    data = {"model_id": model, "message": text}
    if factory_id:
        data["factory_id"] = str(factory_id)
    if session_id:
        data["session_id"] = session_id

    files = {}
    if image:
        ext = image_type.split("/")[-1]
        files["file"] = (f"image.{ext}", image, image_type)

    t = time.time()
    try:
        if files:
            resp = http.post(url, data=data, files=files, timeout=timeout)
        else:
            resp = http.post(url, data=data, timeout=timeout)

        elapsed_ms = int((time.time() - t) * 1000)

        if resp.status_code != 200:
            return LLMResult(
                text=f"HTTP {resp.status_code}: {resp.text[:200]}",
                model=model, elapsed_ms=elapsed_ms,
            )

        body = resp.json()
        usage = body.get("usage", {})

        return LLMResult(
            text=body.get("reply", ""),
            model=body.get("monce_model", body.get("model", model)),
            session_id=body.get("session_id", session_id),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            elapsed_ms=elapsed_ms,
            sat_memory=body.get("sat_memory", {}),
            tools_called=body.get("tools_called", []),
            raw=body,
        )
    except requests.exceptions.Timeout:
        return LLMResult(text="Timeout", model=model, elapsed_ms=int((time.time() - t) * 1000))
    except Exception as e:
        return LLMResult(text=f"Error: {e}", model=model, elapsed_ms=int((time.time() - t) * 1000))


def LLM(prompt: str, model: str = "charles-science", image: bytes = None,
         image_type: str = "image/png", json: bool = False,
         factory_id: int = 0, endpoint: str = None, timeout: int = 120) -> LLMResult:
    """
    One-shot LLM/VLM call. Text in, answer out.

        from monceai import LLM

        # Text → answer
        r = LLM("6x7")
        r = LLM("factor 10403", model="charles-auma")
        r = LLM("what is the golden ratio?", model="charles-science")
        r = LLM("morning bruv", model="charles")

        # Image → answer (VLM)
        r = LLM("what is this?", image=open("photo.png","rb").read())
        r = LLM("extract glass fields", image=img, model="charles-json")

        # Structured JSON
        r = LLM("list prime numbers under 20", json=True)
        r.json  # parsed dict

    Models:
        charles-science   — Snake router → 7 scientific services → Sonnet
        charles-auma      — Boolean maximization over {0,1}^n (= or ≈)
        charles           — 4x parallel (memory+csv+cnf+sudoku) → Sonnet
        charles-json      — Strict JSON output, VLM capable
        charles-architect — ASCII diagrams
        concise           — charles → Haiku TL;DR
        cc                — charles ∥ concise → synthesis
        sonnet            — Sonnet 4.6 (fast, tools)
        haiku             — Haiku 4.5 (fastest, cheapest)
        nova-pro/lite/micro — Amazon Nova (context only)
    """
    if json and model == "charles-science":
        model = "charles-json"
    elif json:
        model = "charles-json"

    resolved = _resolve_model(model)

    return _chat(
        text=prompt, image=image, image_type=image_type,
        model=resolved, factory_id=factory_id,
        endpoint=endpoint, timeout=timeout, as_json=json,
    )


class Charles:
    """
    Lazy async compute. Fires on construction, resolves on read.

        from monceai import Charles

        # These fire INSTANTLY — all 3 compute in parallel
        a = Charles("6x7")
        b = Charles("factor 10403")
        c = Charles("roots of z^2+1=0")

        # Block only when you READ — by now they're done
        print(a)          # "42"
        print(b)          # "10403 = 101 × 103"
        print(c)          # "z = ±i"

        # It's a string everywhere
        f"Answer: {a}"    # "Answer: 42"
        a + " is the answer"
        a.upper()
        len(a)

        # Metadata
        a.result.model       # "monceai-charles-auma"
        a.result.elapsed_ms  # 4200
        a.result.sat_memory  # {"formula": "...", "auma_x": [1,0,1,0,1,0]}

        # Strategies
        Charles("minimize x^2", strategy="math")
        Charles.math("minimize x^2")
        Charles.science("is K4 3-colorable?")
        Charles.json("list primes")
        Charles.vlm("describe", image=img)
    """

    STRATEGIES = {
        "math":    ["charles-auma"],
        "science": ["charles-science"],
        "json":    ["charles-json"],
        "vlm":     ["charles-json"],
        "chat":    ["charles"],
        "quick":   ["concise"],
        "deep":    ["charles", "charles-science"],
        "all":     ["charles-auma", "charles-science", "charles-json"],
    }

    def __init__(self, prompt: str = None, image: bytes = None, image_type: str = "image/png",
                 strategy: str = None, factory_id: int = 0, endpoint: str = None, timeout: int = 90):
        import threading
        self._prompt = prompt or ""
        self._endpoint = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
        self._factory_id = factory_id
        self._timeout = timeout
        self._result = None
        self._text = None
        self._done = threading.Event()

        if prompt is None:
            self._text = ""
            self._result = LLMResult()
            self._done.set()
            return

        if image:
            models = ["charles-json"]
            self._image = image
            self._image_type = image_type
        else:
            self._image = None
            self._image_type = "image/png"
            if strategy and strategy in self.STRATEGIES:
                models = self.STRATEGIES[strategy]
            else:
                models = self._route_static(prompt)

        self._models = models

        # Fire in background — resolves when you read
        def _compute():
            if self._image:
                r = _chat(text=prompt, image=self._image, image_type=self._image_type,
                           model="charles-json", factory_id=factory_id,
                           endpoint=self._endpoint, timeout=timeout)
            elif len(models) == 1:
                r = _chat(text=prompt, model=_resolve_model(models[0]),
                           factory_id=factory_id, endpoint=self._endpoint, timeout=timeout)
            else:
                r = self._parallel_static(prompt, models, factory_id, self._endpoint, timeout)
            self._result = r
            self._text = r.text
            self._done.set()
            _report_usage(self._endpoint, prompt, r)

        threading.Thread(target=_compute, daemon=True).start()

    def _resolve(self):
        self._done.wait()

    @property
    def result(self) -> LLMResult:
        self._resolve()
        return self._result

    # ── string interface: resolves on any read ──
    def __str__(self):
        self._resolve()
        return self._text

    def __repr__(self):
        if self._done.is_set():
            preview = (self._text or "")[:60].replace("\n", " ")
            return f'Charles({self._prompt!r}) → {preview!r}'
        return f'Charles({self._prompt!r}) → [computing...]'

    def __format__(self, spec):
        return format(str(self), spec)

    def __add__(self, other):
        return str(self) + other

    def __radd__(self, other):
        return other + str(self)

    def __len__(self):
        return len(str(self))

    def __contains__(self, item):
        return item in str(self)

    def __getitem__(self, key):
        return str(self)[key]

    def __eq__(self, other):
        return str(self) == str(other)

    def __hash__(self):
        return hash(str(self))

    def __bool__(self):
        self._resolve()
        return bool(self._text)

    def upper(self): return str(self).upper()
    def lower(self): return str(self).lower()
    def strip(self): return str(self).strip()
    def split(self, *a, **kw): return str(self).split(*a, **kw)
    def startswith(self, *a): return str(self).startswith(*a)
    def endswith(self, *a): return str(self).endswith(*a)
    def replace(self, *a): return str(self).replace(*a)
    def find(self, *a): return str(self).find(*a)
    def count(self, *a): return str(self).count(*a)

    @staticmethod
    def _route_static(prompt: str) -> list:
        p = prompt.lower()
        if any(w in p for w in ["x", "*", "+", "-", "/", "%", "factor", "minimize", "maximize",
                                "root", "sqrt", "solve", "find", "^", "equation"]):
            return ["charles-auma"]
        if any(w in p for w in ["color", "sat", "schedule", "graph", "sudoku", "chess",
                                "classify", "predict", "kpi", "accuracy"]):
            return ["charles-science"]
        if any(w in p for w in ["json", "extract", "structured", "list", "fields"]):
            return ["charles-json"]
        return ["charles"]

    @staticmethod
    def _parallel_static(prompt, models, factory_id, endpoint, timeout):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        results = {}
        with ThreadPoolExecutor(max_workers=len(models)) as pool:
            futures = {
                pool.submit(_chat, text=prompt, model=_resolve_model(m),
                            factory_id=factory_id, endpoint=endpoint,
                            session=requests.Session(), timeout=timeout): m
                for m in models
            }
            for f in as_completed(futures):
                results[futures[f]] = f.result()
        best = None
        for m in models:
            r = results.get(m)
            if r and r.ok and (best is None or len(r.text) > len(best.text)):
                best = r
        if best is None:
            best = next(iter(results.values()))
        best.sat_memory["parallel_models"] = list(results.keys())
        return best

    @staticmethod
    def math(prompt, **kw):
        return Charles(prompt, strategy="math", **kw)

    @staticmethod
    def science(prompt, **kw):
        return Charles(prompt, strategy="science", **kw)

    @staticmethod
    def json(prompt, **kw):
        return Charles(prompt, strategy="json", **kw)

    @staticmethod
    def vlm(prompt, image, **kw):
        return Charles(prompt, image=image, **kw)


def VLM(prompt: str, image: bytes, model: str = "charles-json",
         image_type: str = "image/png", json: bool = True,
         factory_id: int = 0, endpoint: str = None, timeout: int = 120) -> LLMResult:
    """
    Vision Language Model — image + text in, structured answer out.

        from monceai import VLM

        r = VLM("what is in this image?", image=open("photo.png","rb").read())
        r = VLM("extract all glass fields", image=pdf_page_bytes)
        r = VLM("describe this chart", image=screenshot, json=False)

        r.text   # raw text
        r.json   # parsed dict (when json=True)

    VLM-capable models: charles-json, sonnet, haiku, nova-pro.
    Default: charles-json (strict JSON + charles memory context).
    """
    if json and model not in ("charles-json",):
        model = "charles-json"

    resolved = _resolve_model(model)

    return _chat(
        text=prompt, image=image, image_type=image_type,
        model=resolved, factory_id=factory_id,
        endpoint=endpoint, timeout=timeout, as_json=json,
    )
