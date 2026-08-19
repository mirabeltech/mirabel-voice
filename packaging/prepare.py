"""Write the two build inputs that PyInstaller needs.

1. MirabelVoice.ico   - the Start menu and taskbar icon.
2. version_info.txt   - the Windows file properties, so the file shows a
                        publisher and a version instead of blanks. A file
                        with no properties looks more suspicious to both
                        people and antivirus tools.

Run this before PyInstaller. It prints the version, so the build script
can use the same number for the installer.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from mirabel_voice import __version__  # noqa: E402
from mirabel_voice.app import STATE_IDLE  # noqa: E402
from mirabel_voice.tray import make_icon_image  # noqa: E402

COMPANY = "Mirabel Technologies"
PRODUCT = "Mirabel Voice"
# Windows picks the size it needs from these.
ICON_SIZES = [16, 24, 32, 48, 64, 128, 256]

VERSION_TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={parts},
    prodvers={parts},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', '{company}'),
        StringStruct('FileDescription', '{product}'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', 'MirabelVoice'),
        StringStruct('OriginalFilename', 'MirabelVoice.exe'),
        StringStruct('ProductName', '{product}'),
        StringStruct('ProductVersion', '{version}'),
      ]),
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])]),
  ],
)
"""


def version_parts(version: str) -> tuple[int, int, int, int]:
    """Turn "0.1.0" into the four numbers that Windows wants."""
    numbers = [int(part) for part in version.split(".")[:3]]
    while len(numbers) < 3:
        numbers.append(0)
    return (numbers[0], numbers[1], numbers[2], 0)


def main() -> int:
    """Write both files and return the process exit code."""
    icon = HERE / "MirabelVoice.ico"
    make_icon_image(STATE_IDLE).save(
        icon, format="ICO", sizes=[(s, s) for s in ICON_SIZES]
    )

    resource = HERE / "version_info.txt"
    resource.write_text(
        VERSION_TEMPLATE.format(
            parts=version_parts(__version__),
            company=COMPANY,
            product=PRODUCT,
            version=__version__,
        ),
        encoding="utf-8",
    )

    print(__version__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
