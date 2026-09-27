"""Fear & Greed fetching and bucketing."""

import asyncio

import httpx
import pytest

from zalat.fng import crowd_bucket, fetch_fng, signal_from_value

URL = "https://api.alternative.me/fng/?limit=2"


def _fetch(handler):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await fetch_fng(URL, 5, client=c)
    return asyncio.run(go())


def test_fetch_ok():
    body = {"name": "Fear and Greed Index", "data": [
        {"value": "32", "value_classification": "Fear", "timestamp": "1727395200"},
        {"value": "54", "value_classification": "Neutral", "timestamp": "1727308800"}],
        "metadata": {"error": None}}
    s = _fetch(lambda r: httpx.Response(200, json=body))
    assert s.available and s.value == 32 and s.label == "Fear"
    assert s.classification == "Fear" and s.timestamp == 1727395200
    assert s.score == pytest.approx(-0.36)


@pytest.mark.parametrize("handler", [
    lambda r: httpx.Response(500, text="err"),
    lambda r: httpx.Response(200, text="not json"),
    lambda r: httpx.Response(200, json={"data": []}),
])
def test_fetch_failures_are_unavailable(handler):
    s = _fetch(handler)
    assert not s.available and s.label == "Unavailable" and s.score is None and s.error


def test_fetch_without_client_is_blocked_offline_but_never_raises():
    s = asyncio.run(fetch_fng(URL, 1))
    assert not s.available


@pytest.mark.parametrize("v, label", [(0, "Extreme Fear"), (24, "Extreme Fear"), (25, "Fear"),
                                      (44, "Fear"), (45, "Neutral"), (55, "Neutral"),
                                      (56, "Greed"), (75, "Greed"), (76, "Extreme Greed"),
                                      (100, "Extreme Greed")])
def test_buckets(v, label):
    assert crowd_bucket(v) == label
    assert signal_from_value(v).label == label
