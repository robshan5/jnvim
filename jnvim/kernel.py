"""Thin, non-blocking wrapper around a Jupyter kernel.

All ZMQ traffic is pumped by background threads into a queue; the curses main
loop drains that queue, so the UI never blocks on the kernel.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import Any, Dict, List, Optional, Tuple

BUNDLED_NAME = "jnvim-python"


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def child_env() -> Dict[str, str]:
    """Environment for kernel subprocesses.

    A PyInstaller bootloader prepends its extraction dir to LD_LIBRARY_PATH and
    exports its own _PYI/_MEIPASS2 handles; children must not inherit either.
    """
    env = dict(os.environ)
    if frozen():
        orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if orig:
            env["LD_LIBRARY_PATH"] = orig
        else:
            env.pop("LD_LIBRARY_PATH", None)
        for key in [k for k in env if k.startswith("_PYI") or k == "_MEIPASS2"]:
            env.pop(key, None)
    return env


def install_bundled_kernelspec() -> Optional[str]:
    """Expose this executable as a kernel so a frozen build needs no system python."""
    try:
        import ipykernel  # noqa: F401
    except ImportError:
        return None
    if frozen():
        argv = [sys.executable, "--kernel-launcher", "-f", "{connection_file}"]
    else:
        argv = [sys.executable, "-m", "jnvim", "--kernel-launcher", "-f", "{connection_file}"]
    root = os.path.join(tempfile.gettempdir(), "jnvim-kernelspec-%d" % os.getuid())
    folder = os.path.join(root, "kernels", BUNDLED_NAME)
    try:
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "kernel.json"), "w", encoding="utf-8") as fh:
            json.dump({
                "argv": argv,
                "display_name": "Python (jnvim bundled)",
                "language": "python",
            }, fh)
    except OSError:
        return None
    existing = os.environ.get("JUPYTER_PATH", "")
    if root not in existing.split(os.pathsep):
        os.environ["JUPYTER_PATH"] = os.pathsep.join([root, existing]) if existing else root
    return BUNDLED_NAME


def resolve_kernel(name: str) -> str:
    """Fall back to the bundled kernel when the requested one cannot be launched."""
    if spec_runnable(name):
        return name
    return install_bundled_kernelspec() or name


def spec_runnable(name: str) -> bool:
    """A frozen build carries kernelspecs that point at the build machine's python."""
    try:
        from jupyter_client.kernelspec import KernelSpecManager

        spec = KernelSpecManager().get_kernel_spec(name)
    except Exception:
        return False
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle and (spec.resource_dir or "").startswith(bundle) and name != BUNDLED_NAME:
        return False
    argv = spec.argv or []
    if not argv:
        return False
    exe = argv[0]
    if os.path.dirname(exe):
        return os.path.exists(exe)
    return shutil.which(exe) is not None


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
            km, kc = self._launch(resolve_kernel(self.name))
        except Exception as exc:  # noqa: BLE001 - surfaced in the status line
            fallback = install_bundled_kernelspec()
            if fallback is None or fallback == self.name:
                self.state = "dead"
                self.error = "%s: %s" % (type(exc).__name__, exc)
                self.events.put(("kernel-error", self.error))
                return
            try:
                km, kc = self._launch(fallback)
            except Exception as exc2:  # noqa: BLE001
                self.state = "dead"
                self.error = "%s: %s" % (type(exc2).__name__, exc2)
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

    def _launch(self, name: str):
        from jupyter_client.manager import KernelManager

        self.name = name
        km = KernelManager(kernel_name=name)
        # the kernel inherits our tty otherwise and scribbles over the UI
        km.start_kernel(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=child_env())
        kc = km.client()
        kc.start_channels()
        kc.wait_for_ready(timeout=60)
        return km, kc

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
