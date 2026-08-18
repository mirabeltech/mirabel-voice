"""Measure whether live transcription really returns words DURING speech.

The question this answers: when we stream audio to the realtime API while
the user is still talking, does text come back before they stop? If the
first words only arrive after we commit, streaming buys us nothing over
the current upload-after-release design.

The script paces a recorded utterance in real time, exactly as a live
microphone would deliver it, and timestamps every event.

Run:
    python scripts/spike_streaming.py path\\to\\audio24k.wav

The audio must be 24 kHz mono PCM16 - the only format the API accepts.
"""

from __future__ import annotations

import asyncio
import base64
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mirabel_voice.config import load_api_keys
from mirabel_voice.dictionary import all_words

MODEL = "gpt-live-transcribe"
SAMPLE_RATE = 24000
CHUNK_MS = 100
CHUNK_BYTES = SAMPLE_RATE * 2 * CHUNK_MS // 1000


def read_pcm(path: Path) -> bytes:
    """Return the raw PCM16 bytes of a 24 kHz mono WAV file."""
    with wave.open(str(path), "rb") as handle:
        if handle.getframerate() != SAMPLE_RATE or handle.getnchannels() != 1:
            raise SystemExit(
                f"{path} is {handle.getframerate()} Hz / "
                f"{handle.getnchannels()} channel. Need 24000 Hz mono."
            )
        return handle.readframes(handle.getnframes())


async def main() -> int:
    load_api_keys()
    source = Path(sys.argv[1])
    pcm = read_pcm(source)
    duration = len(pcm) / (SAMPLE_RATE * 2)
    print(f"audio: {duration:.1f}s, {len(pcm) // CHUNK_BYTES} chunks of {CHUNK_MS}ms")

    from openai import AsyncOpenAI

    client = AsyncOpenAI()
    deltas: list[tuple[float, str]] = []
    completed_at = None
    final_text = ""
    errors: list[str] = []

    started = time.perf_counter()

    def elapsed() -> float:
        return time.perf_counter() - started

    async with client.realtime.connect(
        # Undocumented but required: a transcription session rejects model=
        # in the URL and needs this intent instead.
        extra_query={"intent": "transcription"},
    ) as conn:
        print(f"[{elapsed():6.2f}s] socket open")
        await conn.session.update(
            session={
                "type": "transcription",
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
                        "transcription": {
                            "model": MODEL,
                            "delay": "low",
                            # The dictionary must survive on this path too.
                            "keywords": all_words([]),
                        },
                        "turn_detection": None,  # push-to-talk owns the turn
                    }
                },
            }
        )

        async def pump() -> float:
            """Send audio at real-world speed. Return the commit time."""
            for offset in range(0, len(pcm), CHUNK_BYTES):
                chunk = pcm[offset : offset + CHUNK_BYTES]
                await conn.input_audio_buffer.append(
                    audio=base64.b64encode(chunk).decode("utf-8")
                )
                await asyncio.sleep(CHUNK_MS / 1000)
            commit_time = elapsed()
            print(f"[{commit_time:6.2f}s] key released -> commit")
            await conn.input_audio_buffer.commit()
            return commit_time

        pump_task = asyncio.create_task(pump())

        async for event in conn:
            kind = getattr(event, "type", "")
            if kind == "conversation.item.input_audio_transcription.delta":
                deltas.append((elapsed(), event.delta))
                print(f"[{elapsed():6.2f}s] delta: {event.delta!r}")
            elif kind == "conversation.item.input_audio_transcription.completed":
                completed_at = elapsed()
                final_text = event.transcript
                print(f"[{completed_at:6.2f}s] completed")
                break
            elif kind == "error":
                errors.append(str(getattr(event, "error", event)))
                print(f"[{elapsed():6.2f}s] ERROR: {errors[-1]}")
                break
            elif kind in ("session.created", "session.updated"):
                print(f"[{elapsed():6.2f}s] {kind}")

        commit_at = await pump_task

    print("\n--- verdict ---")
    if errors:
        print("FAILED:", *errors, sep="\n  ")
        return 1
    print(f"final: {final_text!r}")
    if not deltas:
        print("NO DELTAS. Streaming gives no benefit over the current design.")
        return 1
    first_delta, _ = deltas[0]
    during = [t for t, _ in deltas if t < commit_at]
    print(f"first word at {first_delta:.2f}s (speech ended at {commit_at:.2f}s)")
    print(f"{len(during)} of {len(deltas)} deltas arrived WHILE speaking")
    if completed_at is not None:
        tail = completed_at - commit_at
        print(f"release -> final transcript: {tail:.2f}s")
        print(f"estimated release -> pasted text: {tail + 0.75:.2f}s (+cleanup)")
    verdict = "REAL STREAMING" if during else "NOT STREAMING - words only after release"
    print(f"verdict: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
