"""Run a cell against a real Jupyter kernel through the TUI (Linux only).

Needs jupyter_client + ipykernel in the running interpreter.
"""

from __future__ import annotations

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
OUT = "/tmp/jnvim_exec.ipynb"
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][B0]|\x1b[=><]|\x1b\]\d+;[^\x07]*\x07")


def main() -> int:
    if os.path.exists(OUT):
        os.remove(OUT)
    master, slave = os.openpty()
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 110, 0, 0))
    tty.setraw(master)
    env = dict(os.environ, TERM="xterm-256color", PYTHONPATH=ROOT, LINES="40", COLUMNS="110")
    proc = subprocess.Popen(
        [sys.executable, "-m", "jnvim", OUT],
        stdin=slave, stdout=slave, stderr=slave, env=env, cwd=ROOT, start_new_session=True,
    )
    os.close(slave)
    captured = bytearray()

    def pump(seconds: float) -> None:
        end = time.time() + seconds
        os.set_blocking(master, False)
        while time.time() < end:
            try:
                chunk = os.read(master, 65536)
            except BlockingIOError:
                time.sleep(0.02)
                continue
            except OSError:
                return
            if chunk:
                captured.extend(chunk)

    def send(text: str, wait: float = 0.4) -> None:
        os.write(master, text.encode())
        pump(wait)

    pump(8.0)  # kernel startup
    send("i")
    send('print("hi from kernel")\ry = 6 * 7\x1b\x1b', 0.6)
    send(" ", 4.0)          # run cell, move to the next one
    send("iy\x1b\x1b", 0.5)  # second cell: evaluate y
    send(" ", 4.0)
    send(":w\r", 0.8)
    screen = ANSI.sub("", captured.decode("utf-8", "replace"))
    send(":q!\r", 0.8)
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        print("FAIL: editor did not exit")
        return 1
    os.close(master)

    problems = []
    if "hi from kernel" not in screen:
        problems.append("stdout not shown on screen")
    if "Out[1]" not in screen:
        problems.append("execution count not shown")
    if "IPKernelApp" in screen or "Kernel is running over TCP" in screen:
        problems.append("kernel stdio leaked onto the screen")
    if os.path.exists(OUT):
        nb = json.load(open(OUT, encoding="utf-8"))
        texts = json.dumps(nb["cells"])
        if "hi from kernel" not in texts:
            problems.append("stdout not persisted in the notebook")
        if '"42"' not in texts and "42" not in texts:
            problems.append("execute_result not captured")
    else:
        problems.append("notebook not written")

    if problems:
        print("FAILED:")
        for p in problems:
            print("  -", p)
        print("\n--- last 2500 chars of screen ---\n" + screen[-2500:])
        return 1
    print("kernel execution test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
