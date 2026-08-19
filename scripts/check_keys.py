"""Check that the stored API keys actually work.

Prints one plain sentence and exits non-zero when something is wrong, so
the setup script can tell the user before they hit it during dictation.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mirabel_voice.config import Config, load_api_keys  # noqa: E402


def main() -> int:
    load_api_keys()
    try:
        from openai import OpenAI

        OpenAI().models.list()
    except Exception as error:  # noqa: BLE001
        print(f"The OpenAI key was not accepted: {_short(error)}")
        return 1

    if Config.load().cleanup_enabled:
        try:
            import anthropic

            anthropic.Anthropic().messages.count_tokens(
                model=Config.load().cleanup_model,
                messages=[{"role": "user", "content": "hi"}],
            )
        except Exception as error:  # noqa: BLE001
            print(f"The Anthropic key was not accepted: {_short(error)}")
            return 1
    print("Both keys work.")
    return 0


def _short(error: Exception) -> str:
    """Return a short, readable reason."""
    text = str(error).strip().replace("\n", " ")
    return text[:160] if text else error.__class__.__name__


if __name__ == "__main__":
    raise SystemExit(main())
