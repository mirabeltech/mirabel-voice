"""One bounded service check with a deliberately supplied synthetic speech fixture.

Default mode checks the local app only. --live sends two provider requests and
incurs their normal small cost; it never records the microphone or logs results.
"""
import argparse
import json
import time
from pathlib import Path


def check_live(audio: Path):
    import numpy as np
    import soundfile
    from mirabel_voice.config import Config
    from mirabel_voice.app import VoiceApp
    from mirabel_voice.audio import Recording
    from mirabel_voice.transcribe import Transcriber
    from mirabel_voice.cleanup import Cleaner
    config = Config.load()
    if not config.relay_url:
        raise ValueError('This check requires the configured organization relay')
    if audio.stat().st_size > 4_000_000:
        raise ValueError('Use a short synthetic speech fixture under 4 MB')
    samples, rate = soundfile.read(audio, dtype='int16', always_2d=True)
    if not 0 < len(samples) / rate <= 10:
        raise ValueError('Use a synthetic speech fixture no longer than ten seconds')
    signin = VoiceApp._build_signin(config)
    token = signin.credential if signin is not None else config.relay_token
    transcriber = Transcriber(model=config.transcribe_model, relay_url=config.relay_url, relay_token=token, timeout=30)
    cleaner = Cleaner(model=config.cleanup_model, relay_url=config.relay_url, relay_token=token, timeout=20)
    start = time.monotonic()
    from mirabel_voice.work import BoundedWork
    import threading
    cancel = threading.Event()
    transcript = BoundedWork().call(lambda: transcriber.transcribe(Recording(samples=samples[:, 0].astype(np.int16), sample_rate=rate)), 120, cancel)
    transcription_ms = round((time.monotonic() - start) * 1000)
    if not transcript.strip():
        raise RuntimeError('Synthetic speech produced no text')
    start = time.monotonic()
    cleaned = BoundedWork().call(lambda: cleaner.clean('This is a synthetic Mirabel Voice availability check.'), 20, cancel)
    if cleaner.last_failed or not cleaned.strip():
        raise RuntimeError('Cleanup service check failed')
    return {'transcription': 'passed', 'transcription_ms': transcription_ms, 'cleanup': 'passed', 'cleanup_ms': round((time.monotonic() - start) * 1000)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--audio', type=Path, help='Non-sensitive synthetic speech, not an employee recording')
    args = parser.parse_args(argv)
    if args.live and not args.audio:
        parser.error('--live needs --audio with a short synthetic speech fixture')
    try:
        if args.live:
            result = check_live(args.audio)
        else:
            from mirabel_voice.health import check
            check()
            result = {'offline_health': 'passed', 'service': 'not tested; use --live with a synthetic fixture'}
        print(json.dumps(result))
        return 0
    except Exception as error:
        # No provider error payloads, filenames, account identifiers or keys.
        print(json.dumps({'result': 'failed', 'category': type(error).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
