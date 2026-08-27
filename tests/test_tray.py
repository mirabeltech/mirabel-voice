"""The tray menu wiring.

The app-level tests call set_language directly. These tests go through
pystray itself, because pystray calls every action as action(icon, item)
and adapts only callables that expose __code__. A wiring that survives
its own unit test can still break under that convention - the Language
menu did exactly that with a functools.partial.
"""

from types import SimpleNamespace

from mirabel_voice.tray import Tray


class FakeApp:
    """The slice of VoiceApp that the tray touches."""

    def __init__(self):
        self.config = SimpleNamespace(
            language="en",
            relay_url=None,
            relay_token=None,
            cleanup_enabled=True,
            translate_to_english=False,
            input_device=None,
            hotkey="insert",
        )
        self.signin = None
        self.state = "idle"
        self.last_text = ""
        self.chosen = []
        self.translated = []
        self.devices = []

    def set_language(self, code):
        self.chosen.append(code)
        self.config.language = code

    def set_translate(self, on):
        self.translated.append(on)
        self.config.translate_to_english = on

    def set_input_device(self, index):
        self.devices.append(index)
        self.config.input_device = index


def test_clicking_a_language_entry_reaches_set_language():
    tray = Tray(app=FakeApp())
    item = tray._language_item("Telugu", "te")
    # This is the exact call pystray makes on a click: the item receives
    # the icon and passes (icon, item) on to the action.
    item(None)
    assert tray.app.chosen == ["te"]
    assert tray.app.config.language == "te"


def test_the_clicked_entry_shows_as_chosen():
    tray = Tray(app=FakeApp())
    telugu = tray._language_item("Telugu", "te")
    english = tray._language_item("English", "en")
    telugu(None)
    assert telugu.checked
    assert not english.checked


def test_detect_automatically_passes_none():
    tray = Tray(app=FakeApp())
    item = tray._language_item("Detect automatically", None)
    item(None)
    assert tray.app.chosen == [None]


def test_clicking_translate_reaches_set_translate():
    tray = Tray(app=FakeApp())
    item = tray._translate_item()
    item(None)
    assert tray.app.translated == [True]
    item(None)
    assert tray.app.translated == [True, False]


def test_the_translate_entry_shows_its_state():
    tray = Tray(app=FakeApp())
    item = tray._translate_item()
    assert not item.checked
    item(None)
    assert item.checked


def test_the_cleanup_toggle_is_gone_and_translate_lives_under_language():
    """v0.6.4 cut the cleanup toggle - with translate on it sat greyed
    and looked unchecked - and moved translate into the Language menu,
    where the two settings that shape the text sit together."""
    menu = Tray(app=FakeApp())._menu()
    top = [str(item.text) for item in menu.items]
    assert "Clean up with Claude" not in top
    assert "Translate to English" not in top
    language = next(item for item in menu.items if str(item.text) == "Language")
    inner = [str(item.text) for item in language.submenu.items]
    assert "Translate to English" in inner


def test_clicking_a_microphone_reaches_set_input_device():
    tray = Tray(app=FakeApp())
    item = tray._microphone_item("Blue Yeti", 5)
    item(None)
    assert tray.app.devices == [5]
    assert tray.app.config.input_device == 5


def test_system_default_passes_none():
    tray = Tray(app=FakeApp())
    item = tray._microphone_item("System default", None)
    item(None)
    assert tray.app.devices == [None]


def test_the_chosen_microphone_shows_as_chosen():
    tray = Tray(app=FakeApp())
    yeti = tray._microphone_item("Blue Yeti", 5)
    default = tray._microphone_item("System default", None)
    yeti(None)
    assert yeti.checked
    assert not default.checked


def test_the_microphone_menu_shows_each_device_once(monkeypatch):
    """Windows lists a microphone once per audio API. The menu keeps
    the WASAPI entries, which carry full names, and drops the rest."""
    monkeypatch.setattr(
        "mirabel_voice.audio.list_input_devices",
        lambda: [
            {"index": 1, "name": "Microphone (Blue Yeti", "channels": 2, "hostapi": "MME"},
            {"index": 5, "name": "Microphone (Blue Yeti)", "channels": 2, "hostapi": "Windows WASAPI"},
        ],
    )
    submenu = Tray(app=FakeApp())._microphone_menu().submenu
    labels = [str(item.text) for item in submenu.items]
    assert labels == ["System default", "Microphone (Blue Yeti)"]


def test_a_broken_device_listing_still_offers_the_default(monkeypatch):
    def boom():
        raise RuntimeError("no sound device")

    monkeypatch.setattr("mirabel_voice.audio.list_input_devices", boom)
    submenu = Tray(app=FakeApp())._microphone_menu().submenu
    labels = [str(item.text) for item in submenu.items]
    assert labels == ["System default"]


# --- the icons --------------------------------------------------------------


def _colours_in(image):
    """The distinct opaque colours in a PIL image."""
    return {
        rgba[:3]
        for _, rgba in image.convert("RGBA").getcolors(maxcolors=100000)
        if rgba[3] > 200
    }


def test_the_tray_glyph_follows_the_taskbar_theme():
    from mirabel_voice.tray import make_icon_image

    dark_taskbar = _colours_in(make_icon_image("idle", light_taskbar=False))
    light_taskbar = _colours_in(make_icon_image("idle", light_taskbar=True))
    assert (255, 255, 255) in dark_taskbar
    assert (255, 255, 255) not in light_taskbar
    assert (27, 27, 27) in light_taskbar


def test_ready_has_no_badge_and_the_busy_states_do():
    from mirabel_voice.palette import STATE_COLOURS
    from mirabel_voice.tray import make_icon_image

    idle = _colours_in(make_icon_image("idle", light_taskbar=False))
    assert STATE_COLOURS["recording"] not in idle

    for state in ("recording", "working", "error"):
        badge = STATE_COLOURS[state]
        colours = _colours_in(make_icon_image(state, light_taskbar=False))
        # Lanczos softens edges, so look for anything near the badge colour.
        assert any(
            sum(abs(a - b) for a, b in zip(c, badge)) < 60 for c in colours
        ), f"no {state} badge found"


def test_the_app_icon_carries_the_m_only_at_large_sizes():
    from mirabel_voice.tray import make_app_icon

    # The M is ocean-coloured pixels inside the white capsule region.
    def capsule_has_ocean(image):
        size = image.size[0]
        box = image.crop(
            (
                round(size * 0.42),
                round(size * 0.24),
                round(size * 0.58),
                round(size * 0.46),
            )
        )
        return any(
            sum(abs(a - b) for a, b in zip(rgba[:3], (2, 132, 199))) < 90
            for _, rgba in box.convert("RGBA").getcolors(maxcolors=100000)
            if rgba[3] > 200
        )

    assert capsule_has_ocean(make_app_icon(256))
    assert capsule_has_ocean(make_app_icon(48))
    assert not capsule_has_ocean(make_app_icon(32))
    assert not capsule_has_ocean(make_app_icon(16))


def test_the_ico_holds_a_real_image_at_every_size(tmp_path):
    import importlib.util
    from pathlib import Path

    from PIL import Image

    spec = importlib.util.spec_from_file_location(
        "prepare", Path(__file__).parent.parent / "packaging" / "prepare.py"
    )
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)

    icon = tmp_path / "MirabelVoice.ico"
    prepare.write_icon(icon)
    with Image.open(icon) as image:
        sizes = {side for side, _ in image.info["sizes"]}
    assert sizes == {16, 20, 24, 32, 48, 64, 128, 256}

    # And the per-size detail survives the save: the 48 px frame keeps
    # the M, the 32 px frame dropped it. A single-master ICO would have
    # the same drawing at every size.
    def frame_has_ocean(side):
        with Image.open(icon) as image:
            image.size = (side, side)
            image.load()
            box = image.crop(
                (
                    round(side * 0.42),
                    round(side * 0.24),
                    round(side * 0.58),
                    round(side * 0.46),
                )
            )
        return any(
            sum(abs(a - b) for a, b in zip(rgba[:3], (2, 132, 199))) < 90
            for _, rgba in box.convert("RGBA").getcolors(maxcolors=100000)
            if rgba[3] > 200
        )

    assert frame_has_ocean(48)
    assert not frame_has_ocean(32)


# --- the tooltip ------------------------------------------------------------


def test_a_long_tooltip_is_cut_before_windows_cuts_it():
    tray = Tray(app=FakeApp())
    tray.detail = (
        "The text was not inserted - you changed window.\n"
        "Press the paste-last hotkey to insert it here."
    )
    title = tray._title()
    assert len(title) <= 127
    assert title.endswith("…")


def test_a_short_tooltip_is_left_alone():
    tray = Tray(app=FakeApp())
    tray.detail = "Already up to date."
    title = tray._title()
    assert title.endswith("Already up to date.")
