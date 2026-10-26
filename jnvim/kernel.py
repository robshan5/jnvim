"""Thin, non-blocking wrapper around a Jupyter kernel.

All ZMQ traffic is pumped by background threads into a queue; the curses main
loop drains that queue, so the UI never blocks on the kernel.
"""

from __future__ import annotations

import queue
import subprocess
import threading
from typing import Any, Dict, List, Optional, Tuple


class Kernel:
    def __init__(self, name: str = "python3"):
        self.name = name
        self.km = None
        self.kc = None
        self.events: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
        self.state = "stopped"  # stopped | starting | idle | busy | dead
        self.error: Optional[str] = None
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------- lifecycle
    @property
    def alive(self) -> bool:
        return self.kc is not None and self.state not in ("stopped", "dead")

    def start_async(self) -> None:
        if self.state in ("starting",) or self.alive:
            return
        self.state = "starting"
        threading.Thread(target=self._start, daemon=True).start()

    def _start(self) -> None:
        try:
            from jupyter_client.manager import KernelManager

            km = KernelManager(kernel_name=self.name)
            # the kernel inherits our tty otherwise and scribbles over the UI
            km.start_kernel(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            kc = km.client()
            kc.start_channels()
            kc.wait_for_ready(timeout=60)
        except Exception as exc:  # noqa: BLE001 - surfaced in the status line
            self.state = "dead"
            self.error = "%s: %s" % (type(exc).__name__, exc)
            self.events.put(("kernel-error", self.error))
            return
        with self._lock:
            self.km, self.kc = km, kc
            self.state = "idle"
            self.error = None
        self._stop.clear()
        for channel in ("iopub", "shell"):
            thread = threading.Thread(target=self._pump, args=(channel,), daemon=True)
            thread.start()
            self._threads.append(thread)
        self.events.put(("kernel-ready", self.name))

    def _pump(self, channel: str) -> None:
        get = self.kc.get_iopub_msg if channel == "iopub" else self.kc.get_shell_msg
        while not self._stop.is_set():
            try:
                msg = get(timeout=0.2)
            except queue.Empty:
                continue
            except Exception:  # channel closed / kernel died
                if not self._stop.is_set():
                    self.events.put(("kernel-error", "kernel channel closed"))
                return
            self.events.put((channel, msg))

    def shutdown(self) -> None:
        self._stop.set()
        kc, km = self.kc, self.km
        self.kc = self.km = None
        self.state = "stopped"
        try:
            if kc is not None:
                kc.stop_channels()
            if km is not None:
                km.shutdown_kernel(now=True)
        except Exception:
            pass

    def restart(self) -> None:
        if self.km is None:
            self.start_async()
            return

        def _do() -> None:
            try:
                self.km.restart_kernel(now=True)
                self.kc.wait_for_ready(timeout=60)
                self.state = "idle"
                self.events.put(("kernel-ready", self.name))
            except Exception as exc:  # noqa: BLE001
                self.state = "dead"
                self.events.put(("kernel-error", str(exc)))

        self.state = "starting"
        threading.Thread(target=_do, daemon=True).start()

    def interrupt(self) -> None:
        if self.km is not None:
            try:
                self.km.interrupt_kernel()
            except Exception:
                pass

    # -------------------------------------------------------------- requests
    def execute(self, code: str) -> Optional[str]:
        if not self.alive:
            return None
        return self.kc.execute(code, store_history=True, allow_stdin=False)

    def complete(self, code: str, cursor_pos: int, timeout: float = 2.0):
        """Blocking completion request (short timeout, called from the UI)."""
        if not self.alive:
            return []
        try:
            msg_id = self.kc.complete(code, cursor_pos)
        except Exception:
            return []
        deadline = timeout
        while deadline > 0:
            try:
                reply = self.kc.get_shell_msg(timeout=0.2)
            except queue.Empty:
                deadline -= 0.2
                continue
            except Exception:
                return []
            if reply.get("parent_header", {}).get("msg_id") == msg_id:
                content = reply.get("content", {})
                return (
                    content.get("matches", []),
                    content.get("cursor_start", cursor_pos),
                    content.get("cursor_end", cursor_pos),
                )
            self.events.put(("shell", reply))
            deadline -= 0.05
        return []

    def inspect(self, code: str, cursor_pos: int, timeout: float = 2.0) -> str:
        if not self.alive:
            return ""
        try:
            msg_id = self.kc.inspect(code, cursor_pos, detail_level=0)
        except Exception:
            return ""
        deadline = timeout
        while deadline > 0:
            try:
                reply = self.kc.get_shell_msg(timeout=0.2)
            except queue.Empty:
                deadline -= 0.2
                continue
            except Exception:
                return ""
            if reply.get("parent_header", {}).get("msg_id") == msg_id:
                content = reply.get("content", {})
                if not content.get("found"):
                    return ""
                return (content.get("data", {}) or {}).get("text/plain", "")
            self.events.put(("shell", reply))
            deadline -= 0.05
        return ""

    def drain(self, limit: int = 200) -> List[Tuple[str, Any]]:
        msgs = []
        for _ in range(limit):
            try:
                msgs.append(self.events.get_nowait())
            except queue.Empty:
                break
        return msgs


def list_kernels() -> Dict[str, str]:
    try:
        from jupyter_client.kernelspec import KernelSpecManager

        specs = KernelSpecManager().get_all_specs()
        return {name: spec["spec"].get("display_name", name) for name, spec in specs.items()}
    except Exception:
        return {}
