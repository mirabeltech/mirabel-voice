"""The version the app reports to the relay."""

import pytest

from mirabel_voice import version


@pytest.fixture(autouse=True)
def fresh_cache():
    version.client_version.cache_clear()
    yield
    version.client_version.cache_clear()


def test_the_reported_version_drops_the_leading_v(monkeypatch):
    monkeypatch.setattr(version, "app_version", lambda: "v0.9.6")
    assert version.client_version() == "0.9.6"


def test_an_unknowable_version_is_reported_as_unknown(monkeypatch):
    monkeypatch.setattr(version, "app_version", lambda: "")
    assert version.client_version() == "unknown"


def test_the_reported_version_is_read_once(monkeypatch):
    asked = []
    monkeypatch.setattr(version, "app_version", lambda: asked.append(1) or "v1.0.0")
    version.client_version()
    version.client_version()
    assert len(asked) == 1


def test_the_flyout_still_offers_the_version_helpers():
    from mirabel_voice import flyout

    assert flyout.app_version is version.app_version
    assert flyout.version_from_markers is version.version_from_markers
