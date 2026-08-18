"""The dictation dictionary.

Two lists feed the models: the Mirabel seed list that ships inside the
package, and the personal words from the user's settings. The merged list
goes to the transcriber as a spelling hint and to the cleanup model as a
spelling rule.
"""

from __future__ import annotations

import json
import logging
from importlib import resources

log = logging.getLogger(__name__)


def seed_words() -> list[str]:
    """Return the Mirabel terms that ship with the package."""
    try:
        payload = (
            resources.files("mirabel_voice") / "data" / "mirabel_terms.json"
        ).read_text(encoding="utf-8")
        return list(json.loads(payload).get("terms", []))
    except (OSError, json.JSONDecodeError, ModuleNotFoundError) as error:
        log.warning("The seed dictionary did not load: %s", error)
        return []


def all_words(personal: list[str] | None = None) -> list[str]:
    """Return the seed list with the personal words merged after it.

    A personal word that repeats a seed word (in any casing) is dropped.
    """
    merged = list(seed_words())
    seen = {word.lower() for word in merged}
    for word in personal or []:
        key = word.lower()
        if key not in seen:
            merged.append(word)
            seen.add(key)
    return merged
