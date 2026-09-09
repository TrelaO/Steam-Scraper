import json
import os
import threading
from pathlib import Path

# Mirrors quota_guard.py's persistence pattern: a small JSON file under data/, guarded
# by a lock, so a key entered through the Settings UI survives a container restart
# without needing to be re-typed - same reasoning as jobs.json for job state.
KEY_FILE = Path(__file__).resolve().parent.parent / "data" / "api_key_override.json"

_lock = threading.Lock()


def _load() -> dict:
    if not KEY_FILE.exists():
        return {"api_key": None}
    try:
        return json.loads(KEY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"api_key": None}


def _save(data: dict) -> None:
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(json.dumps(data), encoding="utf-8")


def get_api_key() -> str | None:
    """The key actually used for LLM calls. A runtime override (set via the Settings
    UI) takes priority over GEMINI_API_KEY from .env - checked first, falling back to
    .env only if no override is set - so pasting a key into the app takes effect
    immediately, without editing .env or restarting the container. Works for any
    provider key, not just Gemini's; the app only integrates with the Gemini API today,
    but nothing here is Gemini-specific about where the key comes from."""
    with _lock:
        override = _load().get("api_key")
    if override:
        return override
    return os.environ.get("GEMINI_API_KEY")


def set_api_key(key: str) -> None:
    key = key.strip()
    if not key:
        raise ValueError("API key cannot be empty")
    with _lock:
        _save({"api_key": key})


def clear_api_key() -> None:
    with _lock:
        _save({"api_key": None})


def _mask(key: str) -> str:
    if len(key) <= 4:
        return "•" * len(key)
    return "•" * (len(key) - 4) + key[-4:]


def get_status() -> dict:
    """Never returns the raw key - only whether one is configured, where it came
    from (a runtime override vs. .env), and a masked preview for the UI to confirm
    "yes, that's the key I meant" without re-exposing the secret."""
    with _lock:
        override = _load().get("api_key")
    if override:
        return {"source": "override", "masked": _mask(override)}
    env_key = os.environ.get("GEMINI_API_KEY")
    if env_key:
        return {"source": "env", "masked": _mask(env_key)}
    return {"source": "none", "masked": None}
