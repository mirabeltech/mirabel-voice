"""Check that the stored API keys actually work.

Prints one plain sentence and exits non-zero when something is wrong, so
the setup script can tell the user before they hit it during dictation.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mirabel_voice.keycheck import check_keys  # noqa: E402


def main() -> int:
    ok, message = check_keys()
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
