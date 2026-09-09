"""Bounded process shutdown after an explicit quit or approved update."""
from __future__ import annotations

import faulthandler
import logging
import os
import threading
from pathlib import Path

log = logging.getLogger(__name__)
# Leave room for the replacement process's 20-second instance-mutex wait.
SHUTDOWN_TIMEOUT = 12.0


class ShutdownDeadline:
    def __init__(self, folder: Path, *, timeout=SHUTDOWN_TIMEOUT, exit_process=os._exit):
        self.folder = folder
        self.timeout = timeout
        self.exit_process = exit_process
        self._lock = threading.Lock()
        self._started = False
        self._finished = threading.Event()

    def arm(self):
        """Called before any cleanup that could block. Repeated Quit is safe."""
        with self._lock:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._watch, name="mirabel-shutdown-deadline", daemon=True).start()
        log.info("Shutdown requested; waiting for cleanup.")

    def finish(self):
        self._finished.set()

    def _watch(self):
        if self._finished.wait(self.timeout):
            return
        # Do not depend on the logging handler's lock on the fallback path.
        # Stack frames (no locals, recordings or credentials) help diagnose
        # the cleanup that stalled. Failure to write must not block exit.
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            with (self.folder / "shutdown-timeout.log").open("w", encoding="utf-8") as output:
                output.write("Shutdown cleanup exceeded its deadline; ending this process.\n")
                output.flush()
                faulthandler.dump_traceback(file=output, all_threads=True)
        finally:
            # Only our own process: Windows releases its microphone handles
            # and instance mutex, allowing the waiting update to start.
            self.exit_process(0)
