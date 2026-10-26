"""Non-blocking Jupyter kernel client.

ZMQ traffic is pumped by background threads into a queue; the bridge drains it
and forwards translated events to Neovim.
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
        self.jobs: Dict[str, Any] = {}  # msg_id -> token
        self._stop = threading.Event()
        self._lock = threading.Lock()

    @property
    def alive(self) -> bool:
        return self.kc is not None and self.state not in ("stopped", "dead")

    # ------------------------------------------------------------- lifecycle
    def start_async(self) -> None:
        if self.state == "starting" or self.alive:
            return
        self.state = "starting"
        threading.Thread(target=self._start, daemon=True).start()

    def _start(self) -> None:
        try:
            from jupyter_client.manager import KernelManager

            km = KernelManager(kernel_name=self.name)
            # our stdout is the RPC channel; the kernel must never touch it
            km.start_kernel(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            kc = km.client()
            kc.start_channels()
            kc.wait_for_ready(timeout=60)
        except Exception as exc:  # noqa: BLE001 - reported to the editor
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
            threading.Thread(target=self._pump, args=(channel,), daemon=True).start()
        self.events.put(("kernel-ready", self.name))

    def _pump(self, channel: str) -> None:
        kc = self.kc
        if kc is None:
            return
        get = kc.get_iopub_msg if channel == "iopub" else kc.get_shell_msg
        while not self._stop.is_set():
            try:
                msg = get(timeout=0.2)
            except queue.Empty:
                continue
            except Exception:
                if not self._stop.is_set():
                    self.state = "dead"
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

        def run() -> None:
            try:
                self.km.restart_kernel(now=True)
                self.kc.wait_for_ready(timeout=60)
                self.state = "idle"
                self.jobs.clear()
                self.events.put(("kernel-ready", self.name))
            except Exception as exc:  # noqa: BLE001
                self.state = "dead"
                self.events.put(("kernel-error", str(exc)))

        self.state = "starting"
        threading.Thread(target=run, daemon=True).start()

    def interrupt(self) -> None:
        if self.km is not None:
            try:
                self.km.interrupt_kernel()
            except Exception:
                pass

    # -------------------------------------------------------------- requests
    def execute(self, code: str, token: Any) -> Optional[str]:
        if not self.alive:
            return None
        msg_id = self.kc.execute(code, store_history=True, allow_stdin=False)
        self.jobs[msg_id] = token
        return msg_id

    def _request(self, send, timeout: float):
        try:
            msg_id = send()
        except Exception:
            return None
        remaining = timeout
        while remaining > 0:
            try:
                reply = self.kc.get_shell_msg(timeout=0.2)
            except queue.Empty:
                remaining -= 0.2
                continue
            except Exception:
                return None
            if reply.get("parent_header", {}).get("msg_id") == msg_id:
                return reply.get("content", {})
            self.events.put(("shell", reply))
            remaining -= 0.05
        return None

    def complete(self, code: str, cursor_pos: int, timeout: float = 3.0) -> Dict[str, Any]:
        if not self.alive:
            return {}
        return self._request(lambda: self.kc.complete(code, cursor_pos), timeout) or {}

    def inspect(self, code: str, cursor_pos: int, timeout: float = 3.0) -> str:
        if not self.alive:
            return ""
        content = self._request(
            lambda: self.kc.inspect(code, cursor_pos, detail_level=0), timeout) or {}
        if not content.get("found"):
            return ""
        return (content.get("data", {}) or {}).get("text/plain", "")


def list_kernels() -> List[Dict[str, str]]:
    try:
        from jupyter_client.kernelspec import KernelSpecManager

        specs = KernelSpecManager().get_all_specs()
    except Exception:
        return []
    out = []
    for name, spec in sorted(specs.items()):
        info = spec.get("spec", {})
        out.append({
            "name": name,
            "display_name": info.get("display_name", name),
            "language": info.get("language", ""),
        })
    return out
