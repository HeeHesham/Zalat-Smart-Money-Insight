"""Optional per-token SOCIAL sentiment from LunarCrush (API v4).

This adapter is only active when ``LUNARCRUSH_API_KEY`` is set. Social metrics
need a PAID LunarCrush plan; the free "Hobby" tier has market data only. Without
a key we make no request at all and report ``not_configured``; the verdict then
compares smart money with the market-wide Fear & Greed mood instead.

Endpoint (best effort; field names are parsed defensively)::

    GET {base}/public/coins/{coin}/v1     Authorization: Bearer <key>
    -> {"data": {"sentiment": 0-100 (% positive), "galaxy_score": 0-100,
                 "price": ..., "percent_change_24h": ..., ...}}

:func:`fetch_social` never raises: every failure becomes a status.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from zalat.config import redact
from zalat.parsing import norm, parse_number

SOCIAL_STATUSES = ("ok", "not_configured", "not_authorized", "rate_limited",
                   "no_sentiment", "no_symbol", "mismatch", "error")

#: If LunarCrush's price and Nansen's search price differ by more than this
#: factor, the symbol probably refers to a different coin: ignore LunarCrush.
PRICE_GUARD_RATIO = 2.0


@dataclass
class SocialSignal:
    """Token-specific social sentiment (or why it is unavailable)."""

    status: str
    symbol: str | None = None
    #: 0-100, share of positive social posts.
    sentiment: float | None = None
    #: Our bucket (see :func:`social_bucket`); "Unavailable" unless status == "ok".
    label: str = "Unavailable"
    #: (sentiment - 50) / 50 in [-1, 1]; None unless status == "ok".
    score: float | None = None
    galaxy_score: float | None = None
    price_usd: float | None = None
    pct_change_24h: float | None = None
    http_status: int | None = None
    error: str | None = None

    @property
    def available(self) -> bool:
        return self.status == "ok"


def social_bucket(v: float) -> str:
    """Bucket a 0-100 sentiment value."""
    if v <= 20:
        return "Very Bearish"
    if v <= 40:
        return "Bearish"
    if v <= 60:
        return "Mixed"
    if v < 80:
        return "Bullish"
    return "Very Bullish"


def _field(d: dict[str, Any], *names: str) -> float | None:
    """First parseable number among keys whose normalised name is in ``names``."""
    wanted = {norm(n) for n in names}
    for k, v in d.items():
        if norm(k) in wanted:
            n = parse_number(v)
            if n is not None:
                return n
    return None


def signal_from_data(symbol: str, data: Any) -> SocialSignal:
    """Build a :class:`SocialSignal` from a decoded LunarCrush response (pure)."""
    d = data.get("data", data) if isinstance(data, dict) else None
    if isinstance(d, list):
        d = d[0] if d and isinstance(d[0], dict) else None
    if not isinstance(d, dict):
        return SocialSignal("error", symbol, error="unexpected response shape")
    sentiment = _field(d, "sentiment", "sentiment_score")
    sig = SocialSignal(
        "ok", symbol,
        galaxy_score=_field(d, "galaxy_score"),
        price_usd=_field(d, "price", "price_usd"),
        pct_change_24h=_field(d, "percent_change_24h", "price_change_24h"),
    )
    if sentiment is None or not 0 <= sentiment <= 100:
        sig.status = "no_sentiment"
        return sig
    sig.sentiment = sentiment
    sig.label = social_bucket(sentiment)
    sig.score = (sentiment - 50) / 50
    return sig


def apply_price_guard(sig: SocialSignal, search_price: float | None) -> SocialSignal:
    """Mark the signal ``mismatch`` if its price is far from Nansen's.

    Symbols are not unique (many coins are called "PEPE"); a price that is off
    by more than 2x means LunarCrush is describing a different coin.
    """
    if not sig.available or not search_price or not sig.price_usd:
        return sig
    if search_price <= 0 or sig.price_usd <= 0:
        return sig
    ratio = sig.price_usd / search_price
    if ratio > PRICE_GUARD_RATIO or ratio < 1 / PRICE_GUARD_RATIO:
        return dataclasses.replace(sig, status="mismatch", label="Unavailable", score=None)
    return sig


async def fetch_social(symbol: str | None, key: str | None, base: str, timeout: float,
                       client: httpx.AsyncClient | None = None) -> SocialSignal:
    """Fetch social sentiment for ``symbol``. Never raises.

    With no ``key`` this returns ``not_configured`` immediately, before any
    HTTP client is created (zero network traffic).
    """
    if not key:
        return SocialSignal("not_configured", symbol)
    if not symbol:
        return SocialSignal("no_symbol", None)

    url = f"{base.rstrip('/')}/public/coins/{quote(symbol.lower(), safe='')}/v1"
    own = client is None
    try:
        http = client or httpx.AsyncClient(timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return SocialSignal("error", symbol, error=redact(f"{type(exc).__name__}: {exc}", [key])[:200])
    try:
        resp = await http.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=timeout)
        code = resp.status_code
        if code in (401, 402, 403):
            return SocialSignal("not_authorized", symbol, http_status=code)
        if code == 429:
            return SocialSignal("rate_limited", symbol, http_status=code)
        if code != 200:
            return SocialSignal("error", symbol, http_status=code, error=f"HTTP {code}")
        sig = signal_from_data(symbol, resp.json())
        sig.http_status = code
        return sig
    except Exception as exc:  # noqa: BLE001 - optional source: any failure -> status
        return SocialSignal("error", symbol,
                            error=redact(f"{type(exc).__name__}: {exc}", [key])[:200])
    finally:
        if own:
            await http.aclose()
