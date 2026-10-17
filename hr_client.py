"""One stdlib SSE consumer for both Tk frontends; Tk reads a locked mailbox."""
import json
import threading
import time
from urllib.request import Request, urlopen

class SnapshotClient:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._response = None
        self._snapshot = {"bpm": None, "connected": False}
        self._received = 0
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._close_thread = None
        self._thread.start()

    def latest(self):
        with self._lock:
            snap = dict(self._snapshot)
            elapsed = time.monotonic() - self._received
        if snap.get("age") is not None:
            snap["age"] += elapsed
        if elapsed > 5:
            snap.update(bpm=None, connected=False)
        return snap

    def close(self):
        if self._stop.is_set():
            return
        self._stop.set()
        response = self._response
        if response:
            # Buffered HTTP close may wait for a reader. Never block Tk's UI thread.
            self._close_thread = threading.Thread(target=response.close, daemon=True)
            self._close_thread.start()

    def wait_closed(self, timeout=1):
        """Only call after the UI loop exits, or from a non-UI worker."""
        self._thread.join(timeout)
        if self._close_thread:
            self._close_thread.join(timeout)

    def _run(self):
        while not self._stop.is_set():
            try:
                req = Request(self.base + "/events", headers={"Accept": "text/event-stream"})
                with urlopen(req, timeout=8) as response:
                    self._response = response
                    data = []
                    for raw in response:
                        if self._stop.is_set():
                            return
                        line = raw.decode("utf-8").rstrip("\r\n")
                        if line.startswith("data:"):
                            data.append(line[5:].lstrip())
                        elif not line and data:
                            snap = json.loads("\n".join(data))
                            data.clear()
                            if isinstance(snap, dict):
                                with self._lock:
                                    self._snapshot = snap
                                    self._received = time.monotonic()
            except (OSError, ValueError, AttributeError):
                # HTTPResponse.fp can become None when close races with its iterator.
                pass
            finally:
                self._response = None
            self._stop.wait(1)
