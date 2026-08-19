"""Live transcription over the OpenAI realtime socket.

The socket sends audio while the user speaks and returns words as they
arrive, so the app can show them immediately and has almost no work left
when the user releases the hotkey.

The API is asynchronous, but the rest of the app is not. This module runs
one asyncio loop on its own thread and gives the app four plain methods:
start, send, finish, and cancel.

Every failure path returns None from finish(). The caller must then fall
back to the upload path. A dictation is never lost because a socket broke.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import threading
from typing import Callable

log = logging.getLogger(__name__)

MODEL = "gpt-live-transcribe"
SAMPLE_RATE = 24000  # The realtime API accepts no other rate.
CONNECT_TIMEOUT = 5.0
FINISH_TIMEOUT = 10.0

_STOP = object()  # Queue marker: the user released the hotkey.
_ABORT = object()  # Queue marker: the user cancelled.


def available() -> bool:
    """Return True when the realtime socket support is installed."""
    try:
        import websockets  # noqa: F401
    except ImportError:
        return False
    return True


class StreamingSession:
    """One live transcription, from the first chunk to the final words."""

    def __init__(
        self,
        model: str = MODEL,
        keywords: list[str] | None = None,
        language: str | None = None,
        on_delta: Callable[[str], None] | None = None,
        client_factory: Callable[[], object] | None = None,
    ) -> None:
        self.model = model
        self.keywords = keywords or []
        self.language = language
        self.on_delta = on_delta
        self._client_factory = client_factory
        self._pending: list = []  # audio captured before the socket opened
        self._lock = threading.Lock()
        self._queue: asyncio.Queue | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._done = threading.Event()
        self._live = False
        self._transcript: str | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        """Begin opening the socket. This never waits for the network.

        The microphone must open first and stay open. Audio that arrives
        before the socket is ready waits in memory and goes out on connect.
        """
        if not available():
            log.info("The realtime extra is not installed. Using upload.")
            return False
        self._thread = threading.Thread(
            target=self._run, name="mirabel-voice-stream", daemon=True
        )
        self._thread.start()
        return True

    def send(self, chunk: bytes) -> None:
        """Hand one block of audio to the socket."""
        self._put(chunk)

    def _put(self, item) -> None:  # noqa: ANN001
        """Queue audio for the socket, or hold it until the socket opens."""
        with self._lock:
            if not self._live:
                self._pending.append(item)
                return
            loop, target = self._loop, self._queue
        if loop is not None and target is not None:
            loop.call_soon_threadsafe(target.put_nowait, item)

    def finish(self, timeout: float = FINISH_TIMEOUT) -> str | None:
        """Close the turn and return the words, or None on any failure."""
        if self._done.is_set() and self._transcript is None:
            return None
        self._put(_STOP)
        self._done.wait(timeout=timeout)
        if not self._done.is_set():
            log.warning("The live transcript did not arrive in time.")
            self.cancel()
            return None
        return self._transcript

    def cancel(self) -> None:
        """Drop the socket without asking for a transcript."""
        self._put(_ABORT)
        self._done.set()

    # ---- everything below runs on the streaming thread ----

    def _run(self) -> None:
        try:
            asyncio.run(self._session())
        except asyncio.CancelledError:
            log.debug("The live transcription was cancelled.")
        except Exception:  # noqa: BLE001 - the upload path is the safety net
            log.warning("The live transcription failed.", exc_info=True)
        finally:
            with self._lock:
                self._live = False
            self._done.set()

    def _session_config(self) -> dict:
        """Build the session settings for one transcription."""
        transcription: dict = {"model": self.model, "delay": "low"}
        if self.keywords:
            transcription["keywords"] = self.keywords
        if self.language:
            transcription["languages"] = [self.language]
        return {
            "type": "transcription",
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
                    "transcription": transcription,
                    # Push-to-talk decides when the turn ends, not the server.
                    "turn_detection": None,
                }
            },
        }

    async def _session(self) -> None:
        client = (
            self._client_factory()
            if self._client_factory is not None
            else self._default_client()
        )
        # The transcription socket needs this intent and rejects a model
        # in the URL. The model belongs in the session settings instead.
        async with client.realtime.connect(
            extra_query={"intent": "transcription"}
        ) as connection:
            await connection.session.update(session=self._session_config())
            # Take over the audio that arrived while the socket was opening.
            self._queue = asyncio.Queue()
            self._loop = asyncio.get_running_loop()
            with self._lock:
                for item in self._pending:
                    self._queue.put_nowait(item)
                self._pending = []
                self._live = True
            reader = asyncio.create_task(self._read(connection))
            try:
                await self._write(connection)
                await reader
            finally:
                reader.cancel()

    @staticmethod
    def _default_client():  # noqa: ANN205
        from openai import AsyncOpenAI

        return AsyncOpenAI()

    async def _write(self, connection) -> None:  # noqa: ANN001
        """Move audio from the queue onto the socket until the turn ends."""
        while True:
            item = await self._queue.get()
            if item is _ABORT:
                raise asyncio.CancelledError
            if item is _STOP:
                await connection.input_audio_buffer.commit()
                return
            await connection.input_audio_buffer.append(
                audio=base64.b64encode(item).decode("utf-8")
            )

    async def _read(self, connection) -> None:  # noqa: ANN001
        """Collect words until the socket reports the turn is complete."""
        parts: list[str] = []
        async for event in connection:
            kind = getattr(event, "type", "")
            if kind == "conversation.item.input_audio_transcription.delta":
                parts.append(event.delta)
                if self.on_delta is not None:
                    try:
                        self.on_delta("".join(parts))
                    except Exception:  # noqa: BLE001 - the overlay is optional
                        log.debug("A live word update failed.", exc_info=True)
            elif kind == "conversation.item.input_audio_transcription.completed":
                self._transcript = event.transcript
                self._done.set()
                return
            elif kind == "error":
                log.warning("The live socket reported: %s", getattr(event, "error", ""))
                self._done.set()
                return
