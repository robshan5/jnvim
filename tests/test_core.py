"""Smoke tests for the vim engine and the notebook model (no curses needed)."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jnvim.notebook import Cell, Notebook  # noqa: E402
from jnvim.vimbuf import VimBuffer  # noqa: E402

FAILED = []


def check(name, got, want):
    if got != want:
        FAILED.append("%s\n   got : %r\n   want: %r" % (name, got, want))


def feed(buf, keys):
    for key in keys:
        buf.handle_key(key)
    return buf


KEY_RE = re.compile(r"<[A-Za-z][A-Za-z0-9-]*>")


def keys(seq):
    """Expand a string into keys; a '<Name>' group stays a single key."""
    out, i = [], 0
    while i < len(seq):
        m = KEY_RE.match(seq, i)
        if m:
            out.append(m.group(0))
            i = m.end()
        else:
            out.append(seq[i])
            i += 1
    return out


def t(name, text, seq, expected, cursor=None):
    buf = VimBuffer(text)
    feed(buf, keys(seq))
    check(name, buf.text(), expected)
    if cursor is not None:
        check(name + " [cursor]", (buf.row, buf.col), cursor)


# --------------------------------------------------------------- motions
t("x deletes char", "hello", "x", "ello")
t("3x", "hello", "3x", "lo")
t("dw", "foo bar baz", "dw", "bar baz")
t("d2w", "foo bar baz", "d2w", "baz")
t("dd", "a\nb\nc", "dd", "b\nc")
t("2dd", "a\nb\nc", "2dd", "c")
t("dj", "a\nb\nc", "dj", "c")
t("yyp", "a\nb", "yyp", "a\na\nb")
t("D", "hello world", "wD", "hello ")
t("C+insert", "hello world", "wCthere<Esc>", "hello there")
t("cw", "foo bar", "cwbaz<Esc>", "baz bar")
t("ciw", "foo bar", "wciwbaz<Esc>", "foo baz")
t("ci(", "f(a, b)", "f(ci(x<Esc>", "f(x)")
t('di"', 'say "hi there" ok', 'fhdi"', 'say "" ok')
t("A appends", "ab", "Acd<Esc>", "abcd")
t("I inserts at bol", "  ab", "Ix<Esc>", "  xab")
t("o opens below", "a", "ob<Esc>", "a\nb")
t("O opens above", "a", "Ob<Esc>", "b\na")
t("$ and a", "ab\ncd", "$ax<Esc>", "abx\ncd")
t("G then dd", "a\nb\nc", "Gdd", "a\nb")
t("gg then x", "ab\ncd", "Ggglx", "a\ncd")
t("f then dt", "a.b.c", "d2f.", "c")
t("J joins", "a\nb", "J", "a b")
t("r replaces", "cat", "rb", "bat")
t("~ toggles case", "abc", "~~", "ABc")
t("p charwise", "abc", "ylp", "aabc")
t("P linewise", "a\nb", "yyjP", "a\na\nb")
t("undo", "abc", "xxu", "bc")
t("redo", "abc", "xxu<C-r>", "c")
t("dot repeat", "aaaa", "x.", "aa")
t("dot repeat insert", "x\ny", "ofoo<Esc>j.", "x\nfoo\ny\nfoo")
t("visual d", "abcdef", "vlld", "def")
t("visual line d", "a\nb\nc", "jVd", "a\nc")
t("visual y p", "abc", "vly$p", "abcab")
t("indent >>", "a\nb", ">>", "    a\nb")
t("unindent <<", "    a", "<<", "a")
t("visual indent", "a\nb", "Vj>", "    a\n    b")
t("autoindent on enter", "    a", "A<CR>b<Esc>", "    a\n    b")
t("colon autoindent", "if x:", "A<CR>pass<Esc>", "if x:\n    pass")
t("C-w in insert", "foo bar", "A<C-w>baz<Esc>", "foo baz")
t("backspace unindents", "        x", "I<BS><Esc>", "    x")
t("w motion over lines", "ab\ncd", "wx", "ab\nd")
t("e motion", "foo bar", "de", " bar")
t("b motion", "foo bar", "$bD", "foo ")
t("% matching", "(ab)c", "%x", "(abc")
t("0 and ^", "  ab", "$^x", "  b")
t("{ }", "a\n\nb", "}jx", "a\n\n")
t("counted G", "a\nb\nc", "2Gdd", "a\nc")
t("S clears line", "  foo", "Sbar<Esc>", "  bar")
t("s substitutes", "abc", "sX<Esc>", "Xbc")
t("cc keeps indent", "    foo", "ccbar<Esc>", "    bar")

# search
buf = VimBuffer("alpha\nbeta\ngamma")
buf.search("gam", 1)
check("search", (buf.row, buf.col), (2, 0))
buf.search("a", -1)
check("search back", buf.row, 1)

# cursor clamping in normal mode
buf = VimBuffer("abc")
feed(buf, keys("$"))
check("$ cursor", buf.col, 2)
feed(buf, keys("lllll"))
check("l clamps", buf.col, 2)

# --------------------------------------------------------------- notebook
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "demo.ipynb")
    nb = Notebook(path)
    nb.cells = [
        Cell(cell_type="code", source="print('hi')", execution_count=1,
             outputs=[{"output_type": "stream", "name": "stdout", "text": "hi\n"}]),
        Cell(cell_type="markdown", source="# title\ntext"),
    ]
    nb.set_kernel("python3")
    nb.save()
    raw = json.load(open(path, encoding="utf-8"))
    check("nbformat", raw["nbformat"], 4)
    check("source is a list", raw["cells"][0]["source"], ["print('hi')"])
    check("md has no outputs", "outputs" in raw["cells"][1], False)

    again = Notebook.load(path)
    check("roundtrip cells", len(again.cells), 2)
    check("roundtrip source", again.cells[1].source, "# title\ntext")
    check("kernel name", again.kernel_name, "python3")
    check("output text", again.cells[0].output_text(), [("hi", "stream")])

    err = Cell(outputs=[{"output_type": "error", "ename": "ValueError",
                         "evalue": "bad", "traceback": ["\x1b[31mValueError\x1b[0m: bad"]}])
    check("ansi stripped", err.output_text(), [("ValueError: bad", "err")])

if FAILED:
    print("FAILED %d test(s):\n" % len(FAILED))
    print("\n\n".join(FAILED))
    raise SystemExit(1)
print("all tests passed")
