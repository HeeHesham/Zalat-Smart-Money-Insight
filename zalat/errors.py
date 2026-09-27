"""Error hierarchy and the logic that turns low-level exceptions into it.

The MCP SDK runs its transport inside an anyio TaskGroup, so HTTP and
connection failures reach us wrapped in (possibly nested) ``ExceptionGroup``s.
``classify_exception`` flattens those groups and maps the first recognisable
leaf onto one of our own error types, with any secret redacted from the text.
"""

from __future__ import annotations

import asyncio
import re
from typing import Iterable

import httpx

from mcp.shared.exceptions import McpError

#: Messages that indicate a rejected / missing API key.
AUTH_RE = re.compile(r"unauthori[sz]ed|invalid api key|forbidden|\b401\b|\b403\b", re.I)


class ZalatError(Exception):
    """Base class for all errors this tool raises on purpose."""


class ConfigError(ZalatError):
    """Configuration problem (e.g. the API key is missing)."""


class NansenAuthError(ZalatError):
    """Nansen rejected the API key (HTTP 401/403)."""


class NansenNetworkError(ZalatError):
    """Nansen MCP could not be reached (DNS, connect, timeout, 5xx...)."""


class NansenProtocolError(ZalatError):
    """Anything else that went wrong while speaking MCP."""


def _flatten(exc: BaseException) -> list[BaseException]:
    """Return the leaf exceptions of a (nested) exception group."""
    if isinstance(exc, BaseExceptionGroup):
        leaves: list[BaseException] = []
        for sub in exc.exceptions:
            leaves.extend(_flatten(sub))
        return leaves
    return [exc]


def classify_exception(exc: BaseException, secrets: Iterable[str] = ()) -> ZalatError:
    """Map any exception (or exception group) onto a ``ZalatError`` subclass.

    Leaves are checked in order; the first one we recognise wins. Unknown
    exceptions become ``NansenProtocolError``. Messages are redacted.
    """
    # Imported here: config imports this module (ConfigError), so a top-level
    # import would be circular.
    from zalat.config import redact as _redact

    secrets = [s for s in secrets if s]
    if isinstance(exc, ZalatError):
        return type(exc)(_redact(str(exc), secrets))

    leaves = _flatten(exc)
    for leaf in leaves:
        if isinstance(leaf, ZalatError):
            return type(leaf)(_redact(str(leaf), secrets))
        if isinstance(leaf, httpx.HTTPStatusError):
            code = leaf.response.status_code
            if code in (401, 403):
                return NansenAuthError(
                    f"Nansen rejected the API key (HTTP {code}). "
                    "Check NANSEN_API_KEY / NANSEN_API_KEY_HEADER."
                )
            return NansenNetworkError(f"Nansen MCP returned HTTP {code}")
        if isinstance(leaf, (httpx.TimeoutException, asyncio.TimeoutError, TimeoutError)):
            return NansenNetworkError("timeout while talking to Nansen MCP")
        if isinstance(leaf, (httpx.TransportError, OSError)):
            return NansenNetworkError(
                _redact(f"cannot reach Nansen MCP: {type(leaf).__name__}: {leaf}", secrets)
            )
        if isinstance(leaf, McpError):
            msg = _redact(str(leaf), secrets)
            if AUTH_RE.search(msg):
                return NansenAuthError(f"Nansen rejected the request: {msg}")
            return NansenProtocolError(f"MCP error: {msg}")

    first = leaves[0] if leaves else exc
    return NansenProtocolError(_redact(f"{type(first).__name__}: {first}", secrets))
