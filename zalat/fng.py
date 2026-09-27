"""Market-wide mood from the alternative.me Crypto Fear & Greed Index.

Important: this index is MARKET-WIDE and BTC-centric. It is not a per-token
sentiment score; we use it as a proxy for how the crowd feels overall.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass
class CrowdSignal:
    """The crowd side of the verdict."""

    available: bool
    value: int | None = None
    #: Classification text as returned by the API (e.g. "Extreme Fear").
    classification: str | None = None
    #: Our own bucket label (see :func:`crowd_bucket`); "Unavailable" on failure.
    label: str = "Unavailable"
    #: (value - 50) / 50, in [-1, 1]: negative = fear, positive = greed.
    score: float | None = None
    timestamp: int | None = None
    error: str | None = None


def crowd_bucket(v: int) -> str:
    """Bucket a 0-100 index value into our five crowd-mood labels."""
    if v <= 24:
        return "Extreme Fear"
    if v <= 44:
        return "Fear"
    if v <= 55:
        return "Neutral"
    if v <= 75:
        return "Greed"
    return "Extreme Greed"


def signal_from_value(value: int, classification: str | None = None,
                      timestamp: int | None = None) -> CrowdSignal:
    """Build an available :class:`CrowdSignal` from an index value."""
    value = max(0, min(100, int(value)))
    return CrowdSignal(True, value, classification, crowd_bucket(value),
                       (value - 50) / 50, timestamp)


async def fetch_fng(url: str, timeout: float,
                    client: httpx.AsyncClient | None = None) -> CrowdSignal:
    """Fetch the latest index value. Never raises; failures -> unavailable."""
    own = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    try:
        resp = await http.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        latest = data["data"][0]
        ts = latest.get("timestamp")
        return signal_from_value(
            int(latest["value"]),
            latest.get("value_classification"),
            int(ts) if ts not in (None, "") else None,
        )
    except Exception as exc:  # noqa: BLE001 - any failure just means "unavailable"
        return CrowdSignal(False, error=f"{type(exc).__name__}: {exc}"[:200])
    finally:
        if own:
            await http.aclose()


#: Clearer name: this signal is the MARKET-WIDE mood, not a token's crowd.
MarketMood = CrowdSignal
