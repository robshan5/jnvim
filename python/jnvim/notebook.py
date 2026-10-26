"""Minimal .ipynb (nbformat v4) reader/writer.

Dependency free on purpose: opening a notebook must work even when nbformat is
not installed.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any, Dict, List, Optional

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
CELL_TYPES = ("code", "markdown", "raw")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def join(src: Any) -> str:
    return "".join(src) if isinstance(src, list) else (src or "")


def split(text: str) -> List[str]:
    return text.splitlines(keepends=True) if text else []


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def read(path: str) -> Dict[str, Any]:
    """Return ``{cells, metadata, nbformat, nbformat_minor}`` for a notebook."""
    if not os.path.exists(path):
        return {"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    cells = []
    for item in raw.get("cells", []) or []:
        cell_type = item.get("cell_type", "code")
        if cell_type not in CELL_TYPES:
            cell_type = "raw"
        outputs = []
        for out in item.get("outputs", []) or []:
            out = dict(out)
            if "text" in out:
                out["text"] = join(out["text"])
            data = out.get("data")
            if isinstance(data, dict):
                out["data"] = {
                    k: (join(v) if isinstance(v, list) else v) for k, v in data.items()
                }
            outputs.append(out)
        cells.append({
            "cell_type": cell_type,
            "source": join(item.get("source", "")),
            "outputs": outputs if cell_type == "code" else [],
            "execution_count": item.get("execution_count"),
            "metadata": item.get("metadata", {}) or {},
            "id": str(item.get("id") or new_id()),
        })
    return {
        "cells": cells,
        "metadata": raw.get("metadata", {}) or {},
        "nbformat": raw.get("nbformat", 4),
        "nbformat_minor": raw.get("nbformat_minor", 5),
    }


def write(path: str, doc: Dict[str, Any]) -> str:
    cells = []
    for cell in doc.get("cells", []):
        item: Dict[str, Any] = {
            "cell_type": cell.get("cell_type", "code"),
            "id": cell.get("id") or new_id(),
            "metadata": cell.get("metadata") or {},
            "source": split(cell.get("source", "")),
        }
        if item["cell_type"] == "code":
            item["execution_count"] = cell.get("execution_count")
            outputs = []
            for out in cell.get("outputs") or []:
                out = dict(out)
                if isinstance(out.get("text"), str):
                    out["text"] = split(out["text"])
                data = out.get("data")
                if isinstance(data, dict):
                    out["data"] = {
                        k: (split(v) if k.startswith("text/") and isinstance(v, str) else v)
                        for k, v in data.items()
                    }
                outputs.append(out)
            item["outputs"] = outputs
        cells.append(item)

    body = {
        "cells": cells,
        "metadata": doc.get("metadata") or {},
        "nbformat": doc.get("nbformat", 4),
        "nbformat_minor": max(doc.get("nbformat_minor", 5), 5),
    }
    folder = os.path.dirname(os.path.abspath(path))
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(body, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)
    return path


def output_lines(outputs: List[Dict[str, Any]]) -> List[List[str]]:
    """Flatten nbformat outputs into ``[text, kind]`` pairs for rendering."""
    lines: List[List[str]] = []
    for out in outputs or []:
        otype = out.get("output_type")
        kind, text = "out", ""
        if otype == "stream":
            text = out.get("text", "")
            kind = "err" if out.get("name") == "stderr" else "stream"
        elif otype in ("execute_result", "display_data"):
            data = out.get("data", {}) or {}
            if "text/plain" in data:
                text = data["text/plain"]
            else:
                for mime, payload in data.items():
                    size = len(payload) if isinstance(payload, str) else 0
                    text = "[%s %.1f KB]" % (mime, size / 1024.0)
                    break
        elif otype == "error":
            kind = "err"
            tb = out.get("traceback") or []
            text = "\n".join(tb) if tb else "%s: %s" % (
                out.get("ename", "Error"), out.get("evalue", ""))
        if not text:
            continue
        for line in strip_ansi(text).rstrip("\n").split("\n"):
            lines.append([line.replace("\t", "    "), kind])
    return lines


def language(metadata: Dict[str, Any]) -> str:
    info = metadata.get("language_info") or {}
    spec = metadata.get("kernelspec") or {}
    return info.get("name") or spec.get("language") or "python"


def kernel_name(metadata: Dict[str, Any]) -> Optional[str]:
    return (metadata.get("kernelspec") or {}).get("name")
