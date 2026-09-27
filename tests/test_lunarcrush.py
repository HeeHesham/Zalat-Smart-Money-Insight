"""LunarCrush adapter (optional, paid plan): parsing, statuses, zero-request guarantee."""

import asyncio
import json

import httpx
import pytest

from tests.conftest import FAKE_LC_KEY, fixture_text
from zalat.lunarcrush import (
    SocialSignal,
    apply_price_guard,
    fetch_social,
    signal_from_data,
    social_bucket,
)

BASE = "https://lunarcrush.example/api4"


def _fetch(handler, symbol="PEPE", key=FAKE_LC_KEY, seen=None):
    def wrapped(req):
        if seen is not None:
            seen.append(req)
        return handler(req)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(wrapped)) as c:
            return await fetch_social(symbol, key, BASE, 5, client=c)
    return asyncio.run(go())


def test_ok_parse_and_request_shape():
    seen = []
    sig = _fetch(lambda r: httpx.Response(200, text=fixture_text("lc_coin.json")), seen=seen)
    assert sig.status == "ok" and sig.available
    assert sig.sentiment == 78 and sig.label == "Bullish"
    assert sig.score == pytest.approx(0.56)
    assert sig.galaxy_score == 65 and sig.price_usd == pytest.approx(4.1e-06)
    assert sig.pct_change_24h == pytest.approx(-5.2) and sig.http_status == 200
    (req,) = seen
    assert str(req.url) == f"{BASE}/public/coins/pepe/v1"
    assert req.headers["Authorization"] == f"Bearer {FAKE_LC_KEY}"
    assert FAKE_LC_KEY not in str(req.url)


@pytest.mark.parametrize("code, status", [(401, "not_authorized"), (402, "not_authorized"),
                                          (403, "not_authorized"), (429, "rate_limited"),
                                          (500, "error"), (404, "error")])
def test_http_errors(code, status):
    sig = _fetch(lambda r: httpx.Response(code, text=f"denied {FAKE_LC_KEY}"))
    assert sig.status == status and not sig.available and sig.http_status == code
    assert sig.score is None and sig.label == "Unavailable"
    assert FAKE_LC_KEY not in (sig.error or "")


def test_bad_json_and_transport_error_are_error_without_key():
    assert _fetch(lambda r: httpx.Response(200, text="<html>")).status == "error"

    def boom(req):
        raise httpx.ConnectError(f"refused {FAKE_LC_KEY}")

    sig = _fetch(boom)
    assert sig.status == "error" and FAKE_LC_KEY not in sig.error and "***" in sig.error


def test_no_sentiment_keeps_other_fields():
    sig = _fetch(lambda r: httpx.Response(200, text=fixture_text("lc_no_sentiment.json")))
    assert sig.status == "no_sentiment" and not sig.available
    assert sig.price_usd == pytest.approx(4.1e-06) and sig.score is None


def test_no_key_makes_zero_requests(monkeypatch):
    def forbid(*a, **k):
        raise AssertionError("an HTTP client was created without a LunarCrush key")

    monkeypatch.setattr(httpx.AsyncClient, "__init__", forbid)
    for key in (None, ""):
        sig = asyncio.run(fetch_social("PEPE", key, BASE, 5))
        assert sig.status == "not_configured" and sig.symbol == "PEPE"


def test_no_symbol_makes_zero_requests(monkeypatch):
    monkeypatch.setattr(httpx.AsyncClient, "__init__",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no request expected")))
    assert asyncio.run(fetch_social(None, FAKE_LC_KEY, BASE, 5)).status == "no_symbol"


def test_real_client_path_is_blocked_offline_but_never_raises():
    # No injected client: the conftest network block makes the request fail.
    sig = asyncio.run(fetch_social("PEPE", FAKE_LC_KEY, BASE, 1))
    assert sig.status == "error" and FAKE_LC_KEY not in (sig.error or "")


def test_signal_from_data_variants():
    assert signal_from_data("X", {"data": [{"sentiment": "62"}]}).label == "Bullish"
    assert signal_from_data("X", {"data": {"sentiment_score": 15}}).label == "Very Bearish"
    assert signal_from_data("X", {"data": {"sentiment": 150}}).status == "no_sentiment"
    assert signal_from_data("X", "nope").status == "error"
    assert signal_from_data("X", {"data": {"price_usd": "1.5", "price_change_24h": "3%"}}).pct_change_24h == 3


def test_social_bucket_boundaries():
    assert [social_bucket(v) for v in (20, 21, 40, 41, 60, 61, 79, 80)] == [
        "Very Bearish", "Bearish", "Bearish", "Mixed", "Mixed", "Bullish", "Bullish", "Very Bullish"]


def test_price_guard():
    ok = signal_from_data("PEPE", json.loads(fixture_text("lc_coin.json")))
    assert apply_price_guard(ok, 4e-06).status == "ok"          # ratio 1.025
    assert apply_price_guard(ok, 2.1e-06).status == "ok"        # ratio ~1.95
    bad = apply_price_guard(ok, 1e-06)                          # ratio 4.1
    assert bad.status == "mismatch" and bad.score is None and not bad.available
    assert apply_price_guard(ok, 1e-05).status == "mismatch"    # ratio 0.41
    assert apply_price_guard(ok, None).status == "ok"           # --address: no search price
    na = SocialSignal("no_sentiment", "PEPE", price_usd=1.0)
    assert apply_price_guard(na, 5.0) is na
