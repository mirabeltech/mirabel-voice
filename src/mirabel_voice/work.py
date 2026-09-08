"""Cancelable wall-clock deadlines without accumulating abandoned workers."""
import queue
import threading
import time


class WorkCancelled(Exception):
    pass


class BoundedWork:
    def __init__(self):
        self._thread = None
        self._lock = threading.Lock()

    def call(self, operation, timeout, cancel):
        result = queue.Queue(maxsize=1)
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise TimeoutError('The previous network request is still disconnecting. Try again shortly.')
            def run():
                try:
                    result.put((True, operation()))
                except Exception as error:
                    result.put((False, error))
            self._thread = threading.Thread(target=run, daemon=True, name='mirabel-network')
            self._thread.start()
        end = time.monotonic() + timeout
        while True:
            if cancel.is_set():
                raise WorkCancelled()
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('The request took too long. Retry when your connection is ready.')
            try:
                ok, value = result.get(timeout=min(0.05, remaining))
            except queue.Empty:
                continue
            if cancel.is_set():
                raise WorkCancelled()
            if ok:
                return value
            raise value
