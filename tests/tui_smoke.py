"""End-to-end smoke test: drive the curses UI through a pty (Linux only)."""

import fcntl
import json
import os
import re
import struct
import subprocess
import sys
import termios
import time
import tty

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = "/tmp/jnvim_smoke.ipynb"
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][B0]|\x1b[=><]|\x1b\]\d+;[^\x07]*\x07")
CMD = os.environ.get("JNVIM_CMD", "").split() or [sys.executable, "-m", "jnvim"]


def main() -> int:
    if os.path.exists(OUT):
        os.remove(OUT)
    master, slave = os.openpty()
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 110, 0, 0))
    tty.setraw(master)
    env = dict(os.environ, TERM="xterm-256color", PYTHONPATH=ROOT, LINES="40", COLUMNS="110")
    proc = subprocess.Popen(
        CMD + [OUT],
        stdin=slave, stdout=slave, stderr=slave, env=env,
        cwd=ROOT, start_new_session=True,
    )
    os.close(slave)
    captured = bytearray()

    def pump(seconds: float = 0.35) -> None:
        end = time.time() + seconds
        while time.time() < end:
            os.set_blocking(master, False)
            try:
                chunk = os.read(master, 65536)
            except BlockingIOError:
                time.sleep(0.02)
                continue
            except OSError:
                return
            if chunk:
                captured.extend(chunk)
            else:
                time.sleep(0.02)

    def send(text: str, wait: float = 0.35) -> None:
        os.write(master, text.encode())
        pump(wait)

    pump(2.0)  # let the kernel start / fail
    send("i")
    send('print("hello")\x1b\x1b')
    send("o")
    send("x = 1\x1b\x1b")
    send("o")
    send("# heading\x1b\x1b")
    send("m")                     # make the last cell markdown
    send("gg")                    # back to the first cell
    send("yyp")                   # duplicate it
    send("G")
    send(":w\r", 0.6)
    screen = ANSI.sub("", captured.decode("utf-8", "replace"))
    send(":q!\r", 0.6)

    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        print("FAIL: editor did not exit")
        return 1
    os.close(master)

    problems = []
    if proc.returncode != 0:
        problems.append("exit code %s" % proc.returncode)
    if "Traceback (most recent call last)" in screen:
        problems.append("python traceback on screen")
    for needle in ("NOTEBOOK", "In [ ]", "Markdown", "jnvim_smoke.ipynb"):
        if needle not in screen:
            problems.append("missing %r on screen" % needle)

    if not os.path.exists(OUT):
        problems.append("notebook was not written")
    else:
        nb = json.load(open(OUT, encoding="utf-8"))
        sources = ["".join(c["source"]) for c in nb["cells"]]
        types = [c["cell_type"] for c in nb["cells"]]
        if sources.count('print("hello")') != 2:
            problems.append("expected the duplicated cell, got %r" % (sources,))
        if "x = 1" not in sources:
            problems.append("second cell missing: %r" % (sources,))
        if "markdown" not in types:
            problems.append("markdown cell missing: %r" % (types,))

    if problems:
        print("FAILED:")
        for p in problems:
            print("  -", p)
        print("\n--- last 2000 chars of screen ---\n" + screen[-2000:])
        return 1
    print("tui smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
