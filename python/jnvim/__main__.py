"""Stdio JSON bridge used by the Lua side of jnvim.nvim.

Protocol (one JSON object per line):

    ->  {"id": 7, "method": "kernel.execute", "params": {...}}
    <-  {"id": 7, "ok": true, "result": {...}}
    <-  {"event": "output", "session": "3", "token": 12, ...}

Nothing but protocol frames may reach stdout, so ``sys.stdout`` is rebound to
stderr for the rest of the process.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import traceback
from typing import Any, Dict, Optional

from . import notebook, percent
from .kernel import Kernel, list_kernels

_PROTOCOL = sys.stdout
sys.stdout = sys.stderr

# methods that wait on the kernel and must not stall the request loop
BLOCKING = ("kernel.complete", "kernel.inspect")


class Session:
    def __init__(self, sid: str, name: str, emit, image_dir: Optional[str] = None) -> None:
        self.sid = sid
        self.emit = emit
        self.image_dir = image_dir
        self.kernel = Kernel(name)
        self.pending = []
        self.lock = threading.Lock()
        self.kernel.start_async()
        threading.Thread(target=self._pump, daemon=True).start()

    def execute(self, code: str, token: Any) -> bool:
        """Requests that arrive while the kernel boots are run once it is ready."""
        with self.lock:
            if not self.kernel.alive:
                if self.kernel.state == "dead":
                    return False
                self.pending.append((code, token))
                return True
        return self.kernel.execute(code, token) is not None

    def _flush(self) -> None:
        with self.lock:
            queued, self.pending = self.pending, []
        for code, token in queued:
            self.kernel.execute(code, token)

    def _fail_pending(self, message: str) -> None:
        with self.lock:
            queued, self.pending = self.pending, []
        for _, token in queued:
            self.emit("output", {
                "token": token,
                "output": {"output_type": "error", "ename": "KernelError",
                           "evalue": message, "traceback": []},
                "lines": [[message, "err"]],
            })
            self.emit("done", {"token": token, "count": None, "status": "error"})

    def _pump(self) -> None:
        kernel = self.kernel
        while True:
            channel, msg = kernel.events.get()
            try:
                self._translate(channel, msg)
            except Exception:
                self.emit("error", {"message": traceback.format_exc(limit=3)})

    def _translate(self, channel: str, msg: Any) -> None:
        if channel == "kernel-ready":
            self.emit("kernel", {"state": "ready", "name": msg})
            self._flush()
            return
        if channel == "kernel-error":
            self.emit("kernel", {"state": "dead", "message": msg})
            self._fail_pending(str(msg))
            return

        header = msg.get("header", {})
        content = msg.get("content", {}) or {}
        mtype = header.get("msg_type", "")
        parent = msg.get("parent_header", {}).get("msg_id")
        token = self.kernel.jobs.get(parent)

        if mtype == "status":
            state = content.get("execution_state")
            if state in ("busy", "idle"):
                self.kernel.state = state
                self.emit("status", {"state": state})
            return
        if token is None:
            return
        if mtype == "execute_input":
            self.emit("input", {"token": token, "count": content.get("execution_count")})
            return
        if mtype == "clear_output":
            self.emit("clear", {"token": token})
            return
        if mtype in ("stream", "display_data", "execute_result", "error"):
            out = dict(content)
            out["output_type"] = mtype
            self.emit("output", {
                "token": token,
                "output": out,
                "lines": notebook.output_lines([out], self.image_dir),
            })
            return
        if channel == "shell" and mtype == "execute_reply":
            self.kernel.jobs.pop(parent, None)
            self.emit("done", {
                "token": token,
                "count": content.get("execution_count"),
                "status": content.get("status", "ok"),
            })


class Bridge:
    def __init__(self) -> None:
        self.sessions: Dict[str, Session] = {}
        self.lock = threading.Lock()
        self.sessions_lock = threading.Lock()
        self.image_dir = tempfile.mkdtemp(prefix="jnvim-images-")

    # ----------------------------------------------------------------- io
    def send(self, payload: Dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False, default=str)
        with self.lock:
            _PROTOCOL.write(line + "\n")
            _PROTOCOL.flush()

    def emitter(self, sid: str):
        def emit(event: str, params: Dict[str, Any]) -> None:
            payload = {"event": event, "session": sid}
            payload.update(params)
            self.send(payload)
        return emit

    def serve(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except ValueError:
                continue
            # only the methods that block get a thread: everything else must
            # keep the order it was sent in, or cells would run out of order
            if request.get("method") in BLOCKING:
                threading.Thread(target=self._handle, args=(request,), daemon=True).start()
            else:
                self._handle(request)

    def _handle(self, request: Dict[str, Any]) -> None:
        rid = request.get("id")
        method = request.get("method", "")
        params = request.get("params") or {}
        handler = getattr(self, "do_" + method.replace(".", "_"), None)
        if handler is None:
            self.send({"id": rid, "ok": False, "error": "unknown method: %s" % method})
            return
        try:
            result = handler(params)
        except Exception as exc:  # noqa: BLE001 - reported to the editor
            self.send({"id": rid, "ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
            return
        if rid is not None:
            self.send({"id": rid, "ok": True, "result": result})

    # ------------------------------------------------------------ sessions
    def session(self, params: Dict[str, Any], create: bool = True) -> Optional[Session]:
        sid = str(params.get("session", "default"))
        # requests are handled on their own threads: only one kernel per session
        with self.sessions_lock:
            session = self.sessions.get(sid)
            if session is None and create:
                session = Session(sid, params.get("kernel") or "python3", self.emitter(sid),
                                  self.image_dir)
                self.sessions[sid] = session
        return session

    # ------------------------------------------------------------- methods
    def do_ping(self, params):
        return {"version": sys.version.split()[0], "pid": __import__("os").getpid(),
                "image_dir": self.image_dir}

    def do_notebook_read(self, params):
        doc = notebook.read(params["path"])
        language = notebook.language(doc["metadata"])
        cells = doc["cells"]
        return {
            "text": percent.to_text(cells, language),
            "language": language,
            "kernel": notebook.kernel_name(doc["metadata"]),
            "metadata": doc["metadata"],
            "nbformat": doc["nbformat"],
            "nbformat_minor": doc["nbformat_minor"],
            "cells": [{
                "cell_type": cell["cell_type"],
                "execution_count": cell["execution_count"],
                "outputs": cell["outputs"],
                "lines": notebook.output_lines(cell["outputs"], self.image_dir),
                "id": cell["id"],
            } for cell in cells],
        }

    def do_notebook_write(self, params):
        language = params.get("language") or "python"
        parsed = percent.from_text(params.get("text", ""), language)
        extras = params.get("cells") or []
        cells = []
        for index, cell in enumerate(parsed):
            extra = extras[index] if index < len(extras) else {}
            cell = dict(cell)
            if cell["cell_type"] == "code":
                cell["outputs"] = _merge_streams(extra.get("outputs") or [])
                cell["execution_count"] = extra.get("execution_count")
            cell["id"] = extra.get("id") or notebook.new_id()
            cells.append(cell)
        metadata = params.get("metadata") or {}
        if params.get("kernel"):
            spec = metadata.setdefault("kernelspec", {})
            spec.setdefault("name", params["kernel"])
            spec.setdefault("display_name", params["kernel"])
            spec.setdefault("language", language)
        notebook.write(params["path"], {
            "cells": cells,
            "metadata": metadata,
            "nbformat": params.get("nbformat", 4),
            "nbformat_minor": params.get("nbformat_minor", 5),
        })
        return {"path": params["path"], "cells": len(cells)}

    def do_notebook_to_text(self, params):
        return {"text": percent.to_text(params.get("cells") or [], params.get("language", "python"))}

    def do_kernel_list(self, params):
        return {"kernels": list_kernels()}

    def do_kernel_start(self, params):
        session = self.session(params)
        return {"state": session.kernel.state, "name": session.kernel.name}

    def do_kernel_status(self, params):
        session = self.session(params, create=False)
        if session is None:
            return {"state": "stopped"}
        return {"state": session.kernel.state, "name": session.kernel.name,
                "error": session.kernel.error}

    def do_kernel_execute(self, params):
        session = self.session(params)
        queued = session.execute(params.get("code", ""), params.get("token"))
        return {"queued": queued, "state": session.kernel.state}

    def do_kernel_interrupt(self, params):
        session = self.session(params, create=False)
        if session:
            session.kernel.interrupt()
        return {"ok": True}

    def do_kernel_restart(self, params):
        session = self.session(params, create=False)
        if session:
            session.kernel.restart()
        return {"ok": True}

    def do_kernel_stop(self, params):
        sid = str(params.get("session", "default"))
        with self.sessions_lock:
            session = self.sessions.pop(sid, None)
        if session:
            session.kernel.shutdown()
        return {"ok": True}

    def do_kernel_complete(self, params):
        session = self.session(params, create=False)
        if session is None:
            return {"matches": []}
        content = session.kernel.complete(params.get("code", ""), int(params.get("pos", 0)))
        return {
            "matches": content.get("matches", []),
            "start": content.get("cursor_start", 0),
            "end": content.get("cursor_end", 0),
        }

    def do_kernel_inspect(self, params):
        session = self.session(params, create=False)
        if session is None:
            return {"text": ""}
        text = session.kernel.inspect(params.get("code", ""), int(params.get("pos", 0)))
        return {"text": notebook.strip_ansi(text)}

    def do_shutdown(self, params):
        for session in list(self.sessions.values()):
            session.kernel.shutdown()
        self.sessions.clear()
        shutil.rmtree(self.image_dir, ignore_errors=True)
        return {"ok": True}


def _merge_streams(outputs):
    """Consecutive stdout chunks are stored as one output in the file."""
    merged = []
    for out in outputs:
        if (merged and out.get("output_type") == "stream"
                and merged[-1].get("output_type") == "stream"
                and merged[-1].get("name") == out.get("name")):
            merged[-1] = dict(merged[-1])
            merged[-1]["text"] = merged[-1].get("text", "") + out.get("text", "")
        else:
            merged.append(out)
    return merged


def main() -> int:
    bridge = Bridge()
    try:
        bridge.serve()
    except KeyboardInterrupt:
        pass
    finally:
        bridge.do_shutdown({})
    return 0


if __name__ == "__main__":
    sys.exit(main())
