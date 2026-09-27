"""Settings loading and secret redaction.

The Nansen API key is read from a local ``.env`` file (ignored by Git) or from
the ``NANSEN_API_KEY`` environment variable. A real exported variable always
wins over ``.env``. The key is only ever placed in HTTP headers; everything
we print goes through :func:`redact` first.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv

from zalat.errors import ConfigError

DEFAULT_MCP_URL = "https://mcp.nansen.ai/ra/mcp/"
DEFAULT_KEY_HEADER = "NANSEN-API-KEY"
DEFAULT_FNG_URL = "https://api.alternative.me/fng/?limit=2"
PLACEHOLDER_KEYS = {"your_key_here", "changeme", "xxx", "<your key>"}

# Secrets registered here are scrubbed by redact() when no explicit list is given.
_KNOWN_SECRETS: set[str] = set()


@dataclass(frozen=True)
class Settings:
    """Runtime configuration. ``repr`` never shows the key."""

    api_key: str
    mcp_url: str = DEFAULT_MCP_URL
    key_header: str = DEFAULT_KEY_HEADER
    timeout: float = 30.0
    fng_url: str = DEFAULT_FNG_URL

    def __repr__(self) -> str:
        return (
            f"Settings(api_key='***', mcp_url={self.mcp_url!r}, key_header={self.key_header!r}, "
            f"timeout={self.timeout!r}, fng_url={self.fng_url!r})"
        )

    __str__ = __repr__


def _clean(value: str | None) -> str:
    """Strip whitespace and one layer of matching quotes."""
    v = (value or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1].strip()
    return v


def load_settings(env_file: str | Path | None = ".env", timeout: float | None = None) -> Settings:
    """Load settings from ``env_file`` (if it exists) and the environment.

    Raises :class:`ConfigError` when the API key is missing or still the
    placeholder from ``.env.example``.
    """
    if env_file is not None and Path(env_file).is_file():
        # override=False: an exported NANSEN_API_KEY beats the .env file.
        load_dotenv(env_file, override=False)

    key = _clean(os.environ.get("NANSEN_API_KEY"))
    if not key or key.lower() in PLACEHOLDER_KEYS:
        raise ConfigError(
            "NANSEN_API_KEY is not set. Copy .env.example to .env and paste your key (see README)."
        )
    _KNOWN_SECRETS.add(key)

    if timeout is None:
        raw_t = _clean(os.environ.get("ZALAT_TIMEOUT"))
        try:
            timeout = float(raw_t) if raw_t else 30.0
        except ValueError as exc:
            raise ConfigError(f"ZALAT_TIMEOUT must be a number, got {raw_t!r}") from exc
    if timeout <= 0:
        raise ConfigError("timeout must be positive")

    return Settings(
        api_key=key,
        mcp_url=_clean(os.environ.get("NANSEN_MCP_URL")) or DEFAULT_MCP_URL,
        key_header=_clean(os.environ.get("NANSEN_API_KEY_HEADER")) or DEFAULT_KEY_HEADER,
        timeout=timeout,
        fng_url=_clean(os.environ.get("ZALAT_FNG_URL")) or DEFAULT_FNG_URL,
    )


def redact(text: str, secrets: Iterable[str] | None = None) -> str:
    """Replace every non-empty secret in ``text`` with ``***``.

    With ``secrets=None`` the keys loaded by :func:`load_settings` in this
    process (plus a current ``NANSEN_API_KEY`` env var) are used.
    """
    if secrets is None:
        pool = set(_KNOWN_SECRETS)
        env_key = _clean(os.environ.get("NANSEN_API_KEY"))
        if env_key:
            pool.add(env_key)
        secrets = pool
    # Longest first so a secret containing another is fully replaced.
    for s in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(s, "***")
    return text
