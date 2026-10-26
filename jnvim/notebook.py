"""Minimal .ipynb (nbformat v4) document model.

Deliberately dependency free: we read/write the JSON ourselves so the editor
can open a notebook even when nbformat is not installed.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

CELL_TYPES = ("code", "markdown", "raw")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def _join(src: Any) -> str:
    if isinstance(src, list):
        return "".join(src)
    return src or ""


def _split(text: str) -> List[str]:
    """nbformat stores source/text as a list of lines keeping the newlines."""
    if not text:
        return []
    return text.splitlines(keepends=True)


@dataclass
class Cell:
    cell_type: str = "code"
    source: str = ""
    outputs: List[Dict[str, Any]] = field(default_factory=list)
    execution_count: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    # transient UI state, never serialised
    collapsed: bool = False
    running: bool = False

    @classmethod
    def from_json(cls, raw: Dict[str, Any]) -> "Cell":
        cell_type = raw.get("cell_type", "code")
        if cell_type not in CELL_TYPES:
            cell_type = "raw"
        outputs = []
        for out in raw.get("outputs", []) or []:
            out = dict(out)
            if "text" in out:
                out["text"] = _join(out["text"])
            data = out.get("data")
            if isinstance(data, dict):
                out["data"] = {k: (_join(v) if isinstance(v, list) else v) for k, v in data.items()}
            outputs.append(out)
        return cls(
            cell_type=cell_type,
            source=_join(raw.get("source", "")),
            outputs=outputs if cell_type == "code" else [],
            execution_count=raw.get("execution_count"),
            metadata=raw.get("metadata", {}) or {},
            id=str(raw.get("id") or uuid.uuid4().hex[:8]),
        )

    def to_json(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "cell_type": self.cell_type,
            "id": self.id,
            "metadata": self.metadata,
            "source": _split(self.source),
        }
        if self.cell_type == "code":
            out["execution_count"] = self.execution_count
            serialised = []
            for o in self.outputs:
                o = dict(o)
                if isinstance(o.get("text"), str):
                    o["text"] = _split(o["text"])
                data = o.get("data")
                if isinstance(data, dict):
                    o["data"] = {
                        k: (_split(v) if k.startswith("text/") and isinstance(v, str) else v)
                        for k, v in data.items()
                    }
                serialised.append(o)
            out["outputs"] = serialised
        return out

    def output_text(self) -> List[tuple]:
        """Flatten outputs into ``(line, kind)`` pairs for rendering."""
        lines: List[tuple] = []
        for out in self.outputs:
            kind = "out"
            otype = out.get("output_type")
            text = ""
            if otype == "stream":
                text = out.get("text", "")
                kind = "err" if out.get("name") == "stderr" else "stream"
            elif otype in ("execute_result", "display_data"):
                data = out.get("data", {}) or {}
                if "text/plain" in data:
                    text = data["text/plain"]
                else:
                    mimes = [m for m in data if m != "text/plain"]
                    text = "[%s]" % ", ".join(mimes) if mimes else ""
            elif otype == "error":
                kind = "err"
                tb = out.get("traceback") or []
                text = "\n".join(tb) if tb else "%s: %s" % (
                    out.get("ename", "Error"),
                    out.get("evalue", ""),
                )
            if not text:
                continue
            for line in strip_ansi(text).rstrip("\n").split("\n"):
                lines.append((line.replace("\t", "    "), kind))
        return lines


class Notebook:
    def __init__(self, path: Optional[str] = None):
        self.path = path
        self.cells: List[Cell] = [Cell()]
        self.metadata: Dict[str, Any] = {}
        self.nbformat = 4
        self.nbformat_minor = 5
        self.dirty = False

    # ------------------------------------------------------------------ io
    @classmethod
    def load(cls, path: str) -> "Notebook":
        nb = cls(path)
        if not os.path.exists(path):
            return nb
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        nb.metadata = raw.get("metadata", {}) or {}
        nb.nbformat = raw.get("nbformat", 4)
        nb.nbformat_minor = raw.get("nbformat_minor", 5)
        cells = [Cell.from_json(c) for c in raw.get("cells", [])]
        nb.cells = cells or [Cell()]
        return nb

    def save(self, path: Optional[str] = None) -> str:
        target = path or self.path
        if not target:
            raise ValueError("no file name")
        doc = {
            "cells": [c.to_json() for c in self.cells],
            "metadata": self.metadata,
            "nbformat": self.nbformat,
            "nbformat_minor": max(self.nbformat_minor, 5),
        }
        directory = os.path.dirname(os.path.abspath(target))
        os.makedirs(directory, exist_ok=True)
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, target)
        self.path = target
        self.dirty = False
        return target

    # -------------------------------------------------------------- helpers
    @property
    def kernel_name(self) -> Optional[str]:
        spec = self.metadata.get("kernelspec") or {}
        return spec.get("name")

    def set_kernel(self, name: str, display_name: Optional[str] = None,
                   language: str = "python") -> None:
        self.metadata["kernelspec"] = {
            "name": name,
            "display_name": display_name or name,
            "language": language,
        }

    def language(self) -> str:
        info = self.metadata.get("language_info") or {}
        return info.get("name") or (self.metadata.get("kernelspec") or {}).get("language") or "python"
