"""
monceai.Document — drag in a file, ask questions, get answers.

    from monceai import Document

    # One-shot: file + prompt → str (via __str__)
    answer = str(Document("spec.pdf", prompt="what's the intercalaire?"))

    # Multi-question: file → reusable doc
    doc = Document("spec.pdf")
    doc.ask("what glass thickness?")               # str
    doc.ask("any deadline?", model="concierge")    # str, routes through Concierge
    doc.extract("list all glass lines as JSON")    # dict via Json

Accepts paths, bytes, file-likes, pathlib.Path. Routes through the charles
family: Charles by default (auto-routes to charles-json when a file is
attached), Concierge when you want memory-backed answers, charles-json
directly for structured output.

The instance IS a dict. Prints as JSON metadata when no prompt was given,
prints as the answer when one was.
"""

from __future__ import annotations

import json as _json
import os
from pathlib import Path
from typing import Any, Optional, Union

from .llm import _coerce_input, _guess_content_type, _inline_file_prompt


class Document(dict):
    """File + question wrapper. Dict subclass; `str(doc)` yields the answer
    when `prompt=` was passed at construction."""

    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)

    def __init__(
        self,
        source: Union[str, bytes, os.PathLike, Any],
        prompt: Optional[str] = None,
        model: str = "charles",
        filename: Optional[str] = None,
        factory_id: int = 0,
        endpoint: Optional[str] = None,
        timeout: int = 120,
    ):
        super().__init__()

        # Resolve filename for display / content-type sniffing
        if filename is None:
            if isinstance(source, (str, os.PathLike)) and not isinstance(source, bytes):
                filename = os.path.basename(os.fspath(source))
            elif hasattr(source, "name"):
                filename = os.path.basename(str(source.name))
            else:
                filename = "document.bin"

        self._source = source
        self._filename = filename
        self._model = model
        self._factory_id = factory_id
        self._endpoint = endpoint
        self._timeout = timeout
        self._answer: Optional[str] = None

        self.update({
            "filename": filename,
            "content_type": _guess_content_type(filename),
            "model": model,
        })

        if prompt is not None:
            self._answer = self._call(prompt, model)
            self["prompt"] = prompt
            self["answer"] = self._answer

    # ── Question methods ──────────────────────────────────────────────────

    def ask(self, prompt: str, model: Optional[str] = None) -> str:
        """Ask a question about the document. Returns a string."""
        return self._call(prompt, model or self._model)

    def extract(
        self,
        prompt: str = "Extract the structured content of this document as JSON.",
        schema: Optional[dict] = None,
    ) -> dict:
        """Pull structured fields out of the document. Returns a dict."""
        from .llm import Json
        q = prompt
        if schema:
            q = f"{prompt}\n\nTarget schema:\n{_json.dumps(schema, indent=2)}"
        j = Json(
            q, file=self._source, filename=self._filename,
            endpoint=self._endpoint, timeout=self._timeout,
        )
        return dict(j)

    # ── Dispatch ──────────────────────────────────────────────────────────

    def _call(self, prompt: str, model: str) -> str:
        from .llm import Charles, Concierge, Json, LLM

        m = (model or "charles").lower()

        if m == "concierge":
            # Concierge has no file= parameter. Inline text files directly;
            # binary files get pre-OCR'd through charles-json, then the
            # extracted text is handed to Concierge for the memory-backed
            # answer.
            inline, multipart = _coerce_input(self._source, filename=self._filename)
            if inline is not None:
                enriched = _inline_file_prompt(prompt, inline, self._filename)
            else:
                summary = LLM(
                    "Transcribe this document verbatim as plain text. "
                    "Preserve line breaks, tables, numbers.",
                    file=self._source, filename=self._filename,
                    model="charles-json",
                    endpoint=self._endpoint, timeout=self._timeout,
                ).text
                enriched = _inline_file_prompt(prompt, summary, self._filename)
            return str(Concierge(enriched, endpoint=self._endpoint,
                                 timeout=self._timeout))

        if m in ("charles-json", "json"):
            j = Json(
                prompt, file=self._source, filename=self._filename,
                endpoint=self._endpoint, timeout=self._timeout,
            )
            return _json.dumps(dict(j), ensure_ascii=False, indent=2)

        # Default: Charles (auto-routes to charles-json when file= is set).
        return str(Charles(
            prompt, file=self._source, filename=self._filename,
            factory_id=self._factory_id,
            endpoint=self._endpoint, timeout=self._timeout,
        ))

    # ── str / repr ────────────────────────────────────────────────────────

    def __str__(self) -> str:
        if self._answer is not None:
            return self._answer
        return _json.dumps(dict(self), ensure_ascii=False, indent=2)

    def __repr__(self) -> str:
        if self._answer is not None:
            preview = self._answer[:60].replace("\n", " ")
            return (f"Document(filename={self._filename!r}, "
                    f"model={self._model!r}, answer={preview!r})")
        return f"Document(filename={self._filename!r}, model={self._model!r})"
