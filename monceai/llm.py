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
import io
import json as _json
import mimetypes
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import requests


# ─────────────────────────────────────────────────────────────────────
# Unified input coercion — path / Path / bytes / file-like → either
# (a) inline text for the prompt, or (b) multipart binary upload.
# ─────────────────────────────────────────────────────────────────────

# Extensions we inline as text alongside the prompt. Everything else is
# treated as binary and goes out via multipart.
_TEXT_EXTS = {
    ".txt", ".md", ".rst", ".log",
    ".json", ".jsonl", ".ndjson",
    ".csv", ".tsv",
    ".xml", ".html", ".htm", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".c", ".h",
    ".cpp", ".hpp", ".java", ".kt", ".rb", ".sh", ".sql", ".css", ".scss",
}


def _guess_content_type(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    table = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".tif": "image/tiff", ".tiff": "image/tiff",
        ".gif": "image/gif", ".bmp": "image/bmp",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".msg": "application/vnd.ms-outlook",
        ".eml": "message/rfc822",
    }
    if ext in table:
        return table[ext]
    ct, _ = mimetypes.guess_type(name)
    return ct or "application/octet-stream"


def _coerce_input(
    source: Any,
    filename: Optional[str] = None,
) -> Tuple[Optional[str], Optional[Tuple[str, bytes, str]]]:
    """Turn any user-supplied input into either inline text or a multipart tuple.

    Returns ``(inline_text, multipart)``. Exactly one will be non-None.

    Accepts:
        - ``str`` path to an existing file
        - ``pathlib.Path``
        - ``bytes`` / ``bytearray`` (must pass ``filename=`` for type sniffing,
          else we treat as a binary blob with a generic name)
        - file-like with ``.read()``
    """
    # file-like (supports .read()) — read it out first
    if hasattr(source, "read") and callable(source.read):
        data = source.read()
        name = filename or getattr(source, "name", None) or "upload.bin"
        name = os.path.basename(str(name))
        source = data  # fall through to bytes branch
        filename = name

    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
        name = filename or "upload.bin"
        ct = _guess_content_type(name)
        # Any declared text type, or no extension + valid utf-8 → inline
        ext = os.path.splitext(name)[1].lower()
        if ext in _TEXT_EXTS or ct.startswith("text/"):
            try:
                return data.decode("utf-8"), None
            except UnicodeDecodeError:
                pass
        return None, (name, data, ct)

    if isinstance(source, (str, os.PathLike)) and not isinstance(source, bytes):
        # Treat as a filesystem path. If the string isn't actually a path,
        # caller should have passed it as the prompt — we only reach this
        # helper when a file-ish argument is provided.
        path = Path(os.fspath(source))
        if not path.exists():
            raise FileNotFoundError(f"file not found: {path}")
        name = filename or path.name
        ext = path.suffix.lower()
        ct = _guess_content_type(name)
        if ext in _TEXT_EXTS or ct.startswith("text/"):
            try:
                return path.read_text(encoding="utf-8"), None
            except UnicodeDecodeError:
                pass  # fall through to binary
        return None, (name, path.read_bytes(), ct)

    raise TypeError(
        f"unsupported file input: {type(source).__name__} "
        f"(expected path, Path, bytes, or file-like)"
    )


def _inline_file_prompt(prompt: str, text: str, filename: Optional[str]) -> str:
    """Wrap inlined file content under a clear delimiter in the prompt."""
    header = f"[file: {filename}]" if filename else "[file]"
    return f"{prompt}\n\n{header}\n{text}"


_usage_queue = []
_usage_flush_lock = None


def _report_usage(endpoint: str, prompt: str, result: "LLMResult"):
    """Queue usage entry, flush in background batch."""
    import threading
    global _usage_flush_lock
    if _usage_flush_lock is None:
        _usage_flush_lock = threading.Lock()

    sat = result.sat_memory or {}
    entry = {
        "prompt": prompt,
        "answer": result.text,
        "model": result.model,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "elapsed_ms": result.elapsed_ms,
        "zero_llm": bool(sat.get("zero_llm")),
        "fast_path": bool(sat.get("fast_path")),
        "winner": sat.get("winner", ""),
        "sat_memory": sat,
    }
    _usage_queue.append(entry)

    def _flush():
        with _usage_flush_lock:
            batch = list(_usage_queue)
            _usage_queue.clear()
            for e in batch:
                try:
                    requests.post(f"{endpoint}/usage", json=e, timeout=2)
                except Exception:
                    pass

    if len(_usage_queue) >= 10 or not any(t.name == "_usage_flush" for t in threading.enumerate()):
        t = threading.Thread(target=_flush, name="_usage_flush", daemon=True)
        t.start()


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
    "moncey":            "moncey",
    "concierge":         "concierge",
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
             file: Any = None, filename: Optional[str] = None,
             timeout: int = 120) -> LLMResult:
        return _chat(
            text=text, image=image, image_type=image_type,
            model=self.model, factory_id=self.factory_id,
            session_id=self.session_id, endpoint=self.endpoint,
            session=self._http, timeout=timeout,
            file=file, filename=filename,
        )

    def __repr__(self):
        return f"LLMSession(model={self.model!r}, session={self.session_id!r})"


def _chat(text: str, image: bytes = None, image_type: str = "image/png",
          model: str = "charles-science", factory_id: int = 0,
          session_id: str = "", endpoint: str = None,
          session: requests.Session = None, timeout: int = 120,
          as_json: bool = False,
          file: Any = None, filename: Optional[str] = None) -> LLMResult:

    url = f"{(endpoint or DEFAULT_ENDPOINT).rstrip('/')}/v1/chat"
    http = session or requests.Session()

    # Unified file handling: path / Path / bytes / file-like. Text-like
    # payloads (.txt, .json, .csv, ...) are inlined into the prompt so
    # the backend — which only accepts binary multipart — still sees them.
    # Binary payloads (.pdf, .png, .docx, ...) go out as multipart.
    if file is not None:
        display_name = filename
        if display_name is None:
            if isinstance(file, (str, os.PathLike)):
                display_name = os.path.basename(os.fspath(file))
            elif hasattr(file, "name"):
                display_name = os.path.basename(str(file.name))
        inline_text, multipart = _coerce_input(file, filename=filename)
        if inline_text is not None:
            text = _inline_file_prompt(text or "", inline_text, display_name)
        elif multipart is not None:
            image = multipart[1]
            image_type = multipart[2]
            filename = multipart[0]

    data = {"model_id": model, "message": text}
    if factory_id:
        data["factory_id"] = str(factory_id)
    if session_id:
        data["session_id"] = session_id

    files = {}
    if image:
        name = filename or f"image.{image_type.split('/')[-1]}"
        files["file"] = (name, image, image_type)

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
         file: Any = None, filename: Optional[str] = None,
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
        file=file, filename=filename,
    )


class Charles(str):
    """
    Two modes:

        # With text → blocks, returns str
        Charles("6x7")              # → "42"
        Charles("factor 10403")     # → "10403 = 101 × 103"

        # Without text → reusable client, fires parallel futures
        c = Charles()
        a = c("6x7")               # fires in background
        b = c("8x9")               # fires in background
        c("roots of z^2+1=0")      # fires in background
        print(a)                    # blocks on first read
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

    def __new__(cls, prompt: str = None, image: bytes = None, image_type: str = "image/png",
                strategy: str = None, factory_id: int = 0, endpoint: str = None, timeout: int = 90,
                file: Any = None, filename: Optional[str] = None):

        # No prompt → return a reusable client instance (not a str)
        if prompt is None:
            client = object.__new__(_CharlesClient)
            client._endpoint = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
            client._factory_id = factory_id
            client._timeout = timeout
            return client

        # With prompt → block, return str
        ep = (endpoint or DEFAULT_ENDPOINT).rstrip("/")

        if image or file is not None:
            models = ["charles-json"]
        elif strategy and strategy in cls.STRATEGIES:
            models = cls.STRATEGIES[strategy]
        else:
            models = cls._route_static(prompt)

        if len(models) == 1:
            r = _chat(text=prompt, model=_resolve_model(models[0]),
                       factory_id=factory_id, endpoint=ep, timeout=timeout,
                       image=image, image_type=image_type,
                       file=file, filename=filename)
        else:
            r = cls._parallel_static(prompt, models, factory_id, ep, timeout)

        instance = super().__new__(cls, r.text)
        instance.result = r
        _report_usage(ep, prompt, r)
        return instance

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


class _CharlesFuture:
    """Lazy future returned by Charles() client mode."""
    def __init__(self, prompt, endpoint, factory_id, timeout):
        import threading
        self._prompt = prompt
        self._result = None
        self._text = None
        self._done = threading.Event()

        def _compute():
            models = Charles._route_static(prompt)
            if len(models) == 1:
                r = _chat(text=prompt, model=_resolve_model(models[0]),
                           factory_id=factory_id, endpoint=endpoint, timeout=timeout)
            else:
                r = Charles._parallel_static(prompt, models, factory_id, endpoint, timeout)
            self._result = r
            self._text = r.text
            self._done.set()
            _report_usage(endpoint, prompt, r)

        threading.Thread(target=_compute, daemon=True).start()

    @property
    def result(self):
        self._done.wait()
        return self._result

    def __str__(self):
        self._done.wait()
        return self._text

    def __repr__(self):
        if self._done.is_set():
            return self._text[:60]
        return f'[computing {self._prompt[:30]}...]'

    def __format__(self, spec): return format(str(self), spec)
    def __add__(self, other): return str(self) + other
    def __radd__(self, other): return other + str(self)
    def __len__(self): return len(str(self))
    def __bool__(self): self._done.wait(); return bool(self._text)


class _CharlesClient:
    """Reusable client returned by Charles() with no args. Fires parallel futures."""

    def __call__(self, prompt, **kw):
        return _CharlesFuture(prompt, self._endpoint,
                              kw.get("factory_id", self._factory_id),
                              kw.get("timeout", self._timeout))

    def __repr__(self):
        return f'Charles(endpoint={self._endpoint!r})'


class Moncey(str):
    """
    Two modes:

        # With text → blocks, returns str
        Moncey("44.2 feuillete LowE 16mm")  # → "Bonjour..."

        # Without text → reusable client, fires parallel futures
        m = Moncey()
        a = m("44.2 feuillete")     # fires in background
        b = m("devis 20 vitrages")  # fires in background
        print(a)                     # blocks on first read
    """

    def __new__(cls, prompt: str = None, factory_id: int = 3,
                endpoint: str = None, timeout: int = 30):

        if prompt is None:
            client = object.__new__(_MonceyClient)
            client._endpoint = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
            client._factory_id = factory_id
            client._timeout = timeout
            return client

        ep = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
        r = _chat(text=prompt, model="moncey", factory_id=factory_id,
                   endpoint=ep, timeout=timeout)

        instance = super().__new__(cls, r.text)
        instance.result = r
        _report_usage(ep, prompt, r)
        return instance


class _MonceyFuture:
    """Lazy future for Moncey client mode."""
    def __init__(self, prompt, endpoint, factory_id, timeout):
        import threading
        self._prompt = prompt
        self._result = None
        self._text = None
        self._done = threading.Event()

        def _compute():
            r = _chat(text=prompt, model="moncey", factory_id=factory_id,
                       endpoint=endpoint, timeout=timeout)
            self._result = r
            self._text = r.text
            self._done.set()
            _report_usage(endpoint, prompt, r)

        threading.Thread(target=_compute, daemon=True).start()

    @property
    def result(self):
        self._done.wait()
        return self._result

    def __str__(self):
        self._done.wait()
        return self._text

    def __repr__(self):
        if self._done.is_set():
            return self._text[:60]
        return f'[computing {self._prompt[:30]}...]'

    def __format__(self, spec): return format(str(self), spec)
    def __add__(self, other): return str(self) + other
    def __radd__(self, other): return other + str(self)
    def __len__(self): return len(str(self))
    def __bool__(self): self._done.wait(); return bool(self._text)


class _MonceyClient:
    """Reusable client returned by Moncey() with no args."""

    def __call__(self, prompt, **kw):
        return _MonceyFuture(prompt, self._endpoint,
                             kw.get("factory_id", self._factory_id),
                             kw.get("timeout", self._timeout))

    def __repr__(self):
        return f'Moncey(endpoint={self._endpoint!r})'


class Architect(str):
    """
    ASCII schemas on demand. Backed by charles-architect — every response
    is a diagram (DB schema, system architecture, flow chart, ERD).

        from monceai import Architect

        # Blocking — returns the diagram as a str
        schema = Architect("auth service: users, sessions, api keys")
        print(schema)

        # File in — describe an existing system, get a diagram back
        Architect("diagram this repo", file="README.md")

        # Client mode — reusable, fires parallel futures
        a = Architect()
        s1 = a("postgres schema for a glass factory order system")
        s2 = a("sequence diagram for OAuth2 PKCE flow")
        print(s1)   # blocks on first read

        # Access raw LLMResult (tokens, latency, session_id)
        schema.result.elapsed_ms
    """

    def __new__(cls, prompt: str = None, factory_id: int = 0,
                endpoint: str = None, timeout: int = 120,
                file: Any = None, filename: Optional[str] = None):

        if prompt is None and file is None:
            client = object.__new__(_ArchitectClient)
            client._endpoint = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
            client._factory_id = factory_id
            client._timeout = timeout
            return client

        ep = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
        r = _chat(text=prompt or "", model="charles-architect",
                  factory_id=factory_id, endpoint=ep, timeout=timeout,
                  file=file, filename=filename)

        instance = super().__new__(cls, r.text)
        instance.result = r
        _report_usage(ep, prompt or f"file:{filename or 'upload'}", r)
        return instance


class _ArchitectFuture:
    """Lazy future for Architect client mode."""
    def __init__(self, prompt, endpoint, factory_id, timeout,
                 file=None, filename=None):
        import threading
        self._prompt = prompt
        self._result = None
        self._text = None
        self._done = threading.Event()

        def _compute():
            r = _chat(text=prompt or "", model="charles-architect",
                      factory_id=factory_id, endpoint=endpoint,
                      timeout=timeout, file=file, filename=filename)
            self._result = r
            self._text = r.text
            self._done.set()
            _report_usage(endpoint, prompt or f"file:{filename or 'upload'}", r)

        threading.Thread(target=_compute, daemon=True).start()

    @property
    def result(self):
        self._done.wait()
        return self._result

    def __str__(self):
        self._done.wait()
        return self._text

    def __repr__(self):
        if self._done.is_set():
            return self._text[:60]
        return f'[drawing {str(self._prompt)[:30]}...]'

    def __format__(self, spec): return format(str(self), spec)
    def __add__(self, other): return str(self) + other
    def __radd__(self, other): return other + str(self)
    def __len__(self): return len(str(self))
    def __bool__(self): self._done.wait(); return bool(self._text)


class _ArchitectClient:
    """Reusable client returned by Architect() with no args."""

    def __call__(self, prompt=None, file=None, filename=None, **kw):
        return _ArchitectFuture(
            prompt, self._endpoint,
            kw.get("factory_id", self._factory_id),
            kw.get("timeout", self._timeout),
            file=file, filename=filename,
        )

    def __repr__(self):
        return f'Architect(endpoint={self._endpoint!r})'


class Json(dict):
    """
    Text (and/or file) in, JSON out. Blocks on construction, returns a dict.

        from monceai import Json

        Json("list 5 primes")              # → {"primes": [2, 3, 5, 7, 11]}
        Json('{"broken: json}')            # → fixed
        Json("..." + Moncey("..."))        # → chains

        # File in — any type. Text-like files (.txt/.json/.csv/.md) are
        # inlined into the prompt; binary (.pdf/.png/.docx) goes multipart.
        Json("extract the order", file="order.txt")
        Json("extract fields", file="quote.pdf")
        Json("list the items", file=open("items.csv", "rb"))
        Json("parse this", file=pdf_bytes, filename="q.pdf")

        # Image in — still supported for back-compat.
        Json("extract fields", image=open("photo.png","rb").read())

        j = Json("3 colors")
        j["colors"]                        # list access
        print(j)                           # json.dumps(indent=2)

        j.result                           # LLMResult metadata
    """

    def __init__(self, prompt: str = "", factory_id: int = 0,
                 endpoint: str = None, timeout: int = 30,
                 image: bytes = None, image_type: str = "image/png",
                 file: Any = None, filename: Optional[str] = None):
        super().__init__()
        ep = (endpoint or DEFAULT_ENDPOINT).rstrip("/")

        if not prompt and file is None and image is None:
            self.result = LLMResult()
            return

        r = _chat(text=prompt, model="charles-json", factory_id=factory_id,
                   endpoint=ep, timeout=timeout,
                   image=image, image_type=image_type,
                   file=file, filename=filename)
        self.result = r

        try:
            parsed = _json.loads(r.text)
            if isinstance(parsed, dict):
                self.update(parsed)
            elif isinstance(parsed, list):
                self.update({"data": parsed})
            else:
                self.update({"value": parsed})
        except (ValueError, TypeError):
            self.update({"raw": r.text})

        _report_usage(ep, prompt, r)

    def __repr__(self):
        return _json.dumps(dict(self), ensure_ascii=False, indent=2)

    def __str__(self):
        return _json.dumps(dict(self), ensure_ascii=False, indent=2)


def VLM(prompt: str, image: bytes = None, model: str = "charles-json",
         image_type: str = "image/png", json: bool = True,
         file: Any = None, filename: Optional[str] = None,
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

    Accepts ``file=`` as a path/Path/bytes/file-like for any doctype:
    images go out as multipart; .txt/.json/.csv/.md are inlined into
    the prompt so they reach the backend too.
    """
    if json and model not in ("charles-json",):
        model = "charles-json"

    resolved = _resolve_model(model)

    if image is None and file is None:
        raise TypeError("VLM: provide image=bytes or file=path/bytes/file-like")

    return _chat(
        text=prompt, image=image, image_type=image_type,
        model=resolved, factory_id=factory_id,
        endpoint=endpoint, timeout=timeout, as_json=json,
        file=file, filename=filename,
    )


CONCIERGE_ENDPOINT = "https://concierge.aws.monce.ai"


def _concierge_api(path: str, payload: dict, endpoint: str = None, timeout: int = 30):
    url = f"{(endpoint or CONCIERGE_ENDPOINT).rstrip('/')}{path}"
    try:
        r = requests.post(url, json=payload, timeout=timeout)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def _concierge_get(path: str, params: dict = None, endpoint: str = None, timeout: int = 15):
    url = f"{(endpoint or CONCIERGE_ENDPOINT).rstrip('/')}{path}"
    try:
        r = requests.get(url, params=params or {}, timeout=timeout)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def _concierge_chat(text: str, endpoint: str = None, timeout: int = 120) -> LLMResult:
    url = f"{(endpoint or CONCIERGE_ENDPOINT).rstrip('/')}/chat"
    t = time.time()
    try:
        resp = requests.post(url, json={"message": text}, timeout=timeout)
        elapsed_ms = int((time.time() - t) * 1000)
        if resp.status_code != 200:
            return LLMResult(text=f"HTTP {resp.status_code}: {resp.text[:200]}",
                             model="concierge", elapsed_ms=elapsed_ms)
        body = resp.json()
        return LLMResult(
            text=body.get("reply", ""),
            model="concierge",
            elapsed_ms=elapsed_ms,
            sat_memory={"tools_used": body.get("tools_used", []),
                        "concierge_latency_ms": body.get("latency_ms", 0)},
            raw=body,
        )
    except requests.exceptions.Timeout:
        return LLMResult(text="Timeout", model="concierge",
                         elapsed_ms=int((time.time() - t) * 1000))
    except Exception as e:
        return LLMResult(text=f"Error: {e}", model="concierge",
                         elapsed_ms=int((time.time() - t) * 1000))


class Concierge(str):
    """
    Monce knowledge base. Memory + intelligence + Snake tools.

        # Ask → blocks, returns str
        Concierge("what's the accuracy for VIP today?")

        # Teach → remembers, then answers with context
        Concierge("VIP uses warm edge TPS noir 16mm as default spacer")

        # Search / Remember / Forget
        Concierge.remember("44.2 rTherm is the standard for Riou")
        Concierge.search("rTherm")
        Concierge.forget("old pricing info")

        # Client mode → parallel futures
        c = Concierge()
        a = c("standup report")
        print(a)
    """

    def __new__(cls, prompt: str = None, endpoint: str = None, timeout: int = 120):
        if prompt is None:
            client = object.__new__(_ConciergeClient)
            client._endpoint = (endpoint or CONCIERGE_ENDPOINT).rstrip("/")
            client._timeout = timeout
            return client

        ep = (endpoint or CONCIERGE_ENDPOINT).rstrip("/")
        r = _concierge_chat(text=prompt, endpoint=ep, timeout=timeout)
        instance = super().__new__(cls, r.text)
        instance.result = r
        _report_usage(DEFAULT_ENDPOINT, prompt, r)
        return instance

    @staticmethod
    def remember(text: str, source: str = "sdk", tags: list = None,
                 endpoint: str = None) -> bool:
        result = _concierge_api("/remember",
            {"text": text, "source": source, "tags": tags or ["sdk"]},
            endpoint=endpoint)
        return bool(result and result.get("remembered"))

    @staticmethod
    def search(query: str, limit: int = 20, endpoint: str = None) -> list:
        result = _concierge_get("/search",
            {"q": query, "limit": limit}, endpoint=endpoint)
        if not result:
            return []
        return [m.get("text", "") for m in result.get("memories", [])]

    @staticmethod
    def forget(query: str, endpoint: str = None) -> int:
        result = _concierge_api("/forget", {"query": query}, endpoint=endpoint)
        return result.get("forgotten", 0) if result else 0

    @staticmethod
    def memories(limit: int = 50, tag: str = None, endpoint: str = None) -> list:
        params = {"limit": limit}
        if tag:
            params["tag"] = tag
        result = _concierge_get("/memories", params, endpoint=endpoint)
        if not result:
            return []
        return [m.get("text", "") for m in result.get("memories", [])]

    @staticmethod
    def digest(endpoint: str = None) -> list:
        result = _concierge_get("/digest", endpoint=endpoint)
        if not result:
            return []
        return result.get("entries", [])

    @staticmethod
    def kpi(days: int = 1, factory_id: int = None, endpoint: str = None) -> dict:
        params = {"days": days}
        if factory_id:
            params["factory_id"] = factory_id
        return _concierge_get("/kpi", params, endpoint=endpoint) or {}

    @staticmethod
    def intelligence(endpoint: str = None) -> list:
        result = _concierge_get("/intelligence", endpoint=endpoint)
        if not result:
            return []
        return result.get("entries", [])


class _ConciergeFuture:
    def __init__(self, prompt, endpoint, timeout):
        import threading
        self._prompt = prompt
        self._result = None
        self._text = None
        self._done = threading.Event()

        def _compute():
            r = _concierge_chat(text=prompt, endpoint=endpoint, timeout=timeout)
            self._result = r
            self._text = r.text
            self._done.set()
            _report_usage(DEFAULT_ENDPOINT, prompt, r)

        threading.Thread(target=_compute, daemon=True).start()

    @property
    def result(self):
        self._done.wait()
        return self._result

    def __str__(self):
        self._done.wait()
        return self._text

    def __repr__(self):
        if self._done.is_set():
            return self._text[:60]
        return f'[computing {self._prompt[:30]}...]'

    def __format__(self, spec): return format(str(self), spec)
    def __add__(self, other): return str(self) + other
    def __radd__(self, other): return other + str(self)
    def __len__(self): return len(str(self))
    def __bool__(self): self._done.wait(); return bool(self._text)


class _ConciergeClient:
    def __call__(self, prompt, **kw):
        return _ConciergeFuture(prompt, self._endpoint,
                                kw.get("timeout", self._timeout))

    def remember(self, text, **kw):
        return Concierge.remember(text, endpoint=self._endpoint, **kw)

    def search(self, query, **kw):
        return Concierge.search(query, endpoint=self._endpoint, **kw)

    def forget(self, query, **kw):
        return Concierge.forget(query, endpoint=self._endpoint, **kw)

    def __repr__(self):
        return f'Concierge(endpoint={self._endpoint!r})'


# ═══════════════════════════════════════════════════════════════════════════
# Matching — factory-driven field matching (overlay for extracted terms)
# ═══════════════════════════════════════════════════════════════════════════

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


def _matching_call(payload: dict, endpoint: str = None, timeout: int = 30) -> dict:
    """POST /v1/matching with a JSON body. Returns the response dict."""
    url = f"{(endpoint or DEFAULT_ENDPOINT).rstrip('/')}/v1/matching"
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        return resp.json()
    except requests.exceptions.Timeout:
        return {"error": "timeout"}
    except Exception as e:
        return {"error": str(e)}


class Matching(dict):
    """
    Factory-driven field matching — reliability overlay for extracted terms.

        # Client matching — parses free text, identifies the client
        Matching("LGB Menuiserie SAS", factory_id=4)
        # → {"numero_client": "9232", "nom": "LGB MENUISERIE", "confidence": 0.98, ...}

        # Article matching — match a single extracted value against snake.aws
        Matching("44.2 rTherm", field="verre", factory_id=4)
        # → {"num_article": "63442", "denomination": "44.2 rTherm", "confidence": 1.0}

        # Dict overlay — preserves passthrough fields, enriches client block
        Matching({"nom": "ARC ALU", "qty": 50}, factory_id=4)
        # → {"nom": "ARC ALU", "qty": 50, "numero_client": "..."}

        # Client mode — reusable, fires parallel futures
        m = Matching(factory_id=4)
        a = m("LGB")
        b = m("44.2 rTherm", field="verre")
        print(a.get("numero_client"))

    The instance IS a dict. Indexing, `**unpack`, `json.dumps` — all work.
    `.result` attribute carries full metadata (`LLMResult`-shaped).
    """

    _CLIENT_FIELDS = CLIENT_FIELDS
    _ARTICLE_FIELDS = ARTICLE_FIELDS

    def __new__(cls, arg=None, factory_id: int = 3, field: str = None,
                endpoint: str = None, timeout: int = 30):
        # No arg → reusable client
        if arg is None:
            client = object.__new__(_MatchingClient)
            client._endpoint = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
            client._factory_id = factory_id
            client._timeout = timeout
            return client
        # batch list — return list of Matching
        if isinstance(arg, (list, tuple)):
            return [cls(item, factory_id=factory_id, field=field,
                        endpoint=endpoint, timeout=timeout) for item in arg]
        return super().__new__(cls)

    def __init__(self, arg=None, factory_id: int = 3, field: str = None,
                 endpoint: str = None, timeout: int = 30):
        super().__init__()
        if arg is None or isinstance(arg, (list, tuple)):
            # _MatchingClient path, or batch path — already handled in __new__
            self.result = LLMResult()
            return

        ep = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
        self._factory_id = factory_id
        self._field = field

        # Article mode
        if field is not None:
            if field not in self._ARTICLE_FIELDS:
                raise ValueError(
                    f"Matching: unknown field {field!r}. "
                    f"Allowed: {self._ARTICLE_FIELDS}"
                )
            if not isinstance(arg, str):
                raise TypeError(
                    f"Matching: article mode requires a string query, got {type(arg).__name__}"
                )
            t = time.time()
            body = _matching_call(
                {"query": arg, "field": field, "factory_id": factory_id},
                endpoint=ep, timeout=timeout,
            )
            elapsed = int((time.time() - t) * 1000)
            self.update({
                "query": arg,
                "field": field,
                "num_article": body.get("num_article"),
                "denomination": body.get("denomination"),
                "confidence": body.get("confidence"),
                "method": body.get("method"),
                "candidates": body.get("candidates", []),
            })
            self.result = LLMResult(
                text=body.get("denomination") or "",
                model="matching.article",
                elapsed_ms=elapsed,
                sat_memory={"field": field, "factory_id": factory_id,
                            "method": body.get("method")},
                raw=body,
            )
            _report_usage(ep, f"match:{field}:{arg}", self.result)
            return

        # Client mode — route by input type
        if isinstance(arg, str):
            payload = {"text": arg, "factory_id": factory_id}
        elif isinstance(arg, dict):
            # Extract known client fields; also preserve the full dict as base
            cleaned = {k: v for k, v in arg.items()
                       if k in self._CLIENT_FIELDS and v}
            if cleaned:
                payload = {"fields": cleaned, "factory_id": factory_id}
            else:
                payload = None
            # overlay: start with the caller's dict, enrich with match below
            self.update(arg)
        else:
            raise TypeError(
                f"Matching: unsupported input type {type(arg).__name__}"
            )

        if isinstance(arg, dict) and payload is None:
            self.result = LLMResult(
                text="", model="matching.client",
                sat_memory={"reason": "no_client_fields_in_dict"},
            )
            return

        t = time.time()
        body = _matching_call(payload, endpoint=ep, timeout=timeout)
        elapsed = int((time.time() - t) * 1000)

        # Server may return:
        # - legacy client-only: {client_matching, candidates, ...}
        # - dual-mode auto race: {winner, client_matching, article_match, ...}
        winner = body.get("winner")  # None, "client", "article"
        cm = body.get("client_matching") or {}
        am = body.get("article_match") or {}

        if isinstance(arg, str):
            if winner == "article":
                self.update({
                    "parsed": body.get("parsed") or {},
                    "query": arg,
                    "kind": "article",
                    "num_article": am.get("num_article"),
                    "denomination": am.get("denomination"),
                    "confidence": am.get("confidence"),
                    "method": am.get("method"),
                })
                model_tag = "matching.auto.article"
                text_out = am.get("denomination") or ""
            elif winner == "client" or cm.get("numero_client"):
                self.update({
                    "parsed": body.get("parsed") or {},
                    "kind": "client",
                    "numero_client": cm.get("numero_client"),
                    "nom": cm.get("nom"),
                    "confidence": cm.get("confidence"),
                    "method": cm.get("method"),
                    "source": cm.get("source"),
                })
                model_tag = "matching.auto.client"
                text_out = cm.get("nom") or ""
            else:
                # Neither matched — surface candidates
                self.update({
                    "parsed": body.get("parsed") or {},
                    "kind": None,
                    "numero_client": None, "num_article": None,
                    "confidence": 0.0,
                })
                model_tag = "matching.auto.none"
                text_out = ""
        else:
            # dict-overlay: inject match results on top of caller dict
            if cm.get("numero_client"):
                self["numero_client"] = cm.get("numero_client")
            if cm.get("confidence") is not None:
                self["match_confidence"] = cm.get("confidence")
            model_tag = "matching.client"
            text_out = cm.get("nom") or ""

        self.result = LLMResult(
            text=text_out,
            model=model_tag,
            elapsed_ms=elapsed,
            sat_memory={
                "winner": winner,
                "client_match": cm or None,
                "article_match": am or None,
                "client_confidence": body.get("client_confidence"),
                "article_confidence": body.get("article_confidence"),
                "factory_id": factory_id,
                "candidates": body.get("candidates", {}),
            },
            raw=body,
        )
        _report_usage(ep, f"match:auto:{str(arg)[:60]}", self.result)

    def __repr__(self):
        return _json.dumps(dict(self), ensure_ascii=False, indent=2)

    def __str__(self):
        return _json.dumps(dict(self), ensure_ascii=False, indent=2)


class _MatchingFuture:
    """Lazy future for Matching client mode. Acts as dict on resolve."""

    def __init__(self, arg, endpoint, factory_id, field, timeout):
        import threading
        self._arg = arg
        self._field = field
        self._data = None
        self._result = None
        self._done = threading.Event()

        def _compute():
            m = Matching(arg, factory_id=factory_id, field=field,
                         endpoint=endpoint, timeout=timeout)
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

    # dict interface — each blocks
    def __getitem__(self, key): return self._block()[key]
    def __contains__(self, key): return key in self._block()
    def __iter__(self): return iter(self._block())
    def __len__(self): return len(self._block())
    def keys(self): return self._block().keys()
    def values(self): return self._block().values()
    def items(self): return self._block().items()
    def get(self, key, default=None): return self._block().get(key, default)

    def __str__(self):
        return _json.dumps(self._block(), ensure_ascii=False, indent=2)

    def __repr__(self):
        if self._done.is_set():
            return str(self)
        return f'[matching {str(self._arg)[:30]}...]'


class _MatchingClient:
    """Reusable Matching client, returned by Matching() with no args."""

    def __call__(self, arg, field: str = None, **kw):
        return _MatchingFuture(
            arg, self._endpoint,
            kw.get("factory_id", self._factory_id),
            field,
            kw.get("timeout", self._timeout),
        )

    def __repr__(self):
        return f'Matching(endpoint={self._endpoint!r}, factory_id={self._factory_id})'


# ═══════════════════════════════════════════════════════════════════════════
# Calc — exact NP arithmetic via /v1/calc (str subclass, blocks)
# ═══════════════════════════════════════════════════════════════════════════

def _calc_call(expression: str, endpoint: str = None, timeout: int = 10) -> dict:
    url = f"{(endpoint or DEFAULT_ENDPOINT).rstrip('/')}/v1/calc"
    try:
        resp = requests.post(url, json={"expression": expression}, timeout=timeout)
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


class Calc(str):
    """
    Exact Decimal arithmetic. str subclass — the instance IS the result.

        Calc("123x3456")           # → "425088"
        Calc("100/3")              # → "33.333333"
        float(Calc("44.2*1000"))   # → 44200.0
        Calc("1000000x1000000")    # → "1000000000000"

    Operators: x * / % + -. Decimal-backed — multiplication is poly-time
    to verify, NP-hard to invert (factoring).
    """

    def __new__(cls, expression: str, endpoint: str = None, timeout: int = 10):
        if not isinstance(expression, str):
            raise TypeError(f"Calc: expression must be str, got {type(expression).__name__}")

        ep = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
        t = time.time()
        body = _calc_call(expression, endpoint=ep, timeout=timeout)
        elapsed = int((time.time() - t) * 1000)

        text = str(body.get("result", "") or "")
        instance = super().__new__(cls, text)
        instance.expression = expression
        instance.result = LLMResult(
            text=text,
            model="calc",
            elapsed_ms=elapsed,
            sat_memory={"method": body.get("method"), "expression": expression},
            raw=body,
        )
        _report_usage(ep, f"calc:{expression}", instance.result)
        return instance

    def __float__(self):
        return float(str(self))

    def __int__(self):
        return int(float(str(self)))

    def __repr__(self):
        return f'Calc({self.expression!r} = {str(self)!r})'


# ═══════════════════════════════════════════════════════════════════════════
# Diff — raw vs monceai-enhanced side by side (dict subclass, blocks)
# ═══════════════════════════════════════════════════════════════════════════

def _diff_call(prompt: str, model_id: str = "haiku", factory_id: int = 0,
               framework_id: str = "glass", endpoint: str = None,
               timeout: int = 120) -> dict:
    url = f"{(endpoint or DEFAULT_ENDPOINT).rstrip('/')}/v1/diff"
    try:
        resp = requests.post(
            url,
            json={
                "prompt": prompt,
                "model_id": _resolve_model(model_id),
                "factory_id": factory_id,
                "framework_id": framework_id,
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


class Diff(dict):
    """
    Compare the same prompt raw vs monceai-enhanced side by side.

        d = Diff("Quel intercalaire pour 44.2 rTherm?", factory_id=4)
        d["raw"]["response"]           # generic model answer
        d["enhanced"]["response"]      # factory-specific answer
        d.raw_text                     # shortcut
        d.enhanced_text                # shortcut
        d.context_tokens_added         # int
        print(d.report())              # formatted side-by-side

    The instance IS a dict. Prints pretty JSON.
    """

    def __new__(cls, prompt: str, model: str = "haiku", factory_id: int = 0,
                framework_id: str = "glass", endpoint: str = None,
                timeout: int = 120):
        return super().__new__(cls)

    def __init__(self, prompt: str, model: str = "haiku", factory_id: int = 0,
                 framework_id: str = "glass", endpoint: str = None,
                 timeout: int = 120):
        super().__init__()
        ep = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
        t = time.time()
        body = _diff_call(prompt, model_id=model, factory_id=factory_id,
                          framework_id=framework_id, endpoint=ep, timeout=timeout)
        elapsed = int((time.time() - t) * 1000)
        self.update(body)
        diff_meta = body.get("diff", {}) or {}
        self.prompt = prompt
        self.result = LLMResult(
            text=(body.get("enhanced") or {}).get("response", ""),
            model=f"diff/{_resolve_model(model)}",
            elapsed_ms=elapsed,
            sat_memory={
                "context_tokens_added": diff_meta.get("context_tokens_added", 0),
                "raw_tokens": diff_meta.get("raw_tokens", 0),
                "enhanced_tokens": diff_meta.get("enhanced_tokens", 0),
                "factory_id": factory_id,
            },
            raw=body,
        )
        _report_usage(ep, f"diff:{prompt[:60]}", self.result)

    @property
    def raw_text(self) -> str:
        return (self.get("raw") or {}).get("response", "")

    @property
    def enhanced_text(self) -> str:
        return (self.get("enhanced") or {}).get("response", "")

    @property
    def context_tokens_added(self) -> int:
        return (self.get("diff") or {}).get("context_tokens_added", 0)

    def report(self) -> str:
        """Side-by-side formatted report."""
        lines = [
            "═" * 72,
            f"PROMPT: {self.prompt}",
            "─" * 72,
            "RAW (no monceai context):",
            self.raw_text,
            "─" * 72,
            "ENHANCED (monceai-):",
            self.enhanced_text,
            "─" * 72,
            f"Context tokens added: {self.context_tokens_added}",
            "═" * 72,
        ]
        return "\n".join(lines)

    def __str__(self):
        return _json.dumps(dict(self), ensure_ascii=False, indent=2)

    def __repr__(self):
        return f'Diff(prompt={self.prompt!r}, context_tokens_added={self.context_tokens_added})'
