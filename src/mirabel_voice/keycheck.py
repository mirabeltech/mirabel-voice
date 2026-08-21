"""Check that this machine can really reach the models.

The setup script and the installer both call this before they say the app
is ready. A wrong credential must fail here, with one plain sentence,
rather than during the first dictation.

There are two ways to be set up. A relay machine holds one token and no
provider keys, so the check is one call to the relay. A development
machine holds the two provider keys and calls the providers directly.
"""

from __future__ import annotations

from .config import Config, load_api_keys


def check_keys() -> tuple[bool, str]:
    """Try whatever this machine is set up to use, and say what failed."""
    load_api_keys()
    config = Config.load()
    if config.relay_url:
        return check_relay(config)
    return _check_provider_keys(config)


def check_relay(config: Config) -> tuple[bool, str]:
    """Try the relay with this machine's token.

    One cleanup call settles the whole path: the address answers, the
    relay knows the token, and the provider key behind it works. The same
    token opens the transcription route, so one call is enough for both.
    A refused token comes back as 401 and reads as such.
    """
    if not config.relay_token:
        return False, "This machine has a relay address but no token. Ask Tommy for yours."

    from .cleanup import Cleaner

    cleaner = Cleaner(
        model=config.cleanup_model,
        timeout=config.cleanup_timeout,
        relay_url=config.relay_url,
        relay_token=config.relay_token,
    )
    try:
        cleaner.client.messages.create(
            model=config.cleanup_model,
            max_tokens=1,
            messages=[{"role": "user", "content": "hi"}],
        )
    except Exception as error:  # noqa: BLE001 - any failure means no dictation
        return False, f"The relay did not accept this machine: {_short(error)}"

    return True, "The relay works."


def _check_provider_keys(config: Config) -> tuple[bool, str]:
    """Try both providers directly. Return whether they work, and why not.

    The app never needs the Anthropic key when the cleanup is off, so this
    skips that provider in that case.
    """
    try:
        from openai import OpenAI

        OpenAI().models.list()
    except Exception as error:  # noqa: BLE001 - any failure is a bad key
        return False, f"The OpenAI key was not accepted: {_short(error)}"

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
