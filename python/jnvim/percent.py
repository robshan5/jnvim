"""Jupytext-style percent format: notebook cells <-> plain buffer text.

    # %%                 code cell
    # %% [markdown]      markdown cell, body prefixed with the comment char
    # %% [raw]           raw cell

The Lua side recognises the very same marker, so both halves agree on where a
cell begins.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

MARKER_RE = re.compile(r"^(?P<comment>#|//|--|%)\s*%%(?P<tag>.*)$")
TAG_RE = re.compile(r"\[(markdown|md|raw|code)\]", re.IGNORECASE)

COMMENT = {
    "python": "#", "python3": "#", "julia": "#", "ruby": "#", "r": "#", "sh": "#",
    "bash": "#", "javascript": "//", "typescript": "//", "c": "//", "cpp": "//",
    "rust": "//", "scala": "//", "sql": "--", "haskell": "--", "matlab": "%",
    "octave": "%",
}


def comment_char(language: str) -> str:
    return COMMENT.get((language or "python").lower(), "#")


def marker(language: str, cell_type: str) -> str:
    char = comment_char(language)
    if cell_type == "markdown":
        return "%s %%%% [markdown]" % char
    if cell_type == "raw":
        return "%s %%%% [raw]" % char
    return "%s %%%%" % char


def to_text(cells: List[Dict[str, Any]], language: str = "python") -> str:
    """Render notebook cells as buffer text."""
    char = comment_char(language)
    lines: List[str] = []
    for index, cell in enumerate(cells):
        if index:
            lines.append("")
        cell_type = cell.get("cell_type", "code")
        lines.append(marker(language, cell_type))
        body = (cell.get("source") or "").split("\n")
        while body and not body[-1].strip():
            body.pop()
        if cell_type == "code":
            lines.extend(body)
        else:
            lines.extend((char + " " + line).rstrip() if line else char for line in body)
    if not lines:
        lines = [marker(language, "code"), ""]
    return "\n".join(lines)


def from_text(text: str, language: str = "python") -> List[Dict[str, str]]:
    """Parse buffer text back into ``[{cell_type, source}]``."""
    char = comment_char(language)
    cells: List[Dict[str, str]] = []
    cell_type = None
    body: List[str] = []

    def flush() -> None:
        if cell_type is None:
            return
        source = _trim(body)
        if cell_type != "code":
            source = _uncomment(source, char)
        cells.append({"cell_type": cell_type, "source": source})

    for line in text.split("\n"):
        match = MARKER_RE.match(line)
        if match:
            flush()
            tag = TAG_RE.search(match.group("tag") or "")
            name = (tag.group(1).lower() if tag else "code")
            cell_type = {"md": "markdown"}.get(name, name)
            body = []
        elif cell_type is None:
            if line.strip() or body:
                cell_type = "code"  # text before the first marker is still a cell
                body = [line]
        else:
            body.append(line)
    flush()
    if not cells:
        cells = [{"cell_type": "code", "source": ""}]
    return cells


def _trim(lines: List[str]) -> str:
    out = list(lines)
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def _uncomment(source: str, char: str) -> str:
    out = []
    for line in source.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith(char):
            indent = line[: len(line) - len(stripped)]
            rest = stripped[len(char):]
            out.append(indent + (rest[1:] if rest.startswith(" ") else rest))
        else:
            out.append(line)
    return "\n".join(out)
