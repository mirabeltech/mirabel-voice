"""Failure-path regression tests for private Windows release readiness."""
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from mirabel_voice.storage import save_bytes, load_validated
from mirabel_voice.transaction import InstallLock, UpdateBusy, replace_directory, recover
from mirabel_voice.work import BoundedWork, WorkCancelled
from mirabel_voice.config import Config
from mirabel_relay.limits import Limits, Rejected, DynamoRateLimit
from mirabel_relay.relay import Request, Relay


def test_interrupted_settings_replacement_keeps_previous_data(tmp_path, monkeypatch):
    from mirabel_voice import storage
    path = tmp_path / 'config.json'
    save_bytes(path, b'{"value":1}')
    original = storage.os.replace
    def fail_main(source, dest):
        if Path(dest) == path:
            raise PermissionError('injected sharing violation')
        return original(source, dest)
    monkeypatch.setattr(storage.os, 'replace', fail_main)
    with pytest.raises(PermissionError):
        save_bytes(path, b'{"value":2}')
    assert json.loads(path.read_bytes()) == {'value': 1}
    assert not list(tmp_path.glob('*.tmp'))


def test_bad_settings_recover_valid_backup_and_preserve_damaged_bytes(tmp_path):
    path = tmp_path / 'config.json'
    Config(hotkey='f13').save(path)
    Config(hotkey='insert').save(path)
    path.write_text('{broken')
    assert Config.load(path).hotkey == 'f13'
    assert path.with_suffix('.json.damaged').read_text() == '{broken'
    assert Config.load(path).hotkey == 'f13'


@pytest.mark.parametrize('value', [{'max_seconds': -1}, {'hot_mic': 'yes'}, {'custom_words': 'word'}, {'cleanup_timeout': float('nan')}])
def test_invalid_settings_cannot_silently_run(tmp_path, value):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        Config.load(path)


def test_directory_proof_failure_restores_old_version(tmp_path):
    old, staged = tmp_path / 'app', tmp_path / 'stage'
    old.mkdir(); staged.mkdir()
    (old / 'version').write_text('old')
    (staged / 'version').write_text('new')
    with InstallLock(tmp_path):
        with pytest.raises(RuntimeError):
            replace_directory(old, staged, lambda: False)
    assert (old / 'version').read_text() == 'old'
    assert not old.with_name('app.transaction.json').exists()


@pytest.mark.parametrize('installed_candidate', [False, True])
def test_launcher_recovers_power_loss_during_directory_swap(tmp_path, installed_candidate):
    target = tmp_path / 'app'
    backup = tmp_path / 'app.previous'
    backup.mkdir(); (backup / 'version').write_text('old')
    if installed_candidate:
        target.mkdir(); (target / 'version').write_text('unproven')
    (tmp_path / 'app.transaction.json').write_text('{"state":"pending"}')
    with InstallLock(tmp_path):
        recover(target)
    assert (target / 'version').read_text() == 'old'


def test_committed_candidate_survives_journal_cleanup_crash(tmp_path):
    target = tmp_path / 'app'; target.mkdir()
    (target / 'version').write_text('new')
    backup = tmp_path / 'app.previous'; backup.mkdir()
    (backup / 'version').write_text('old')
    (tmp_path / 'app.transaction.json').write_text('{"state":"committed"}')
    recover(target)
    assert (target / 'version').read_text() == 'new'
    assert backup.exists()


def test_competing_update_cannot_take_lock(tmp_path):
    with InstallLock(tmp_path):
        with pytest.raises(UpdateBusy):
            with InstallLock(tmp_path):
                pytest.fail('A competing installer acquired the lock')
    with InstallLock(tmp_path):
        pass


def test_deadline_does_not_accumulate_network_workers():
    work, release, cancel = BoundedWork(), threading.Event(), threading.Event()
    try:
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            work.call(lambda: release.wait(10), .03, cancel)
        assert time.monotonic() - start < 1
        with pytest.raises(TimeoutError, match='previous'):
            work.call(lambda: None, .03, cancel)
    finally:
        release.set()
        work._thread.join(1)
    assert work.call(lambda: 'recovered', 1, cancel) == 'recovered'


def test_cancel_ignores_late_network_result():
    work, cancel, release = BoundedWork(), threading.Event(), threading.Event()
    cancel.set()
    try:
        with pytest.raises(WorkCancelled):
            work.call(lambda: release.wait(1) or 'text', 1, cancel)
    finally:
        release.set(); work._thread.join(1)


def cleanup_request(**overrides):
    body = {'model': 'claude-haiku-4-5', 'max_tokens': 8000, 'system': 'Clean text', 'messages': [{'role': 'user', 'content': 'synthetic example'}]}
    body.update(overrides)
    return Request('POST', '/v1/messages', {'x-api-key': 'test'}, json.dumps(body).encode())


@pytest.mark.parametrize('overrides', [{'model': 'expensive-model'}, {'max_tokens': 8001}, {'max_tokens': True}, {'tools': []}, {'stream': True}, {'messages': [{'role': 'user', 'content': [{'type': 'image', 'url': 'https://example.com'}]}]}])
def test_service_rejects_unapproved_cost_paths_before_provider(overrides):
    forwarded = []
    relay = Relay({'test': 'tester'}, 'not-real', 'not-real', forward=lambda *a: forwarded.append(a), limits=Limits())
    assert relay.handle(cleanup_request(**overrides)).status == 400
    assert not forwarded


def test_service_accepts_normal_cleanup():
    Limits().validate(cleanup_request(), 'tester')


def test_service_rate_limit_and_storage_outage_do_not_forward():
    class Limiter:
        def allow(self, person):
            return False
    with pytest.raises(Rejected) as failure:
        Limits(Limiter()).validate(cleanup_request(), 'tester')
    assert failure.value.status == 429
    class Broken:
        def allow(self, person):
            raise OSError('storage unavailable')
    with pytest.raises(Rejected) as failure:
        Limits(Broken()).validate(cleanup_request(), 'tester')
    assert failure.value.status == 503


def test_distributed_counter_uses_atomic_condition_and_hashed_identity():
    calls = []
    client = SimpleNamespace(update_item=lambda **kwargs: calls.append(kwargs))
    assert DynamoRateLimit(client, 'test-table', 10, clock=lambda: 123).allow('person@example.com')
    request = calls[0]
    assert 'ConditionExpression' in request
    assert 'person@example.com' not in json.dumps(request)
    assert request['ExpressionAttributeValues'][':limit'] == {'N': '10'}


def test_pausing_closes_microphone_and_refuses_new_capture():
    from test_app import make_app
    app = make_app()
    app.start_recording()
    recorder = app.recorder
    app.set_microphone_paused(True)
    assert not recorder.recording_now
    assert recorder.cancelled
    assert not app.start_recording()
    assert app.microphone_paused


def test_update_reservation_waits_for_recording_then_blocks_new_capture():
    from test_app import make_app
    app = make_app()
    app.start_recording()
    assert not app.reserve_update()
    app.cancel_recording()
    assert app.reserve_update()
    assert not app.start_recording()
    app.release_update()
    assert app.start_recording()
    app.cancel_recording()


def test_default_microphone_change_defers_reopen_while_recording(monkeypatch):
    from mirabel_voice.audio import Recorder
    from mirabel_voice import system_audio
    recorder = Recorder(hot=True)
    identities = iter(['one', 'two'])
    monkeypatch.setattr(system_audio, 'default_input_id', lambda: next(identities))
    recorder._follow_default_input()
    recorder._armed = True
    recorder._follow_default_input()
    assert recorder._pending_device
    assert recorder.is_recording
    recorder.shutdown()


def test_explicit_microphone_does_not_follow_system_default(monkeypatch):
    from mirabel_voice.audio import Recorder
    from mirabel_voice import system_audio
    monkeypatch.setattr(system_audio, 'default_input_id', lambda: pytest.fail('Explicit microphone must stay selected'))
    Recorder(device=3, hot=True)._follow_default_input()


def test_support_export_omits_private_configuration(tmp_path, monkeypatch):
    from mirabel_voice.diagnostics import export
    monkeypatch.setattr('mirabel_voice.health.check', lambda: 'passed')
    monkeypatch.setenv('MIRABEL_VOICE_HOME', str(tmp_path))
    Config(custom_words=['private-client'], relay_token='secret-token', google_client_id='private-account').save()
    payload = export().read_text()
    assert 'private-client' not in payload and 'secret-token' not in payload and 'private-account' not in payload
    assert set(json.loads(payload)) == {'app_version','windows','architecture','python','bundle','offline_health','privacy'}


def test_changed_dependency_lock_requires_full_bundle(tmp_path):
    from test_updater import a_bundle, a_release
    from mirabel_voice.updater import Updater
    site, runtime = a_bundle(tmp_path)
    (site / 'mirabel_voice' / '_runtime.lock').write_text('current dependencies')
    updater = Updater(site, runtime, fetch=a_release(), prove=lambda: pytest.fail('No switching on incompatible dependencies'))
    assert updater.apply_latest() is None
    assert updater.outcome == 'bundle_required'
    assert (site / 'mirabel_voice' / '__init__.py').read_text() == 'old code'


def test_cancel_during_transcription_prevents_late_paste():
    from test_app import make_app, loud_recording
    app = make_app(cleanup_enabled=False)
    release, entered = threading.Event(), threading.Event()
    def transcribe(_):
        entered.set(); release.wait(2); return 'late text'
    app.transcriber.transcribe = transcribe
    app.state = 'working'
    worker = threading.Thread(target=app._process, args=(loud_recording(),))
    worker.start()
    assert entered.wait(1)
    app.cancel_recording()
    worker.join(1)
    release.set(); app._network._thread.join(1)
    assert not worker.is_alive()
    assert app.injector.sent == []
    assert app._pending_recording is None


def test_failed_recording_can_be_retried_without_new_capture():
    from test_app import make_app, loud_recording
    app = make_app(cleanup_enabled=False)
    recording = loud_recording()
    app.transcriber.transcribe = lambda _: (_ for _ in ()).throw(TimeoutError('offline'))
    app._process(recording)
    assert app._pending_recording is recording
    app.transcriber.transcribe = lambda _: 'Recovered text'
    app.retry_last_recording()
    app._worker.join(1)
    assert app.injector.sent == ['Recovered text']
    assert app._pending_recording is None


def test_copy_failure_does_not_remove_working_application(tmp_path, monkeypatch):
    from mirabel_voice import transaction
    target, staged = tmp_path / 'app', tmp_path / 'stage'
    target.mkdir(); staged.mkdir()
    (target / 'version').write_text('old')
    monkeypatch.setattr(transaction.shutil, 'copytree', lambda *_: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):
        replace_directory(target, staged, lambda: True)
    assert (target / 'version').read_text() == 'old'


def test_old_updater_config_probe_rejects_incompatible_runtime(monkeypatch, capsys):
    from mirabel_voice import __main__, runtime
    monkeypatch.setattr(runtime, 'bundle_problem', lambda: 'Full Python ZIP required')
    assert __main__.main(['--config']) == 1
    assert 'Full Python ZIP required' in capsys.readouterr().out


def test_relay_overload_simulation_limits_forwarding():
    from concurrent.futures import ThreadPoolExecutor
    class SharedCounter:
        def __init__(self):
            self.used = 0
            self.lock = threading.Lock()
        def allow(self, _):
            with self.lock:
                if self.used >= 5:
                    return False
                self.used += 1
                return True
    counter = SharedCounter()
    relay = Relay({'test':'tester'}, 'test-only', 'test-only', forward=lambda *a: (200, {}, b'{}'), limits=Limits(counter))
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: relay.handle(cleanup_request()).status, range(50)))
    assert results.count(200) == 5
    assert results.count(429) == 45


def test_oversize_wav_fallback_never_reaches_provider():
    from mirabel_voice.transcribe import Transcriber, TranscriptionError
    recording = SimpleNamespace(for_upload=lambda: ('speech.wav', b'0' * 4_000_001, 'audio/wav'))
    transcriber = Transcriber(client=SimpleNamespace(), relay_url='https://relay.invalid', relay_token='test-only')
    with pytest.raises(TranscriptionError, match='too large'):
        transcriber.transcribe(recording)


def test_multibyte_custom_words_count_toward_upload_limit():
    from mirabel_voice.transcribe import Transcriber, TranscriptionError
    recording = SimpleNamespace(for_upload=lambda: ('speech.ogg', b'0' * 3_900_000, 'audio/ogg'))
    transcriber = Transcriber(client=SimpleNamespace(), relay_url='https://relay.invalid', relay_token='test-only', custom_words=['語' * 200] * 500)
    with pytest.raises(TranscriptionError, match='custom words are too large'):
        transcriber.transcribe(recording)


def test_five_minute_wav_fallback_is_rejected_before_network(monkeypatch):
    import numpy as np
    from mirabel_voice.audio import Recording
    from mirabel_voice.transcribe import Transcriber, TranscriptionError
    recording = Recording(samples=np.ones(300 * 16000, dtype=np.int16), sample_rate=16000)
    monkeypatch.setattr(Recording, 'to_opus_bytes', lambda _: (_ for _ in ()).throw(RuntimeError('encoder unavailable')))
    transcriber = Transcriber(client=SimpleNamespace(), relay_url='https://relay.invalid', relay_token='test-only')
    with pytest.raises(TranscriptionError, match='too large'):
        transcriber.transcribe(recording)


def test_windows_encrypted_signin_backup_recovers_without_plaintext(tmp_path):
    import sys
    if sys.platform != 'win32':
        pytest.skip('Windows account encryption')
    from mirabel_voice.signin import GoogleSignin
    store = tmp_path / 'synthetic-signin.bin'
    signin = GoogleSignin('synthetic-client', 'synthetic-desktop-value', store=store)
    signin._refresh_token = 'synthetic-original-refresh'
    signin._save()
    signin._refresh_token = 'synthetic-new-refresh'
    signin._save()
    backup = store.with_suffix('.bin.bak')
    assert b'synthetic-original-refresh' not in backup.read_bytes()
    assert b'synthetic-new-refresh' not in store.read_bytes()
    store.write_bytes(b'damaged-encrypted-file')
    recovered = GoogleSignin('synthetic-client', 'synthetic-desktop-value', store=store)
    assert recovered.signed_in()
    assert recovered._refresh_token == 'synthetic-original-refresh'
    assert store.with_suffix('.bin.damaged').read_bytes() == b'damaged-encrypted-file'
