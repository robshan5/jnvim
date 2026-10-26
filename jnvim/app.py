"""Curses front-end: a vim-flavoured terminal notebook editor."""

from __future__ import annotations

import copy
import curses
import os
import re
import sys
from dataclasses import dataclass
from typing import List, Optional

from .kernel import Kernel, list_kernels
from .keys import normalise, printable
from .notebook import Cell, Notebook, strip_ansi
from .vimbuf import VimBuffer

MODE_NB = "notebook"
MODE_EDIT = "edit"

HELP = """\
 jnvim - vim-style terminal notebook

 NOTEBOOK MODE (cell navigation)
   j / k            next / previous cell         (count works: 3j)
   gg / G           first / last cell
   <C-d> / <C-u>    scroll half a screen
   <CR>             edit cell (cell NORMAL mode)
   i / I / a / A    edit cell and enter INSERT
   o / O            new code cell below / above and edit
   dd / yy / x      delete / yank / cut cell      (3dd works)
   p / P            paste cell below / above
   J / K            move cell down / up
   u / <C-r>        undo / redo a notebook edit
   <Space>          run cell and move to the next one
   s                run cell, stay here
   A (shift)        run every cell
   m / c / t        change cell type: markdown / code / raw
   C                clear this cell's output
   z                collapse / expand this cell's output
   / ?  n / N       search cell sources, next / previous match
   ZZ / ZQ          save and quit / quit without saving
   ?                this help      :            command line

 CELL EDIT MODE (full modal editing)
   NORMAL  h j k l w W b B e E 0 ^ $ gg G { } % f F t T ; , n N
           x X s S D C Y p P J ~ r . u <C-r> v V > <
           operators d c y > < with any motion, and iw aw i" i' i( i[ i{
   INSERT  <Esc> leave, <BS> <Del> <Tab> <C-w> <C-u>, auto-indent
   <Esc>   in NORMAL leaves the cell and returns to notebook mode
   <C-e>   run this cell (from anywhere inside the cell)
   K       ask the kernel for docs about the word under the cursor
   <C-n>   kernel completion for the token before the cursor

 COMMAND LINE
   :w [file]  :wq  :x  :q  :q!  :e file  :new
   :run-all   :restart   :interrupt   :clear-all   :kernel [name]
   :kernels   :set number|nonumber|tabstop=N   :help
"""


@dataclass
class DLine:
    prefix: str = ""
    body: str = ""
    pstyle: str = "dim"
    bstyle: str = "text"
    cell: int = -1
    src_row: int = -1
    header: bool = False


class App:
    def __init__(self, stdscr, path: Optional[str], kernel_name: Optional[str]):
        self.scr = stdscr
        self.nb = Notebook.load(path) if path else Notebook()
        if path and not os.path.exists(path):
            self.message = "%s [New File]" % path
        else:
            self.message = "%s  -  press ? for help" % (path or "[No Name]")
        self.cur = 0
        self.mode = MODE_NB
        self.buf: Optional[VimBuffer] = None
        self.top = 0
        self.left = 0
        self.show_numbers = True
        self.tabstop = 4
        self.running = True
        self.cmdline: Optional[dict] = None
        self.overlay: Optional[dict] = None
        self.clipboard: List[Cell] = []
        self.nb_undo: List[tuple] = []
        self.nb_redo: List[tuple] = []
        self.nb_count = ""
        self.nb_pending = ""
        self.search_pat = ""
        self.search_dir = 1
        self.pending_msg = ""
        self._lines: List[DLine] = []
        self._cursor_xy = None
        self._cmd_history: List[str] = []
        self.styles: dict = {}

        name = kernel_name or self.nb.kernel_name or "python3"
        self.kernel = Kernel(name)
        self.jobs = {}  # msg_id -> Cell

    # ------------------------------------------------------------------ util
    @property
    def cell(self) -> Cell:
        return self.nb.cells[self.cur]

    def notify(self, text: str) -> None:
        self.message = text

    def push_undo(self) -> None:
        self.nb_undo.append((copy.deepcopy(self.nb.cells), self.cur))
        if len(self.nb_undo) > 100:
            self.nb_undo.pop(0)
        self.nb_redo.clear()
        self.nb.dirty = True

    def sync_cell(self) -> None:
        if self.buf is not None and self.buf.modified:
            self.cell.source = self.buf.text()
            self.nb.dirty = True

    # ------------------------------------------------------------- main loop
    def run(self) -> None:
        curses.curs_set(1)
        self.scr.timeout(60)
        while self.running:
            self.poll_kernel()
            self.draw()
            try:
                ch = self.scr.get_wch()
            except curses.error:
                continue
            except KeyboardInterrupt:
                self.kernel.interrupt()
                self.notify("interrupt sent to kernel")
                continue
            key = normalise(ch)
            if key == "<Resize>":
                continue
            try:
                self.handle_key(key)
            except Exception as exc:  # keep the editor alive on a bad key path
                self.notify("error: %s: %s" % (type(exc).__name__, exc))

    # ------------------------------------------------------------ dispatching
    def handle_key(self, key: str) -> None:
        if self.overlay is not None:
            self.handle_overlay(key)
            return
        if self.cmdline is not None:
            self.handle_cmdline(key)
            return
        if self.mode == MODE_EDIT:
            self.handle_edit(key)
        else:
            self.handle_notebook(key)

    # ----------------------------------------------------------- overlay keys
    def handle_overlay(self, key: str) -> None:
        ov = self.overlay
        height = max(1, self.scr.getmaxyx()[0] - 2)
        if key in ("q", "<Esc>", "<CR>", "<Space>"):
            self.overlay = None
        elif key in ("j", "<Down>"):
            ov["scroll"] = min(max(0, len(ov["lines"]) - height), ov["scroll"] + 1)
        elif key in ("k", "<Up>"):
            ov["scroll"] = max(0, ov["scroll"] - 1)
        elif key in ("<C-d>", "<PageDown>"):
            ov["scroll"] = min(max(0, len(ov["lines"]) - height), ov["scroll"] + height // 2)
        elif key in ("<C-u>", "<PageUp>"):
            ov["scroll"] = max(0, ov["scroll"] - height // 2)
        elif key == "g":
            ov["scroll"] = 0
        elif key == "G":
            ov["scroll"] = max(0, len(ov["lines"]) - height)

    def show_overlay(self, title: str, text: str) -> None:
        lines = text.replace("\t", "    ").split("\n")
        self.overlay = {"title": title, "lines": lines, "scroll": 0}

    # --------------------------------------------------------- notebook mode
    def handle_notebook(self, key: str) -> None:
        self.message = ""
        pending, self.nb_pending = self.nb_pending, ""

        if pending == "g":
            if key == "g":
                self.goto_cell((int(self.nb_count) - 1) if self.nb_count else 0)
            self.nb_count = ""
            return
        if pending == "Z":
            if key == "Z":
                self.cmd_write()
                self.quit(force=not self.nb.dirty)
            elif key == "Q":
                self.quit(force=True)
            return
        if pending in ("d", "y"):
            if key == pending:
                count = int(self.nb_count or 1)
                self.yank_cells(count)
                if pending == "d":
                    self.delete_cells(count)
            self.nb_count = ""
            return

        if key.isdigit() and not (key == "0" and not self.nb_count):
            self.nb_count += key
            return
        count = int(self.nb_count) if self.nb_count else None
        self.nb_count = ""
        n = count or 1

        if key in ("j", "<Down>", "<C-n>"):
            self.goto_cell(self.cur + n)
        elif key in ("k", "<Up>", "<C-p>"):
            self.goto_cell(self.cur - n)
        elif key == "G":
            self.goto_cell((count - 1) if count else len(self.nb.cells) - 1)
        elif key in ("g", "Z", "d", "y"):
            self.nb_pending = key
            self.nb_count = str(count) if count else ""
        elif key in ("<C-d>", "<PageDown>"):
            self.goto_cell(self.cur + max(1, len(self.nb.cells) // 4 or 1))
        elif key in ("<C-u>", "<PageUp>"):
            self.goto_cell(self.cur - max(1, len(self.nb.cells) // 4 or 1))
        elif key == "<CR>":
            self.enter_edit()
        elif key in ("i", "I", "a"):
            self.enter_edit()
            self.buf.handle_key(key)
        elif key == "A":
            self.run_all()
        elif key in ("o", "O"):
            self.push_undo()
            at = self.cur + 1 if key == "o" else self.cur
            self.nb.cells.insert(at, Cell())
            self.cur = at
            self.enter_edit()
            self.buf.handle_key("i")
        elif key == "x":
            self.yank_cells(n)
            self.delete_cells(n)
        elif key in ("p", "P"):
            self.paste_cells(after=(key == "p"))
        elif key == "J":
            self.move_cell(1)
        elif key == "K":
            self.move_cell(-1)
        elif key == "u":
            self.undo_nb()
        elif key == "<C-r>":
            self.redo_nb()
        elif key == " ":
            self.run_cell(advance=True)
        elif key == "s":
            self.run_cell(advance=False)
        elif key in ("m", "c", "t"):
            self.set_cell_type({"m": "markdown", "c": "code", "t": "raw"}[key])
        elif key == "C":
            self.push_undo()
            self.cell.outputs = []
            self.cell.execution_count = None
        elif key == "z":
            self.cell.collapsed = not self.cell.collapsed
        elif key in ("/", "?"):
            self.cmdline = {"prefix": key, "text": ""}
        elif key in ("n", "N"):
            if self.search_pat:
                direction = self.search_dir if key == "n" else -self.search_dir
                self.search_cells(self.search_pat, direction)
        elif key == ":":
            self.cmdline = {"prefix": ":", "text": ""}
        elif key == "<C-e>":
            self.run_cell(advance=False)
        elif key == "<C-c>":
            self.kernel.interrupt()
            self.notify("interrupt sent to kernel")
        elif key == "<Esc>":
            pass
        else:
            self.notify("unmapped key %s  (press ? for help)" % key)

    # ------------------------------------------------------------- edit mode
    def enter_edit(self) -> None:
        self.buf = VimBuffer(self.cell.source, tabstop=self.tabstop)
        self.buf.mode = "normal"
        self.mode = MODE_EDIT
        self.left = 0

    def leave_edit(self) -> None:
        self.sync_cell()
        self.buf = None
        self.mode = MODE_NB
        self.left = 0

    def handle_edit(self, key: str) -> None:
        buf = self.buf
        if key == "<C-e>":
            self.sync_cell()
            self.run_cell(advance=False)
            return
        if buf.mode == "normal":
            if key == ":":
                self.sync_cell()
                self.cmdline = {"prefix": ":", "text": ""}
                return
            if key in ("/", "?"):
                self.cmdline = {"prefix": key, "text": "", "buffer": True}
                return
            if key == "K":
                self.kernel_inspect()
                return
            if key == "Z":
                self.leave_edit()
                self.nb_pending = "Z"
                return
        if buf.mode == "insert" and key == "<C-n>":
            self.kernel_complete()
            return
        used = buf.handle_key(key)
        if not used and key == "<Esc>" and buf.mode == "normal":
            self.leave_edit()
            return
        if buf.message:
            self.notify(buf.message)
            buf.message = ""
        self.sync_cell()

    # ------------------------------------------------------------- cmdline
    def handle_cmdline(self, key: str) -> None:
        cl = self.cmdline
        if key == "<Esc>":
            self.cmdline = None
            return
        if key == "<CR>":
            self.cmdline = None
            text = cl["text"]
            if cl["prefix"] == ":":
                if text:
                    self._cmd_history.append(text)
                self.exec_command(text)
            else:
                direction = 1 if cl["prefix"] == "/" else -1
                if cl.get("buffer") and self.buf is not None:
                    self.buf.search(text or self.buf.last_search[0], direction)
                    if self.buf.message:
                        self.notify(self.buf.message)
                        self.buf.message = ""
                else:
                    self.search_pat = text or self.search_pat
                    self.search_dir = direction
                    self.search_cells(self.search_pat, direction)
            return
        if key in ("<BS>", "<C-h>"):
            if cl["text"]:
                cl["text"] = cl["text"][:-1]
            else:
                self.cmdline = None
            return
        if key == "<C-u>":
            cl["text"] = ""
            return
        if key == "<C-w>":
            cl["text"] = re.sub(r"\S+\s*$", "", cl["text"])
            return
        if key == "<Up>" and cl["prefix"] == ":" and self._cmd_history:
            cl["text"] = self._cmd_history[-1]
            return
        if printable(key):
            cl["text"] += key

    def exec_command(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        parts = text.split()
        cmd, args = parts[0], parts[1:]
        arg = " ".join(args)

        if cmd in ("w", "write"):
            self.cmd_write(arg or None)
        elif cmd in ("wq", "x"):
            if self.cmd_write(arg or None):
                self.quit(force=True)
        elif cmd == "q":
            self.quit(force=False)
        elif cmd in ("q!", "quit!"):
            self.quit(force=True)
        elif cmd in ("wq!",):
            self.cmd_write(arg or None)
            self.quit(force=True)
        elif cmd in ("e", "edit"):
            if not arg:
                self.notify("usage: :e <file.ipynb>")
            elif self.nb.dirty:
                self.notify("no write since last change (add ! to override)")
            else:
                self.open(arg)
        elif cmd in ("e!", "edit!"):
            self.open(arg)
        elif cmd == "new":
            self.nb = Notebook()
            self.cur = 0
            self.mode = MODE_NB
            self.buf = None
        elif cmd in ("run-all", "runall"):
            self.run_all()
        elif cmd == "restart":
            self.kernel.restart()
            self.notify("restarting kernel ...")
        elif cmd == "interrupt":
            self.kernel.interrupt()
            self.notify("interrupt sent")
        elif cmd in ("clear-all", "clearall"):
            self.push_undo()
            for cell in self.nb.cells:
                cell.outputs = []
                cell.execution_count = None
            self.notify("cleared all outputs")
        elif cmd == "kernel":
            if arg:
                self.kernel.shutdown()
                self.kernel = Kernel(arg)
                self.nb.set_kernel(arg)
                self.nb.dirty = True
                self.kernel.start_async()
                self.notify("starting kernel %s" % arg)
            else:
                self.notify("kernel: %s (%s)" % (self.kernel.name, self.kernel.state))
        elif cmd == "kernels":
            specs = list_kernels()
            body = "\n".join("  %-20s %s" % (k, v) for k, v in sorted(specs.items()))
            self.show_overlay("available kernels", body or "  (none found)")
        elif cmd == "set":
            self.cmd_set(arg)
        elif cmd in ("h", "help"):
            self.show_overlay("help", HELP)
        elif cmd.isdigit():
            self.goto_cell(int(cmd) - 1)
        else:
            self.notify("not an editor command: %s" % cmd)

    def cmd_set(self, arg: str) -> None:
        if arg in ("number", "nu"):
            self.show_numbers = True
        elif arg in ("nonumber", "nonu"):
            self.show_numbers = False
        elif arg.startswith("tabstop=") or arg.startswith("ts="):
            try:
                self.tabstop = max(1, int(arg.split("=", 1)[1]))
                if self.buf:
                    self.buf.tabstop = self.tabstop
            except ValueError:
                self.notify("bad value: %s" % arg)
        else:
            self.notify("unknown option: %s" % arg)

    def cmd_write(self, path: Optional[str] = None) -> bool:
        self.sync_cell()
        target = path or self.nb.path
        if not target:
            self.notify("no file name (use :w <file.ipynb>)")
            return False
        if not target.endswith(".ipynb"):
            target += ".ipynb"
        try:
            self.nb.save(target)
        except OSError as exc:
            self.notify("write failed: %s" % exc)
            return False
        self.notify('"%s" written' % target)
        return True

    def open(self, path: str) -> None:
        try:
            self.nb = Notebook.load(path)
        except (OSError, ValueError) as exc:
            self.notify("cannot open %s: %s" % (path, exc))
            return
        self.cur = 0
        self.top = 0
        self.mode = MODE_NB
        self.buf = None
        self.nb_undo.clear()
        self.notify('"%s" %d cells' % (path, len(self.nb.cells)))

    def quit(self, force: bool) -> None:
        self.sync_cell()
        if self.nb.dirty and not force:
            self.notify("no write since last change (:q! to override, :wq to save)")
            return
        self.running = False

    # ------------------------------------------------------------ cell edits
    def goto_cell(self, index: int) -> None:
        self.cur = max(0, min(len(self.nb.cells) - 1, index))

    def yank_cells(self, count: int) -> None:
        self.clipboard = copy.deepcopy(self.nb.cells[self.cur:self.cur + count])
        self.notify("%d cell(s) yanked" % len(self.clipboard))

    def delete_cells(self, count: int) -> None:
        self.push_undo()
        del self.nb.cells[self.cur:self.cur + count]
        if not self.nb.cells:
            self.nb.cells = [Cell()]
        self.cur = min(self.cur, len(self.nb.cells) - 1)

    def paste_cells(self, after: bool) -> None:
        if not self.clipboard:
            self.notify("nothing to paste")
            return
        self.push_undo()
        at = self.cur + 1 if after else self.cur
        copies = copy.deepcopy(self.clipboard)
        for c in copies:
            c.id = os.urandom(4).hex()
        self.nb.cells[at:at] = copies
        self.cur = at

    def move_cell(self, delta: int) -> None:
        target = self.cur + delta
        if not (0 <= target < len(self.nb.cells)):
            return
        self.push_undo()
        cells = self.nb.cells
        cells[self.cur], cells[target] = cells[target], cells[self.cur]
        self.cur = target

    def set_cell_type(self, kind: str) -> None:
        if self.cell.cell_type == kind:
            return
        self.push_undo()
        self.cell.cell_type = kind
        if kind != "code":
            self.cell.outputs = []
            self.cell.execution_count = None

    def undo_nb(self) -> None:
        if not self.nb_undo:
            self.notify("already at oldest change")
            return
        cells, cur = self.nb_undo.pop()
        self.nb_redo.append((copy.deepcopy(self.nb.cells), self.cur))
        self.nb.cells, self.cur = cells, min(cur, len(cells) - 1)
        self.nb.dirty = True

    def redo_nb(self) -> None:
        if not self.nb_redo:
            self.notify("already at newest change")
            return
        cells, cur = self.nb_redo.pop()
        self.nb_undo.append((copy.deepcopy(self.nb.cells), self.cur))
        self.nb.cells, self.cur = cells, min(cur, len(cells) - 1)
        self.nb.dirty = True

    def search_cells(self, pattern: str, direction: int) -> None:
        if not pattern:
            return
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            self.notify("bad pattern: %s" % exc)
            return
        total = len(self.nb.cells)
        for step in range(1, total + 1):
            idx = (self.cur + direction * step) % total
            if rx.search(self.nb.cells[idx].source):
                self.cur = idx
                self.notify("/%s" % pattern)
                return
        self.notify("pattern not found: %s" % pattern)

    # --------------------------------------------------------------- running
    def ensure_kernel(self) -> bool:
        if self.kernel.alive:
            return True
        if self.kernel.state == "starting":
            self.notify("kernel is still starting ...")
            return False
        self.kernel.start_async()
        self.notify("starting kernel %s ..." % self.kernel.name)
        return False

    def run_cell(self, advance: bool, index: Optional[int] = None) -> None:
        self.sync_cell()
        index = self.cur if index is None else index
        cell = self.nb.cells[index]
        if cell.cell_type != "code":
            if advance:
                self.goto_cell(index + 1)
            return
        if not cell.source.strip():
            if advance:
                self.goto_cell(index + 1)
            return
        if not self.ensure_kernel():
            self.pending_msg = "run"
            return
        cell.outputs = []
        cell.running = True
        cell.execution_count = None
        msg_id = self.kernel.execute(cell.source)
        if msg_id:
            self.jobs[msg_id] = cell
        if advance:
            if index + 1 >= len(self.nb.cells):
                self.nb.cells.append(Cell())
                self.nb.dirty = True
            self.goto_cell(index + 1)

    def run_all(self) -> None:
        self.sync_cell()
        if not self.ensure_kernel():
            return
        for i in range(len(self.nb.cells)):
            self.run_cell(advance=False, index=i)
        self.notify("queued %d cells" % len(self.nb.cells))

    def poll_kernel(self) -> None:
        for channel, msg in self.kernel.drain():
            if channel == "kernel-ready":
                self.notify("kernel %s ready" % msg)
                if self.pending_msg == "run":
                    self.pending_msg = ""
                    self.run_cell(advance=False)
                continue
            if channel == "kernel-error":
                self.notify("kernel error: %s" % msg)
                continue
            parent = msg.get("parent_header", {}).get("msg_id")
            content = msg.get("content", {}) or {}
            mtype = msg.get("header", {}).get("msg_type", "")
            cell = self.jobs.get(parent)

            if mtype == "status":
                state = content.get("execution_state")
                if state in ("busy", "idle"):
                    self.kernel.state = state
                continue
            if mtype == "execute_input" and cell is not None:
                cell.execution_count = content.get("execution_count")
                continue
            if mtype == "clear_output" and cell is not None:
                cell.outputs = []
                continue
            if mtype in ("stream", "display_data", "execute_result", "error") and cell is not None:
                out = dict(content)
                out["output_type"] = mtype
                if mtype == "execute_result":
                    cell.execution_count = content.get("execution_count", cell.execution_count)
                if mtype == "stream" and cell.outputs:
                    last = cell.outputs[-1]
                    if last.get("output_type") == "stream" and last.get("name") == out.get("name"):
                        last["text"] = last.get("text", "") + out.get("text", "")
                        continue
                cell.outputs.append(out)
                self.nb.dirty = True
                continue
            if channel == "shell" and mtype == "execute_reply" and cell is not None:
                cell.running = False
                cell.execution_count = content.get("execution_count", cell.execution_count)
                self.jobs.pop(parent, None)

    # ----------------------------------------------------- kernel assistance
    def kernel_inspect(self) -> None:
        if not self.kernel.alive:
            self.notify("kernel not running")
            return
        buf = self.buf
        offset = sum(len(l) + 1 for l in buf.lines[: buf.row]) + buf.col
        doc = self.kernel.inspect(buf.text(), offset)
        if not doc:
            self.notify("no documentation found")
            return
        self.show_overlay("kernel docs", strip_ansi(doc))

    def kernel_complete(self) -> None:
        if not self.kernel.alive:
            self.notify("kernel not running")
            return
        buf = self.buf
        offset = sum(len(l) + 1 for l in buf.lines[: buf.row]) + buf.col
        result = self.kernel.complete(buf.text(), offset)
        if not result:
            self.notify("no completions")
            return
        matches, start, end = result
        if not matches:
            self.notify("no completions")
            return
        line_start = sum(len(l) + 1 for l in buf.lines[: buf.row])
        c1, c2 = start - line_start, end - line_start
        if c1 < 0 or c2 > len(buf.line()):
            self.notify("no completions")
            return
        best = matches[0] if len(matches) == 1 else os.path.commonprefix(matches)
        if not best:
            best = matches[0]
        line = buf.line()
        buf._snapshot()
        buf.lines[buf.row] = line[:c1] + best + line[c2:]
        buf.col = c1 + len(best)
        self.sync_cell()
        if len(matches) > 1:
            self.notify("  ".join(matches[:12]) + (" ..." if len(matches) > 12 else ""))

    # --------------------------------------------------------------- drawing
    def style(self, name: str) -> int:
        return self.styles.get(name, curses.A_NORMAL)

    def init_colors(self) -> None:
        self.styles = {}
        try:
            curses.start_color()
            curses.use_default_colors()
            has_color = curses.has_colors()
        except curses.error:
            has_color = False
        if not has_color:
            self.styles = {
                "code": curses.A_BOLD, "md": curses.A_BOLD, "raw": curses.A_BOLD,
                "sel": curses.A_BOLD, "nr": curses.A_DIM, "text": curses.A_NORMAL,
                "out": curses.A_NORMAL, "err": curses.A_BOLD, "stream": curses.A_NORMAL,
                "status": curses.A_REVERSE, "dim": curses.A_DIM, "mdtext": curses.A_NORMAL,
                "title": curses.A_REVERSE,
            }
            return
        pairs = {
            1: (curses.COLOR_CYAN, -1),
            2: (curses.COLOR_MAGENTA, -1),
            3: (curses.COLOR_YELLOW, -1),
            4: (curses.COLOR_GREEN, -1),
            5: (curses.COLOR_RED, -1),
            6: (curses.COLOR_BLUE, -1),
            7: (curses.COLOR_WHITE, curses.COLOR_BLUE),
        }
        for idx, (fg, bg) in pairs.items():
            try:
                curses.init_pair(idx, fg, bg)
            except curses.error:
                pass
        cp = curses.color_pair
        self.styles = {
            "code": cp(1) | curses.A_BOLD,
            "md": cp(2) | curses.A_BOLD,
            "raw": cp(3) | curses.A_BOLD,
            "sel": cp(3) | curses.A_BOLD,
            "nr": cp(6),
            "text": curses.A_NORMAL,
            "mdtext": cp(2),
            "out": curses.A_NORMAL,
            "stream": cp(4),
            "err": cp(5),
            "status": cp(7) | curses.A_BOLD,
            "dim": curses.A_DIM,
            "title": cp(7) | curses.A_BOLD,
        }

    def build_lines(self, width: int) -> List[DLine]:
        lines: List[DLine] = []
        for i, cell in enumerate(self.nb.cells):
            sel = i == self.cur
            gut = "\u2590" if sel else " "
            gstyle = "sel" if sel else "dim"
            if cell.cell_type == "code":
                if cell.running:
                    label = "In [*]"
                elif cell.execution_count:
                    label = "In [%d]" % cell.execution_count
                else:
                    label = "In [ ]"
                hstyle = "code"
            elif cell.cell_type == "markdown":
                label, hstyle = "Markdown", "md"
            else:
                label, hstyle = "Raw", "raw"
            head = " %s %d/%d " % (label, i + 1, len(self.nb.cells))
            bar = "\u2500" * max(0, width - len(head) - 2)
            lines.append(DLine(gut, head + bar, gstyle, hstyle, i, -1, True))

            src = cell.source.split("\n")
            nwidth = max(2, len(str(len(src)))) if self.show_numbers else 0
            body_style = "mdtext" if cell.cell_type == "markdown" else "text"
            for r, text in enumerate(src):
                if self.show_numbers:
                    prefix = "%s%*d \u2502 " % (gut, nwidth, r + 1)
                else:
                    prefix = "%s " % gut
                lines.append(DLine(prefix, text.replace("\t", " " * self.tabstop),
                                   gstyle if r else gstyle, body_style, i, r))

            outs = cell.output_text() if cell.cell_type == "code" else []
            if outs:
                if cell.collapsed:
                    lines.append(DLine("%s " % gut, "\u25b8 %d output line(s) hidden" % len(outs),
                                       gstyle, "dim", i, -1))
                else:
                    tag = "Out[%d]" % cell.execution_count if cell.execution_count else "Out"
                    lines.append(DLine("%s " % gut, "%s %s" % (
                        tag, "\u2500" * max(0, width - len(tag) - 4)), gstyle, "dim", i, -1))
                    for text, kind in outs[:2000]:
                        lines.append(DLine("%s " % gut, text, gstyle,
                                           {"err": "err", "stream": "stream"}.get(kind, "out"),
                                           i, -1))
            lines.append(DLine(" ", "", "dim", "dim", i, -1))
        return lines

    def ensure_visible(self, height: int, lines: List[DLine]) -> None:
        if self.mode == MODE_EDIT and self.buf is not None:
            target = next((n for n, dl in enumerate(lines)
                           if dl.cell == self.cur and dl.src_row == self.buf.row), None)
        else:
            target = next((n for n, dl in enumerate(lines)
                           if dl.cell == self.cur and dl.header), None)
        if target is None:
            return
        if self.mode == MODE_NB:
            last = max((n for n, dl in enumerate(lines) if dl.cell == self.cur), default=target)
            if last < self.top + height and self.top > target:
                self.top = target
        if target < self.top:
            self.top = target
        elif target >= self.top + height:
            self.top = target - height + 1
        self.top = max(0, min(self.top, max(0, len(lines) - 1)))

    def draw(self) -> None:
        scr = self.scr
        height, width = scr.getmaxyx()
        if height < 3 or width < 20:
            return
        scr.erase()
        body_h = height - 2

        if self.overlay is not None:
            self.draw_overlay(height, width)
        else:
            lines = self.build_lines(width)
            self._lines = lines
            self.ensure_visible(body_h, lines)
            self.update_hscroll(width)
            cursor = None
            for y in range(body_h):
                idx = self.top + y
                if idx >= len(lines):
                    break
                dl = lines[idx]
                try:
                    scr.addnstr(y, 0, dl.prefix, width, self.style(dl.pstyle))
                except curses.error:
                    pass
                plen = len(dl.prefix)
                if plen < width:
                    body = dl.body[self.left:] if dl.src_row >= 0 else dl.body
                    try:
                        scr.addnstr(y, plen, body, width - plen, self.style(dl.bstyle))
                    except curses.error:
                        pass
                if (self.mode == MODE_EDIT and self.buf is not None
                        and dl.cell == self.cur and dl.src_row == self.buf.row):
                    x = plen + self.buf.col - self.left
                    if 0 <= x < width:
                        cursor = (y, x)
            self._cursor_xy = cursor

        self.draw_status(height, width)
        self.draw_cmdline(height, width)

        if self.cmdline is not None:
            try:
                curses.curs_set(1)
                scr.move(height - 1, min(width - 1, len(self.cmdline["prefix"]) + len(self.cmdline["text"])))
            except curses.error:
                pass
        elif self.overlay is None and self._cursor_xy is not None:
            try:
                curses.curs_set(1)
                scr.move(*self._cursor_xy)
            except curses.error:
                pass
        else:
            try:
                curses.curs_set(0)
            except curses.error:
                pass
        scr.refresh()

    def update_hscroll(self, width: int) -> None:
        if self.mode != MODE_EDIT or self.buf is None:
            self.left = 0
            return
        avail = max(10, width - 10)
        if self.buf.col < self.left:
            self.left = max(0, self.buf.col - 4)
        elif self.buf.col >= self.left + avail:
            self.left = self.buf.col - avail + 4

    def draw_overlay(self, height: int, width: int) -> None:
        ov = self.overlay
        title = " %s  (j/k scroll, q close) " % ov["title"]
        try:
            self.scr.addnstr(0, 0, title.ljust(width), width, self.style("title"))
        except curses.error:
            pass
        for y in range(1, height - 2):
            idx = ov["scroll"] + y - 1
            if idx >= len(ov["lines"]):
                break
            try:
                self.scr.addnstr(y, 0, ov["lines"][idx], width)
            except curses.error:
                pass

    def draw_status(self, height: int, width: int) -> None:
        if self.mode == MODE_EDIT and self.buf is not None:
            mode = {"normal": "NORMAL", "insert": "INSERT", "visual": "VISUAL",
                    "vline": "V-LINE", "replace1": "REPLACE"}.get(self.buf.mode, "NORMAL")
            pos = "%d:%d" % (self.buf.row + 1, self.buf.col + 1)
            pending = self.buf.pending
        else:
            mode = "NOTEBOOK"
            pos = "cell %d/%d" % (self.cur + 1, len(self.nb.cells))
            pending = self.nb_count + self.nb_pending
        kstate = {"idle": "idle", "busy": "busy", "starting": "starting",
                  "dead": "dead", "stopped": "off"}.get(self.kernel.state, self.kernel.state)
        name = self.nb.path or "[No Name]"
        flag = " [+]" if self.nb.dirty else ""
        left = " %s  %s%s  %s " % (mode, os.path.basename(name), flag, self.cell.cell_type)
        right = " %s:%s  %s %s " % (self.kernel.name, kstate, pending, pos)
        text = left + " " * max(0, width - len(left) - len(right)) + right
        try:
            self.scr.addnstr(height - 2, 0, text[:width].ljust(width), width, self.style("status"))
        except curses.error:
            pass

    def draw_cmdline(self, height: int, width: int) -> None:
        if self.cmdline is not None:
            text = self.cmdline["prefix"] + self.cmdline["text"]
        else:
            text = self.message
        try:
            self.scr.addnstr(height - 1, 0, text[:width].ljust(width), width)
        except curses.error:
            pass


def _main(stdscr, path, kernel_name):
    curses.cbreak()
    stdscr.keypad(True)
    if hasattr(curses, "set_escdelay"):
        curses.set_escdelay(25)
    app = App(stdscr, path, kernel_name)
    app.init_colors()
    app.kernel.start_async()
    try:
        app.run()
    finally:
        app.kernel.shutdown()
    return app


def _prepare_terminfo() -> None:
    """A frozen ncurses only searches its build host's terminfo path."""
    if not getattr(sys, "frozen", False):
        return
    dirs = [d for d in ("/usr/share/terminfo", "/lib/terminfo", "/etc/terminfo",
                        "/usr/lib/terminfo", "/usr/share/lib/terminfo") if os.path.isdir(d)]
    bundled = os.path.join(getattr(sys, "_MEIPASS", ""), "terminfo")
    if os.path.isdir(bundled):
        dirs.append(bundled)
    current = os.environ.get("TERMINFO_DIRS")
    if current:
        dirs = current.split(":") + dirs
    if dirs:
        os.environ["TERMINFO_DIRS"] = ":".join(dict.fromkeys(dirs))


def start(path: Optional[str], kernel_name: Optional[str]) -> None:
    _prepare_terminfo()
    try:
        curses.wrapper(_main, path, kernel_name)
    except curses.error as exc:
        raise SystemExit("terminal error: %s (TERM=%s)" % (exc, os.environ.get("TERM", "")))
