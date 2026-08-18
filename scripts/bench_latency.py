"""Latency harness for the Mirabel Voice pipeline.

Feeds a synthesized spoken sentence through the real transcribe and cleanup
stages three times each and prints per-stage timings. Red when the median
post-release path exceeds the 2.0 s budget.
"""

import statistics
import sys
import time
import wave

sys.path.insert(0, r"C:\Dev\mirabel-voice\src")

import numpy as np

from mirabel_voice.audio import Recording
from mirabel_voice.cleanup import Cleaner
from mirabel_voice.config import load_api_keys
from mirabel_voice.dictionary import all_words
from mirabel_voice.transcribe import Transcriber

BUDGET_SECONDS = 2.0
PASTE_OVERHEAD = 0.15  # PASTE_SETTLE_SECONDS before Ctrl+V lands
ROUNDS = 3

load_api_keys()

with wave.open(r"C:\Users\thoma\AppData\Local\Temp\claude\c--Users-thoma\33238760-d699-40f3-a92c-a4ddc8c9ea5c\scratchpad\bench.wav", "rb") as handle:
    frames = handle.readframes(handle.getnframes())
recording = Recording(
    samples=np.frombuffer(frames, dtype=np.int16), sample_rate=16000
)
print(f"audio: {recording.duration:.1f}s of speech")

words = all_words([])
args = sys.argv[1:]
warm = "--warm" in args
transcribe_models = [a for a in args if not a.startswith("--")] or ["whisper-1"]
cleaner = Cleaner(custom_words=words)


for model in transcribe_models:
    transcriber = Transcriber(model=model, language="en", custom_words=words)
    if warm:
        t0 = time.perf_counter()
        transcriber.client.models.list()
        cleaner.client.messages.count_tokens(
            model=cleaner.model, messages=[{"role": "user", "content": "hi"}]
        )
        print(f"warm-up pings done in {time.perf_counter() - t0:.2f}s")
    t_times, c_times = [], []
    transcript = cleaned = ""
    for round_number in range(ROUNDS):
        t0 = time.perf_counter()
        transcript = transcriber.transcribe(recording)
        t1 = time.perf_counter()
        cleaned = cleaner.clean(transcript)
        t2 = time.perf_counter()
        t_times.append(t1 - t0)
        c_times.append(t2 - t1)
        print(
            f"  [{model}] round {round_number + 1}: "
            f"transcribe {t1 - t0:.2f}s  cleanup {t2 - t1:.2f}s"
        )
    t_med = statistics.median(t_times)
    c_med = statistics.median(c_times)
    total = t_med + c_med + PASTE_OVERHEAD
    verdict = "GREEN" if total <= BUDGET_SECONDS else "RED"
    print(f"[{model}] raw: {transcript!r}")
    print(f"[{model}] cleaned: {cleaned!r}")
    print(
        f"[{model}] median transcribe {t_med:.2f}s + cleanup {c_med:.2f}s "
        f"+ paste {PASTE_OVERHEAD:.2f}s = {total:.2f}s -> {verdict}"
    )
