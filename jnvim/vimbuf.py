"""A modal (vim-like) text buffer.

Used for editing the source of a single notebook cell.  Supports normal /
insert / visual / visual-line / replace modes, counts, operators + motions,
a subset of text objects, registers, undo/redo, search and dot-repeat.

Keys arriving here are already normalised by :mod:`jnvim.keys`.
"""

from __future__ import annotations

import re
import string
from typing import List, Optional, Tuple

Pos = Tuple[int, int]

WORD = set(string.ascii_letters + string.digits + "_")
INDENT_RE = re.compile(r"^[ \t]*")

OPENERS = {"(": ")", "[": "]", "{": "}", "<": ">"}
QUOTES = {'"', "'", "`"}
OBJ_ALIASES = {
    "b": "(", ")": "(",
    "B": "{", "}": "{",
    "]": "[",
    ">": "<",
}


def char_class(ch: str, big: bool = False) -> int:
    if ch in (" ", "\t", "\n", ""):
        return 0
    if big:
        return 1
    return 1 if ch in WORD else 2


class VimBuffer:
    """A list-of-lines buffer driven by vim keystrokes."""

    def __init__(self, text: str = "", tabstop: int = 4, expandtab: bool = True):
        self.lines: List[str] = text.split("\n") if text else [""]
        self.row = 0
        self.col = 0
        self.want_col = 0
        self.mode = "normal"
        self.tabstop = tabstop
        self.expandtab = expandtab
        self.modified = False
        self.message = ""
        self.tick = 0

        self._count = ""
        self._op: Optional[str] = None
        self._opcount = 1
        self._prefix = ""          # pending g / z / Z
        self._await: Optional[str] = None   # f F t T r + text-object i/a
        self._register: Tuple[str, bool] = ("", False)

        self._undo: List[Tuple[List[str], int, int]] = []
        self._redo: List[Tuple[List[str], int, int]] = []
        self._group = False

        self.vstart: Optional[Pos] = None
        self.last_find: Optional[Tuple[str, str]] = None
        self.last_search: Tuple[str, int] = ("", 1)

        self._seq: List[str] = []
        self._capturing = False
        self._last_change: Optional[List[str]] = None
        self._replaying = False

    # ------------------------------------------------------------ accessors
    def text(self) -> str:
        return "\n".join(self.lines)

    def set_text(self, text: str) -> None:
        self.lines = text.split("\n") if text else [""]
        self._clamp()

    @property
    def register(self) -> Tuple[str, bool]:
        return self._register

    @register.setter
    def register(self, value: Tuple[str, bool]) -> None:
        self._register = value

    def line(self, row: Optional[int] = None) -> str:
        row = self.row if row is None else row
        if 0 <= row < len(self.lines):
            return self.lines[row]
        return ""

    def selection(self) -> Optional[Tuple[Pos, Pos, bool]]:
        """Normalised visual selection as ``(start, end_inclusive, linewise)``."""
        if self.mode not in ("visual", "vline") or self.vstart is None:
            return None
        a, b = self.vstart, (self.row, self.col)
        if b < a:
            a, b = b, a
        return a, b, self.mode == "vline"

    # ---------------------------------------------------------------- state
    def _clamp(self) -> None:
        self.row = max(0, min(self.row, len(self.lines) - 1))
        limit = len(self.line())
        if self.mode in ("normal", "visual", "vline"):
            limit = max(0, limit - 1)
        self.col = max(0, min(self.col, limit))

    def _snapshot(self) -> None:
        self.tick += 1
        self.modified = True
        if self._group:
            return
        self._undo.append((list(self.lines), self.row, self.col))
        if len(self._undo) > 500:
            self._undo.pop(0)
        self._redo.clear()

    def _enter_insert(self) -> None:
        self.mode = "insert"
        self._group = True

    def _leave_insert(self) -> None:
        self.mode = "normal"
        self._group = False
        self.col = max(0, self.col - 1)
        self._clamp()

    def reset_pending(self) -> None:
        self._count = ""
        self._op = None
        self._prefix = ""
        self._await = None

    @property
    def pending(self) -> str:
        return "%s%s%s%s" % (self._count, self._op or "", self._prefix, self._await or "")

    # ------------------------------------------------------------- entry pt
    def handle_key(self, key: str) -> bool:
        """Feed one normalised key.  Returns False if the key was not used."""
        if self.mode == "insert":
            self._capture(key)
            used = self._insert_key(key)
        elif self.mode == "replace1":
            self._capture(key)
            used = self._replace_one(key)
        else:
            if (not self._replaying and not self._capturing
                    and not self.pending and self.mode == "normal"):
                self._seq = []
            self._capture(key)
            used = self._normal_key(key)
        self._finish_capture()
        return used

    # --------------------------------------------------------- dot recording
    def _capture(self, key: str) -> None:
        if self._replaying:
            return
        if self.mode in ("normal", "visual", "vline") and not self.pending and not self._capturing:
            self._seq = [key]
            self._capturing = True
            self._tick_at_start = self.tick
        elif self._capturing:
            self._seq.append(key)

    def _finish_capture(self) -> None:
        if self._replaying or not self._capturing:
            return
        if self.mode in ("insert", "replace1") or self.pending:
            return  # command still in flight
        if self.tick != getattr(self, "_tick_at_start", self.tick):
            self._last_change = list(self._seq)
        self._capturing = False

    def repeat(self, count: int = 1) -> None:
        if not self._last_change:
            self.message = "nothing to repeat"
            return
        keys = list(self._last_change)
        self._replaying = True
        try:
            for _ in range(count):
                for key in keys:
                    self.handle_key(key)
                if self.mode in ("insert", "replace1"):
                    self.handle_key("<Esc>")
        finally:
            self._replaying = False

    # -------------------------------------------------------- insert mode
    def _insert_key(self, key: str) -> bool:
        if key == "<Esc>":
            self._leave_insert()
            return True
        if key == "<CR>":
            self._snapshot()
            cur = self.line()
            indent = INDENT_RE.match(cur).group(0)
            head, tail = cur[: self.col], cur[self.col:]
            if head.rstrip().endswith(":"):
                indent += " " * self.tabstop if self.expandtab else "\t"
            self.lines[self.row] = head
            self.lines.insert(self.row + 1, indent + tail)
            self.row += 1
            self.col = len(indent)
            return True
        if key in ("<BS>", "<C-h>"):
            self._snapshot()
            if self.col > 0:
                line = self.line()
                back = 1
                if self.expandtab and line[: self.col].strip() == "":
                    rem = self.col % self.tabstop or self.tabstop
                    back = min(rem, self.col)
                self.lines[self.row] = line[: self.col - back] + line[self.col:]
                self.col -= back
            elif self.row > 0:
                prev = self.lines[self.row - 1]
                self.col = len(prev)
                self.lines[self.row - 1] = prev + self.lines[self.row]
                del self.lines[self.row]
                self.row -= 1
            return True
        if key == "<Del>":
            self._snapshot()
            line = self.line()
            if self.col < len(line):
                self.lines[self.row] = line[: self.col] + line[self.col + 1:]
            elif self.row + 1 < len(self.lines):
                self.lines[self.row] = line + self.lines[self.row + 1]
                del self.lines[self.row + 1]
            return True
        if key == "<Tab>":
            self._snapshot()
            pad = " " * (self.tabstop - self.col % self.tabstop) if self.expandtab else "\t"
            self._insert_text(pad)
            return True
        if key == "<C-w>":
            self._snapshot()
            line = self.line()
            i = self.col
            while i > 0 and line[i - 1].isspace():
                i -= 1
            if i > 0:
                cls = char_class(line[i - 1])
                while i > 0 and char_class(line[i - 1]) == cls:
                    i -= 1
            self.lines[self.row] = line[:i] + line[self.col:]
            self.col = i
            return True
        if key == "<C-u>":
            self._snapshot()
            line = self.line()
            start = len(INDENT_RE.match(line).group(0))
            start = start if start < self.col else 0
            self.lines[self.row] = line[:start] + line[self.col:]
            self.col = start
            return True
        if key in ("<Left>", "<Right>", "<Up>", "<Down>", "<Home>", "<End>"):
            self._arrow(key)
            return True
        if len(key) == 1 and (key.isprintable() or key == " "):
            self._snapshot()
            self._insert_text(key)
            return True
        return False

    def _insert_text(self, text: str) -> None:
        line = self.line()
        self.lines[self.row] = line[: self.col] + text + line[self.col:]
        self.col += len(text)

    def _replace_one(self, key: str) -> bool:
        self.mode = "normal"
        if key == "<Esc>" or len(key) != 1:
            return True
        self._snapshot()
        line = self.line()
        if self.col < len(line):
            self.lines[self.row] = line[: self.col] + key + line[self.col + 1:]
        return True

    def _arrow(self, key: str) -> None:
        if key == "<Left>":
            self.col = max(0, self.col - 1)
        elif key == "<Right>":
            self.col = min(len(self.line()), self.col + 1)
        elif key == "<Up>":
            self.row = max(0, self.row - 1)
        elif key == "<Down>":
            self.row = min(len(self.lines) - 1, self.row + 1)
        elif key == "<Home>":
            self.col = 0
        elif key == "<End>":
            self.col = len(self.line())
        self._clamp()

    # -------------------------------------------------------- normal/visual
    def _normal_key(self, key: str) -> bool:
        self.message = ""
        visual = self.mode in ("visual", "vline")

        # waiting for a character argument (f/F/t/T/r) or a text object
        if self._await:
            awaiting, self._await = self._await, None
            return self._resolve_await(awaiting, key)

        if self._prefix:
            prefix, self._prefix = self._prefix, ""
            return self._resolve_prefix(prefix, key)

        if key.isdigit() and not (key == "0" and not self._count):
            self._count += key
            return True

        count = int(self._count) if self._count else None

        # operator pending: a doubled operator is linewise
        if self._op and key == self._op:
            self._count = ""
            n = (self._opcount or 1) * (count or 1)
            start = (self.row, 0)
            end = (min(len(self.lines) - 1, self.row + n - 1), 0)
            op, self._op = self._op, None
            self._apply(op, start, end, linewise=True)
            return True

        if self._op and key in ("i", "a"):
            self._await = key
            return True

        if key in ("d", "c", "y", ">", "<", "=") and not self._op:
            if visual:
                self._visual_operator(key)
                return True
            self._op = key
            self._opcount = count or 1
            self._count = ""
            return True

        if key in ("g", "z", "Z", "["):
            self._prefix = key
            return True

        if key in ("f", "F", "t", "T", "r"):
            self._await = key
            return True

        # motions ------------------------------------------------------
        if self._op == "c" and key in ("w", "W"):
            # vim quirk: cw behaves like ce when the cursor is on a word
            line = self.line()
            if self.col < len(line) and not line[self.col].isspace():
                key = "e" if key == "w" else "E"

        motion = self._motion(key, count)
        if motion is not None:
            target, linewise, inclusive = motion
            if self._op:
                op, self._op = self._op, None
                self._count = ""
                self._apply(op, (self.row, self.col), target, linewise, inclusive)
            else:
                self.row, self.col = target
                if key not in ("j", "k", "<Up>", "<Down>", "<C-d>", "<C-u>"):
                    self.want_col = self.col
                self._clamp()
                self._count = ""
            return True

        if self._op:  # unknown key cancels a pending operator
            self.reset_pending()
            return True

        self._count = ""
        return self._simple_command(key, count, visual)

    # ------------------------------------------------------------- commands
    def _simple_command(self, key: str, count: Optional[int], visual: bool) -> bool:
        n = count or 1

        if key == "<Esc>":
            if visual:
                self.mode = "normal"
                self.vstart = None
                self._clamp()
                return True
            self.reset_pending()
            return False  # let the app leave edit mode

        if key == "v":
            if self.mode == "visual":
                self.mode, self.vstart = "normal", None
            else:
                self.mode, self.vstart = "visual", (self.row, self.col)
            return True
        if key == "V":
            if self.mode == "vline":
                self.mode, self.vstart = "normal", None
            else:
                self.mode, self.vstart = "vline", (self.row, self.col)
            return True
        if key == "o" and visual:
            self.vstart, (self.row, self.col) = (self.row, self.col), self.vstart
            return True

        if visual and key in ("x", "s", "p", "~", "u", "U", "J"):
            if key in ("x", "s"):
                self._visual_operator("d" if key == "x" else "c")
            elif key == "p":
                sel = self.selection()
                text, linewise = self._register
                self._visual_operator("d")
                self._register = (text, linewise)
                self._paste(after=False, count=1)
            elif key in ("~", "u", "U"):
                self._visual_case(key)
            elif key == "J":
                a, b, _ = self.selection()
                self.mode, self.vstart = "normal", None
                self.row = a[0]
                self._join(max(2, b[0] - a[0] + 1))
            return True

        if key in ("i", "I", "a", "A", "o", "O"):
            if key == "i":
                pass
            elif key == "I":
                self.col = self._first_non_blank(self.row)
            elif key == "a":
                self.col = min(len(self.line()), self.col + 1)
            elif key == "A":
                self.col = len(self.line())
            elif key in ("o", "O"):
                self._snapshot()
                indent = INDENT_RE.match(self.line()).group(0)
                if self.line().rstrip().endswith(":"):
                    indent += " " * self.tabstop
                at = self.row + 1 if key == "o" else self.row
                self.lines.insert(at, indent)
                self.row, self.col = at, len(indent)
            self.mode, self.vstart = "normal", None
            self._enter_insert()
            return True

        if key == "x":
            self._snapshot()
            line = self.line()
            end = min(len(line), self.col + n)
            self._register = (line[self.col:end], False)
            self.lines[self.row] = line[: self.col] + line[end:]
            self._clamp()
            return True
        if key == "X":
            self._snapshot()
            line = self.line()
            start = max(0, self.col - n)
            self._register = (line[start:self.col], False)
            self.lines[self.row] = line[:start] + line[self.col:]
            self.col = start
            return True
        if key == "s":
            self._snapshot()
            line = self.line()
            end = min(len(line), self.col + n)
            self._register = (line[self.col:end], False)
            self.lines[self.row] = line[: self.col] + line[end:]
            self._enter_insert()
            return True
        if key == "S":
            self._apply("c", (self.row, 0), (self.row + n - 1, 0), linewise=True)
            return True
        if key == "D":
            self._apply("d", (self.row, self.col), (self.row, len(self.line())), False, False)
            return True
        if key == "C":
            self._apply("c", (self.row, self.col), (self.row, len(self.line())), False, False)
            return True
        if key == "Y":
            self._apply("y", (self.row, 0), (self.row + n - 1, 0), linewise=True)
            return True
        if key in ("p", "P"):
            self._paste(after=(key == "p"), count=n)
            return True
        if key == "J":
            self._join(n + 1 if n > 1 else 2)
            return True
        if key == "~":
            self._snapshot()
            line = self.line()
            end = min(len(line), self.col + n)
            self.lines[self.row] = line[: self.col] + line[self.col:end].swapcase() + line[end:]
            self.col = min(end, max(0, len(line) - 1))
            return True
        if key == "u":
            self.undo()
            return True
        if key == "<C-r>":
            self.redo()
            return True
        if key == ".":
            self.repeat(count or 1)
            return True
        if key == "R":
            self.mode = "replace1"  # single-shot replace; R-as-overwrite is not supported
            return True
        if key in ("n", "N"):
            pattern, direction = self.last_search
            if pattern:
                self.search(pattern, direction if key == "n" else -direction, move=True)
            return True
        if key in ("<Left>", "<Right>", "<Up>", "<Down>", "<Home>", "<End>"):
            self._arrow(key)
            return True
        return False

    def _visual_operator(self, op: str) -> None:
        sel = self.selection()
        if sel is None:
            return
        a, b, linewise = sel
        self.mode, self.vstart = "normal", None
        self._apply(op, a, b, linewise=linewise, inclusive=not linewise)

    def _visual_case(self, key: str) -> None:
        sel = self.selection()
        if sel is None:
            return
        a, b, linewise = sel
        self.mode, self.vstart = "normal", None
        self._snapshot()
        if linewise:
            a, b = (a[0], 0), (b[0], len(self.lines[b[0]]))
        else:
            b = (b[0], b[1] + 1)
        text = self._get_range(a, b)
        new = text.swapcase() if key == "~" else (text.lower() if key == "u" else text.upper())
        self._delete_range(a, b)
        self.row, self.col = a
        self._insert_raw(new)
        self.row, self.col = a
        self._clamp()

    # -------------------------------------------------------------- awaiting
    def _resolve_await(self, awaiting: str, key: str) -> bool:
        if key == "<Esc>" or len(key) != 1:
            self.reset_pending()
            return True
        if awaiting == "r":
            self._snapshot()
            line = self.line()
            n = int(self._count) if self._count else 1
            self._count = ""
            if self.col + n <= len(line):
                self.lines[self.row] = line[: self.col] + key * n + line[self.col + n:]
                self.col += n - 1
            return True
        if awaiting in ("f", "F", "t", "T"):
            count = int(self._count) if self._count else 1
            self.last_find = (awaiting, key)
            target = self._find_char(awaiting, key, count)
            if target is None:
                self._count = ""
                self._op = None
                self.message = "pattern not found: %s" % key
                return True
            if self._op:
                op, self._op = self._op, None
                self._count = ""
                inclusive = awaiting in ("f", "t")
                self._apply(op, (self.row, self.col), target, False, inclusive)
            else:
                self.row, self.col = target
                self.want_col = self.col
                self._count = ""
            return True
        if awaiting in ("i", "a"):  # text object with a pending operator
            rng = self._text_object(awaiting, key)
            op, self._op = self._op, None
            self._count = ""
            if rng is None:
                return True
            start, end, linewise = rng
            if op:
                self._apply(op, start, end, linewise=linewise, inclusive=False)
            return True
        return True

    def _resolve_prefix(self, prefix: str, key: str) -> bool:
        if prefix == "g":
            if key == "g":
                count = int(self._count) if self._count else 1
                target = (min(len(self.lines) - 1, count - 1), 0)
                if self._op:
                    op, self._op = self._op, None
                    self._apply(op, (self.row, 0), target, linewise=True)
                else:
                    self.row, self.col = target
                    self.col = self._first_non_blank(self.row)
                self._count = ""
                return True
            if key in ("u", "U", "~") and self.mode in ("visual", "vline"):
                self._visual_case("u" if key == "u" else ("U" if key == "U" else "~"))
                return True
            if key == "_":
                self.col = self._first_non_blank(self.row)
                return True
        if prefix == "Z":
            self.reset_pending()
            return False  # ZZ / ZQ are handled by the app
        self.reset_pending()
        return True

    # --------------------------------------------------------------- motions
    def _motion(self, key: str, count: Optional[int]):
        """Return ``(target_pos, linewise, inclusive)`` or None."""
        n = count or 1
        row, col = self.row, self.col
        line = self.line()

        if key in ("h", "<BS>", "<Left>"):
            return (row, max(0, col - n)), False, False
        if key in ("l", "<Right>", " "):
            limit = len(line) if self._op else max(0, len(line))
            return (row, min(limit, col + n)), False, False
        if key in ("j", "<Down>", "<C-n>"):
            target = min(len(self.lines) - 1, row + n)
            return self._vertical(target), True if self._op else False, False
        if key in ("k", "<Up>", "<C-p>"):
            target = max(0, row - n)
            return self._vertical(target), True if self._op else False, False
        if key == "+" or key == "<CR>":
            target = min(len(self.lines) - 1, row + n)
            return (target, self._first_non_blank(target)), True if self._op else False, False
        if key == "-":
            target = max(0, row - n)
            return (target, self._first_non_blank(target)), True if self._op else False, False
        if key == "0":
            return (row, 0), False, False
        if key == "^":
            return (row, self._first_non_blank(row)), False, False
        if key == "$":
            target = min(len(self.lines) - 1, row + n - 1)
            return (target, max(0, len(self.lines[target]) - (0 if self._op else 1))), False, False
        if key == "w":
            return self._word_fwd(n, big=False), False, False
        if key == "W":
            return self._word_fwd(n, big=True), False, False
        if key == "b":
            return self._word_back(n, big=False), False, False
        if key == "B":
            return self._word_back(n, big=True), False, False
        if key == "e":
            return self._word_end(n, big=False), False, True
        if key == "E":
            return self._word_end(n, big=True), False, True
        if key == "G":
            target = (count - 1) if count else len(self.lines) - 1
            target = max(0, min(len(self.lines) - 1, target))
            return (target, self._first_non_blank(target)), True, False
        if key == "{":
            return self._paragraph(-1, n), False, False
        if key == "}":
            return self._paragraph(1, n), False, False
        if key == "%":
            match = self._matching_bracket()
            return (match, False, True) if match else None
        if key in (";", ","):
            if not self.last_find:
                return None
            cmd, ch = self.last_find
            if key == ",":
                cmd = {"f": "F", "F": "f", "t": "T", "T": "t"}[cmd]
            target = self._find_char(cmd, ch, n)
            return (target, False, cmd in ("f", "t")) if target else None
        if key == "<C-d>":
            target = min(len(self.lines) - 1, row + max(1, len(self.lines) // 2))
            return self._vertical(target), False, False
        if key == "<C-u>":
            target = max(0, row - max(1, len(self.lines) // 2))
            return self._vertical(target), False, False
        return None

    def _vertical(self, target_row: int) -> Pos:
        self.want_col = max(self.want_col, self.col)
        return target_row, min(self.want_col, max(0, len(self.lines[target_row]) - 1))

    def _first_non_blank(self, row: int) -> int:
        line = self.lines[row] if 0 <= row < len(self.lines) else ""
        stripped = line.lstrip()
        return len(line) - len(stripped) if stripped else 0

    def _char_at(self, row: int, col: int) -> str:
        line = self.lines[row]
        return line[col] if col < len(line) else "\n"

    def _advance(self, pos: Pos) -> Optional[Pos]:
        row, col = pos
        if col < len(self.lines[row]):
            return row, col + 1
        if row + 1 < len(self.lines):
            return row + 1, 0
        return None

    def _retreat(self, pos: Pos) -> Optional[Pos]:
        row, col = pos
        if col > 0:
            return row, col - 1
        if row > 0:
            return row - 1, len(self.lines[row - 1])
        return None

    def _word_fwd(self, count: int, big: bool) -> Pos:
        pos = (self.row, self.col)
        for _ in range(count):
            cls = char_class(self._char_at(*pos), big)
            nxt = self._advance(pos)
            if nxt is None:
                return pos
            pos = nxt
            if cls:
                while char_class(self._char_at(*pos), big) == cls:
                    nxt = self._advance(pos)
                    if nxt is None:
                        return pos
                    pos = nxt
            while char_class(self._char_at(*pos), big) == 0:
                if self._char_at(*pos) == "\n" and not self.lines[pos[0]]:
                    break  # an empty line is a word
                nxt = self._advance(pos)
                if nxt is None:
                    return pos
                pos = nxt
        return pos

    def _word_back(self, count: int, big: bool) -> Pos:
        pos = (self.row, self.col)
        for _ in range(count):
            prev = self._retreat(pos)
            if prev is None:
                return pos
            pos = prev
            while char_class(self._char_at(*pos), big) == 0:
                if self._char_at(*pos) == "\n" and not self.lines[pos[0]]:
                    break
                prev = self._retreat(pos)
                if prev is None:
                    return pos
                pos = prev
            cls = char_class(self._char_at(*pos), big)
            if cls:
                while True:
                    prev = self._retreat(pos)
                    if prev is None or char_class(self._char_at(*prev), big) != cls:
                        break
                    pos = prev
        return pos

    def _word_end(self, count: int, big: bool) -> Pos:
        pos = (self.row, self.col)
        for _ in range(count):
            nxt = self._advance(pos)
            if nxt is None:
                return pos
            pos = nxt
            while char_class(self._char_at(*pos), big) == 0:
                nxt = self._advance(pos)
                if nxt is None:
                    return pos
                pos = nxt
            cls = char_class(self._char_at(*pos), big)
            while True:
                nxt = self._advance(pos)
                if nxt is None or char_class(self._char_at(*nxt), big) != cls:
                    break
                pos = nxt
        return pos

    def _paragraph(self, direction: int, count: int) -> Pos:
        row = self.row
        for _ in range(count):
            row += direction
            while 0 < row < len(self.lines) - 1 and self.lines[row].strip():
                row += direction
            row = max(0, min(len(self.lines) - 1, row))
        return row, 0

    def _find_char(self, cmd: str, ch: str, count: int) -> Optional[Pos]:
        line = self.line()
        col = self.col
        for _ in range(count):
            if cmd in ("f", "t"):
                start = col + (2 if cmd == "t" else 1)
                idx = line.find(ch, min(start, len(line)))
                if idx < 0:
                    return None
                col = idx
            else:
                stop = col - (2 if cmd == "T" else 1)
                if stop < 0:
                    return None
                idx = line.rfind(ch, 0, stop + 1)
                if idx < 0:
                    return None
                col = idx
        if cmd == "t":
            col -= 1
        elif cmd == "T":
            col += 1
        return self.row, max(0, col)

    def _matching_bracket(self) -> Optional[Pos]:
        pairs = {"(": ")", "[": "]", "{": "}"}
        rev = {v: k for k, v in pairs.items()}
        line = self.line()
        col = self.col
        while col < len(line) and line[col] not in pairs and line[col] not in rev:
            col += 1
        if col >= len(line):
            return None
        ch = line[col]
        if ch in pairs:
            depth, pos = 0, (self.row, col)
            while pos is not None:
                cur = self._char_at(*pos)
                if cur == ch:
                    depth += 1
                elif cur == pairs[ch]:
                    depth -= 1
                    if depth == 0:
                        return pos
                pos = self._advance(pos)
        else:
            depth, pos = 0, (self.row, col)
            while pos is not None:
                cur = self._char_at(*pos)
                if cur == ch:
                    depth += 1
                elif cur == rev[ch]:
                    depth -= 1
                    if depth == 0:
                        return pos
                pos = self._retreat(pos)
        return None

    # ---------------------------------------------------------- text objects
    def _text_object(self, kind: str, key: str):
        key = OBJ_ALIASES.get(key, key)
        if key in ("w", "W"):
            big = key == "W"
            line = self.line()
            if not line:
                return (self.row, 0), (self.row, 0), False
            col = min(self.col, len(line) - 1)
            cls = char_class(line[col], big)
            start = col
            while start > 0 and char_class(line[start - 1], big) == cls:
                start -= 1
            end = col
            while end + 1 < len(line) and char_class(line[end + 1], big) == cls:
                end += 1
            if kind == "a":
                trail = end
                while trail + 1 < len(line) and line[trail + 1].isspace():
                    trail += 1
                if trail == end:
                    while start > 0 and line[start - 1].isspace():
                        start -= 1
                end = trail
            return (self.row, start), (self.row, end + 1), False
        if key in QUOTES:
            line = self.line()
            positions = [i for i, ch in enumerate(line) if ch == key and (i == 0 or line[i - 1] != "\\")]
            for i in range(0, len(positions) - 1, 2):
                a, b = positions[i], positions[i + 1]
                if a <= self.col <= b:
                    if kind == "i":
                        return (self.row, a + 1), (self.row, b), False
                    return (self.row, a), (self.row, b + 1), False
            return None
        if key in OPENERS:
            close = OPENERS[key]
            start = self._unmatched_opener(key, close)
            if start is None:
                return None
            end = self._match_forward(start, key, close)
            if end is None:
                return None
            if kind == "i":
                inner_start = self._advance(start)
                if inner_start is None or inner_start > end:
                    return None
                return inner_start, end, False
            return start, (end[0], end[1] + 1), False
        return None

    def _unmatched_opener(self, opener: str, closer: str) -> Optional[Pos]:
        pos: Optional[Pos] = (self.row, self.col)
        cursor = pos
        depth = 0
        while pos is not None:
            ch = self._char_at(*pos)
            if ch == closer and pos != cursor:
                depth += 1
            elif ch == opener:
                if depth == 0:
                    return pos
                depth -= 1
            pos = self._retreat(pos)
        return None

    def _match_forward(self, start: Pos, opener: str, closer: str) -> Optional[Pos]:
        pos: Optional[Pos] = start
        depth = 0
        while pos is not None:
            ch = self._char_at(*pos)
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    return pos
            pos = self._advance(pos)
        return None

    # ------------------------------------------------------------- operators
    def _apply(self, op: str, start: Pos, end: Pos, linewise: bool = False,
               inclusive: bool = False) -> None:
        if end < start:
            start, end = end, start
        if op in (">", "<", "="):
            self._indent(op, start[0], end[0])
            return
        if linewise:
            r1, r2 = start[0], min(end[0], len(self.lines) - 1)
            text = "\n".join(self.lines[r1:r2 + 1]) + "\n"
            self._register = (text, True)
            if op == "y":
                self.row, self.col = r1, self.col
                self._clamp()
                return
            self._snapshot()
            if op == "d":
                del self.lines[r1:r2 + 1]
                if not self.lines:
                    self.lines = [""]
                self.row = min(r1, len(self.lines) - 1)
                self.col = self._first_non_blank(self.row)
            else:  # c
                indent = INDENT_RE.match(self.lines[r1]).group(0)
                self.lines[r1:r2 + 1] = [indent]
                self.row, self.col = r1, len(indent)
                self._enter_insert()
            self._clamp()
            return

        if inclusive:
            end = (end[0], end[1] + 1)
        text = self._get_range(start, end)
        self._register = (text, False)
        if op == "y":
            self.row, self.col = start
            self._clamp()
            return
        self._snapshot()
        self._delete_range(start, end)
        self.row, self.col = start
        if op == "c":
            self._enter_insert()
        self._clamp()

    def _indent(self, op: str, r1: int, r2: int) -> None:
        self._snapshot()
        pad = " " * self.tabstop
        for row in range(r1, min(r2, len(self.lines) - 1) + 1):
            line = self.lines[row]
            if op == ">":
                if line.strip():
                    self.lines[row] = pad + line
            else:
                stripped = line[: self.tabstop].lstrip()
                removed = len(line[: self.tabstop]) - len(stripped)
                self.lines[row] = line[removed:]
        self.mode, self.vstart = "normal", None
        self.row = r1
        self.col = self._first_non_blank(r1)

    def _get_range(self, start: Pos, end: Pos) -> str:
        if start[0] == end[0]:
            return self.lines[start[0]][start[1]:end[1]]
        parts = [self.lines[start[0]][start[1]:]]
        parts.extend(self.lines[start[0] + 1:end[0]])
        last = self.lines[end[0]] if end[0] < len(self.lines) else ""
        parts.append(last[: end[1]])
        return "\n".join(parts)

    def _delete_range(self, start: Pos, end: Pos) -> None:
        if start[0] == end[0]:
            line = self.lines[start[0]]
            self.lines[start[0]] = line[: start[1]] + line[end[1]:]
            return
        head = self.lines[start[0]][: start[1]]
        tail = self.lines[end[0]][end[1]:] if end[0] < len(self.lines) else ""
        self.lines[start[0]:min(end[0], len(self.lines) - 1) + 1] = [head + tail]

    def _insert_raw(self, text: str) -> None:
        parts = text.split("\n")
        line = self.line()
        if len(parts) == 1:
            self.lines[self.row] = line[: self.col] + text + line[self.col:]
            self.col += len(text)
            return
        head, tail = line[: self.col], line[self.col:]
        new = [head + parts[0]] + parts[1:-1] + [parts[-1] + tail]
        self.lines[self.row:self.row + 1] = new
        self.row += len(parts) - 1
        self.col = len(parts[-1])

    def _paste(self, after: bool, count: int) -> None:
        text, linewise = self._register
        if not text:
            self.message = "register empty"
            return
        self._snapshot()
        if linewise:
            body = text[:-1] if text.endswith("\n") else text
            new = body.split("\n") * count
            at = self.row + 1 if after else self.row
            self.lines[at:at] = new
            self.row = at
            self.col = self._first_non_blank(self.row)
        else:
            if after and self.line():
                self.col = min(len(self.line()), self.col + 1)
            self._insert_raw(text * count)
            self.col = max(0, self.col - 1)
        self._clamp()

    def _join(self, count: int) -> None:
        self._snapshot()
        for _ in range(max(1, count - 1)):
            if self.row + 1 >= len(self.lines):
                break
            cur = self.lines[self.row].rstrip()
            nxt = self.lines[self.row + 1].lstrip()
            sep = "" if not cur or not nxt else " "
            self.col = len(cur)
            self.lines[self.row] = cur + sep + nxt
            del self.lines[self.row + 1]
        self._clamp()

    # ------------------------------------------------------------ undo/redo
    def undo(self) -> None:
        if not self._undo:
            self.message = "already at oldest change"
            return
        lines, row, col = self._undo.pop()
        self._redo.append((list(self.lines), self.row, self.col))
        self.lines, self.row, self.col = lines, row, col
        self.tick += 1
        self.modified = True
        self._clamp()

    def redo(self) -> None:
        if not self._redo:
            self.message = "already at newest change"
            return
        lines, row, col = self._redo.pop()
        self._undo.append((list(self.lines), self.row, self.col))
        self.lines, self.row, self.col = lines, row, col
        self.tick += 1
        self.modified = True
        self._clamp()

    # ---------------------------------------------------------------- search
    def search(self, pattern: str, direction: int = 1, move: bool = True) -> bool:
        self.last_search = (pattern, direction)
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            self.message = "bad pattern: %s" % exc
            return False
        order = range(len(self.lines))
        rows = list(order) if direction > 0 else list(reversed(order))
        start = (self.row, self.col)
        # search after the cursor first, then wrap
        for wrap in (False, True):
            for row in rows:
                if not wrap:
                    if direction > 0 and row < start[0]:
                        continue
                    if direction < 0 and row > start[0]:
                        continue
                matches = list(rx.finditer(self.lines[row]))
                if direction < 0:
                    matches.reverse()
                for m in matches:
                    if not wrap and row == start[0]:
                        if direction > 0 and m.start() <= start[1]:
                            continue
                        if direction < 0 and m.start() >= start[1]:
                            continue
                    if move:
                        self.row, self.col = row, m.start()
                        self._clamp()
                    return True
        self.message = "pattern not found: %s" % pattern
        return False
