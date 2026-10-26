"""Minimal .ipynb (nbformat v4) reader/writer.

Dependency free on purpose: opening a notebook must work even when nbformat is
not installed.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import struct
import uuid
from typing import Any, Dict, List, Optional

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
CELL_TYPES = ("code", "markdown", "raw")

IMAGE_MIMES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}


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


def image_size(data: bytes) -> Optional[tuple]:
    """(width, height) for PNG/GIF without pulling in an image library."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", data[6:10])
    if data[:2] == b"\xff\xd8":  # jpeg: walk the segment headers
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                break
            marker, length = data[index + 1], struct.unpack(">H", data[index + 2:index + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack(">HH", data[index + 5:index + 9])
                return width, height
            index += 2 + length
    return None


def save_image(mime: str, payload: str, folder: str) -> Optional[Dict[str, Any]]:
    """Write one image output to `folder`; returns its path and pixel size."""
    extension = IMAGE_MIMES.get(mime)
    if extension is None or not payload:
        return None
    if mime == "image/svg+xml":
        data = payload.encode("utf-8")
    else:
        try:
            data = base64.b64decode(payload, validate=False)
        except (binascii.Error, ValueError):
            return None
    name = hashlib.sha1(data).hexdigest()[:16] + extension
    path = os.path.join(folder, name)
    if not os.path.exists(path):
        os.makedirs(folder, exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
    size = image_size(data)
    return {
        "path": path,
        "mime": mime,
        "bytes": len(data),
        "width": size[0] if size else None,
        "height": size[1] if size else None,
    }


def output_lines(outputs: List[Dict[str, Any]], image_dir: Optional[str] = None) -> List[list]:
    """Flatten nbformat outputs into ``[text, kind]`` pairs for rendering.

    Image outputs become ``[text, "image", info]`` when `image_dir` is given.
    """
    lines: List[list] = []
    for out in outputs or []:
        otype = out.get("output_type")
        kind, text = "out", ""
        if otype == "stream":
            text = out.get("text", "")
            kind = "err" if out.get("name") == "stderr" else "stream"
        elif otype in ("execute_result", "display_data"):
            data = out.get("data", {}) or {}
            image = next((mime for mime in data if mime in IMAGE_MIMES), None)
            if image:
                info = save_image(image, data[image], image_dir) if image_dir else None
                size = ("%dx%d" % (info["width"], info["height"])
                        if info and info["width"] else "%.1f KB" % (len(data[image]) / 1024.0))
                entry = ["[%s %s]" % (image, size), "image"]
                if info:
                    entry.append(info)
                lines.append(entry)
                if "text/plain" not in data:
                    continue
            if "text/plain" in data:
                text = data["text/plain"]
            elif not image:
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
