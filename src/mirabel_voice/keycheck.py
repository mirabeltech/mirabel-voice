"""Check that the stored API keys really work.

The setup script and the installer both call this before they say the app
is ready. A key that is wrong must fail here, with one plain sentence,
rather than during the first dictation.
"""

from __future__ import annotations

from .config import Config, load_api_keys


def check_keys() -> tuple[bool, str]:
    """Try both providers. Return whether they work, and why not.

    The app never needs the Anthropic key when the cleanup is off, so this
    skips that provider in that case.
    """
    load_api_keys()
    try:
        from openai import OpenAI

        OpenAI().models.list()
    except Exception as error:  # noqa: BLE001 - any failure is a bad key
        return False, f"The OpenAI key was not accepted: {_short(error)}"

    config = Config.load()
    if config.cleanup_enabled:
        try:
            import anthropic

            anthropic.Anthropic().messages.count_tokens(
                model=config.cleanup_model,
                messages=[{"role": "user", "content": "hi"}],
            )
        except Exception as error:  # noqa: BLE001 - any failure is a bad key
            return False, f"The Anthropic key was not accepted: {_short(error)}"

    return True, "Both keys work."


def _short(error: Exception) -> str:
    """Return a short, readable reason."""
    text = str(error).strip().replace("\n", " ")
    return text[:160] if text else error.__class__.__name__
