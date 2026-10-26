"""Normalise curses key events into vim-style key names."""

from __future__ import annotations

import curses

SPECIAL = {
    curses.KEY_UP: "<Up>",
    curses.KEY_DOWN: "<Down>",
    curses.KEY_LEFT: "<Left>",
    curses.KEY_RIGHT: "<Right>",
    curses.KEY_HOME: "<Home>",
    curses.KEY_END: "<End>",
    curses.KEY_NPAGE: "<PageDown>",
    curses.KEY_PPAGE: "<PageUp>",
    curses.KEY_BACKSPACE: "<BS>",
    curses.KEY_DC: "<Del>",
    curses.KEY_ENTER: "<CR>",
    curses.KEY_RESIZE: "<Resize>",
    curses.KEY_BTAB: "<S-Tab>",
    curses.KEY_IC: "<Insert>",
}

CTRL_NAMES = {
    0: "<C-@>", 9: "<Tab>", 10: "<CR>", 13: "<CR>", 27: "<Esc>", 127: "<BS>",
}


def normalise(ch) -> str:
    if isinstance(ch, int):
        if ch in SPECIAL:
            return SPECIAL[ch]
        if 0 <= ch < 256:
            return normalise(chr(ch))
        return "<K%d>" % ch
    if not ch:
        return ""
    code = ord(ch[0])
    if code in CTRL_NAMES:
        return CTRL_NAMES[code]
    if code < 32:
        return "<C-%s>" % chr(code + 96)
    if code == 127:
        return "<BS>"
    return ch


def printable(key: str) -> bool:
    return len(key) == 1 and (key.isprintable() or key == " ")
