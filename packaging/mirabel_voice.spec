# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for the packaged app.

This produces a folder, not a single file. A folder starts faster, and
antivirus tools treat it far better than a self-extracting executable.
Inno Setup then wraps the folder into the installer.

Two programs come out of one analysis:

* MirabelVoice.exe        - no console. This is what people run.
* MirabelVoiceConsole.exe - a console. The installer uses it to test the
                            keys, it runs the key picker, and it prints
                            messages when something needs diagnosing.

The entry point is packaging/entry.py, not the package's own __main__.py.
See the note in that file: pointing PyInstaller at __main__.py builds an
empty app without reporting an error.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

HERE = Path(SPECPATH).resolve()
ROOT = HERE.parent
ICON = HERE / "MirabelVoice.ico"

# The seed dictionary is read at run time, so it must travel with the app.
datas = [(str(ROOT / "src" / "mirabel_voice" / "data"), "mirabel_voice/data")]
# sounddevice keeps its copy of PortAudio in a separate data package. It
# is a module rather than a package, so its own name collects nothing.
datas += collect_data_files("_sounddevice_data", include_py_files=False)
# Same trap as sounddevice: soundfile is a module, and the libsndfile DLL it
# needs lives in the sibling _soundfile_data package. Miss it and every
# recording silently falls back to WAV.
datas += collect_data_files("_soundfile_data", include_py_files=False)

hiddenimports = collect_submodules("mirabel_voice") + [
    # pystray and pynput choose a backend at import time. PyInstaller
    # cannot see that choice, so name the Windows ones here.
    "pystray._win32",
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
    # The OpenAI live transcription path opens a websocket.
    "soundfile",
    "websockets",
    "websockets.asyncio.client",
]

a = Analysis(
    [str(HERE / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "setuptools", "pip"],
    noarchive=False,
)

pyz = PYZ(a.pure)

windowed = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MirabelVoice",
    debug=False,
    strip=False,
    upx=False,  # UPX compression is a common antivirus trigger.
    console=False,
    icon=str(ICON),
    version=str(HERE / "version_info.txt"),
)

console = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MirabelVoiceConsole",
    debug=False,
    strip=False,
    upx=False,
    console=True,
    icon=str(ICON),
    version=str(HERE / "version_info.txt"),
)

coll = COLLECT(
    windowed,
    console,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="MirabelVoice",
)
