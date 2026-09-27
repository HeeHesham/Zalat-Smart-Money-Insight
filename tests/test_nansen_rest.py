"""Nansen REST client (default backend): request mapping, headers, metadata, errors."""

import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest

from tests.conftest import FAKE_KEY, fixture_text
from zalat.config import Settings
from zalat.errors import NansenAuthError
from zalat.nansen_mcp import (
    NansenMCPClient,
    TokenRef,
    flows_args,
    search_args,
    token_info_args,
    token_ohlcv_args,
    who_bought_sold_args,
)
from zalat.nansen_rest import (
    AUTH_MESSAGE,
    REST_SMART_LABELS,
    NansenRESTClient,
    make_client,
    rest_request,
)

PEPE = TokenRef("PEPE", "Pepe", "0x6982508145454ce325ddbe47a25d4ec3d2311933", "ethereum")
NOW = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
HEADERS = {"X-Request-Id": "req-abc123", "X-Nansen-Credits-Cost": "1",
           "X-Nansen-Credits-Remaining": "28090", "Ratelimit-Remaining": "149"}


def settings(key=FAKE_KEY, **kw):
    return Settings(api_key=key, rest_url="https://api.nansen.example/api/v1", timeout=5, **kw)


# ---- request mapping ---------------------------------------------------------------------
def test_rest_request_mapping():
    assert rest_request("general_search", search_args("PEPE", "ethereum")) == \
        ("search/general", {"search_query": "PEPE"})
    assert rest_request("token_recent_flows_summary", flows_args(PEPE, "7d")) == (
        "tgm/flow-intelligence",
        {"chain": "ethereum", "token_address": PEPE.address, "timeframe": "7d"})
    assert rest_request("token_info", token_info_args(PEPE)) == (
        "tgm/token-information", {"chain": "ethereum", "token_address": PEPE.address,
                                  "timeframe": "1d"})
    assert rest_request("token_ohlcv", token_ohlcv_args(PEPE)) == (
        "tgm/token-ohlcv", {"chain": "ethereum", "token_address": PEPE.address, "timeframe": "1d"})
    with pytest.raises(KeyError):
        rest_request("token_quant_scores", {})


@pytest.mark.parametrize("period, frm", [("1d", "2026-09-26 12:00:00"), ("1h", "2026-09-26 12:00:00"),
                                         ("7d", "2026-09-20 12:00:00")])
def test_who_bought_sold_body(period, frm):
    path, body = rest_request("token_who_bought_sold", who_bought_sold_args(PEPE, "SELL", period), NOW)
    assert path == "tgm/who-bought-sold"
    assert body == {
        "token_address": PEPE.address, "buy_or_sell": "SELL",
        "date": {"from": frm, "to": "2026-09-27 12:00:00"}, "chain": "ethereum",
        "filters": {"include_smart_money_labels": REST_SMART_LABELS,
                    "trade_volume_usd": {"min": 10}},
        "order_by": [{"field": "token_trade_volume", "direction": "DESC"}],
        "pagination": {"page": 1, "per_page": 100},
    }


# ---- client against httpx.MockTransport ----------------------------------------------
def _run(handler, key=FAKE_KEY, tool="general_search", args=None, sleeps=None):
    seen = []

    def wrapped(req):
        seen.append(req)
        return handler(req)

    async def fake_sleep(s):
        if sleeps is not None:
            sleeps.append(s)

    async def go():
        async with NansenRESTClient(settings(key), transport=httpx.MockTransport(wrapped),
                                    sleep=fake_sleep) as c:
            return await c.call(tool, args or search_args("PEPE", "ethereum"))
    return asyncio.run(go()), seen


def test_ok_call_captures_metadata_and_sends_key_header():
    res, seen = _run(lambda r: httpx.Response(200, text=fixture_text("real_search.json"),
                                              headers=HEADERS))
    assert res.ok and json.loads(res.text)["tokens"][1]["symbol"] == "PEPE"
    assert (res.http_status, res.request_id, res.credits_cost, res.credits_remaining,
            res.ratelimit_remaining) == (200, "req-abc123", 1.0, 28090.0, 149)
    (req,) = seen
    assert req.method == "POST" and str(req.url) == "https://api.nansen.example/api/v1/search/general"
    assert json.loads(req.content) == {"search_query": "PEPE"}
    assert req.headers["apiKey"] == FAKE_KEY and FAKE_KEY not in str(req.url)


def test_no_key_sends_no_key_header():
    res, seen = _run(lambda r: httpx.Response(200, json={"tokens": []}), key="")
    assert res.ok
    assert "apikey" not in {k.lower() for k in seen[0].headers.keys()}
    assert "nansen-api-key" not in {k.lower() for k in seen[0].headers.keys()}


def test_custom_key_header():
    async def go():
        seen = []
        tr = httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200, json={}))
        async with NansenRESTClient(settings(rest_key_header="X-Key"), transport=tr) as c:
            await c.call("general_search", search_args("PEPE", None))
        return seen
    assert asyncio.run(go())[0].headers["X-Key"] == FAKE_KEY


@pytest.mark.parametrize("code", [401, 403])
def test_auth_errors_raise_with_request_id(code):
    body = {"error": "unauthorized", "message": f"Invalid API key {FAKE_KEY}", "code": "INVALID_KEY",
            "status": code, "request_id": "req-err-1"}
    with pytest.raises(NansenAuthError) as info:
        _run(lambda r: httpx.Response(code, json=body))
    msg = str(info.value)
    assert msg == (f"Nansen rejected the request (HTTP {code}, request_id req-err-1): "
                   "check NANSEN_API_KEY in .env (missing or invalid)")
    assert FAKE_KEY not in msg


def test_http_error_body_request_id_and_reason():
    body = {"error": "bad_request", "message": "invalid chain", "code": "INVALID_CHAIN",
            "status": 422, "request_id": "req-422"}
    res, _ = _run(lambda r: httpx.Response(422, json=body))
    assert not res.ok and res.error_kind == "tool_error" and res.reason == "INVALID_CHAIN"
    assert res.request_id == "req-422" and res.http_status == 422
    res5, _ = _run(lambda r: httpx.Response(503, text="upstream down", headers=HEADERS))
    assert res5.error_kind == "network" and res5.reason == "http_503" and res5.request_id == "req-abc123"


def test_429_retries_honouring_retry_after():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(429, json={"error": "rate limited"},
                                  headers={"Retry-After": "2"} if calls["n"] == 1
                                  else {"Ratelimit-Reset": "1"})
        return httpx.Response(200, json={"tokens": []}, headers=HEADERS)

    sleeps = []
    res, seen = _run(handler, sleeps=sleeps)
    assert res.ok and res.retries == 2 and len(seen) == 3
    assert sleeps == [2.0, 1.0]


def test_429_exhausted_is_rate_limited():
    sleeps = []
    res, seen = _run(lambda r: httpx.Response(429, json={"request_id": "req-429"}), sleeps=sleeps)
    assert not res.ok and res.error_kind == "rate_limited" and res.retries == 3
    assert len(seen) == 4 and res.request_id == "req-429" and len(sleeps) == 3


def test_transport_error_and_timeout_and_unknown_tool():
    def refuse(req):
        raise httpx.ConnectError(f"refused {FAKE_KEY}")
    res, _ = _run(refuse)
    assert not res.ok and res.error_kind == "network" and FAKE_KEY not in res.text

    def slow(req):
        raise httpx.ReadTimeout("slow")
    assert _run(slow)[0].error_kind == "timeout"
    res3, seen = _run(lambda r: httpx.Response(200), tool="token_quant_scores", args={})
    assert res3.reason == "unknown_tool" and seen == []


def test_key_in_response_is_redacted():
    res, _ = _run(lambda r: httpx.Response(200, text=f'{{"echo": "{FAKE_KEY}"}}'))
    assert FAKE_KEY not in res.text and "***" in res.text


def test_default_transport_is_blocked_offline():
    async def go():
        async with NansenRESTClient(settings()) as c:
            return await c.call("general_search", search_args("PEPE", None))
    res = asyncio.run(go())
    assert not res.ok and res.error_kind == "network"


def test_requires_context_manager():
    with pytest.raises(RuntimeError):
        asyncio.run(NansenRESTClient(settings()).call("general_search", {"query": "x"}))


def test_make_client_backend_switch():
    assert isinstance(make_client(settings()), NansenRESTClient)
    assert isinstance(make_client(settings(backend="mcp")), NansenMCPClient)


def test_auth_message_variants():
    from zalat.nansen_rest import auth_message

    assert AUTH_MESSAGE == "Nansen rejected the request: check NANSEN_API_KEY in .env (missing or invalid)"
    assert auth_message(403) == ("Nansen rejected the request (HTTP 403): check NANSEN_API_KEY in .env "
                                 "(missing or invalid)")


def _wbs_page(page, n, last):
    rows = [{"address": f"0x{page:02d}{i:038d}", "bought_volume_usd": 10.0, "sold_volume_usd": 1.0}
            for i in range(n)]
    return {"data": rows, "pagination": {"page": page, "per_page": 100, "is_last_page": last}}


def _paged(pages_total, fail_on=None):
    bodies = []

    def handler(req):
        body = json.loads(req.content)
        bodies.append(body)
        page = body["pagination"]["page"]
        if page == fail_on:
            return httpx.Response(500, text="boom", headers={"X-Request-Id": f"req-p{page}"})
        hdr = {"X-Request-Id": f"req-p{page}", "X-Nansen-Credits-Cost": "1",
               "X-Nansen-Credits-Remaining": str(1000 - page)}
        return httpx.Response(200, json=_wbs_page(page, 100, page >= pages_total), headers=hdr)
    return handler, bodies


def test_who_bought_sold_fetches_more_pages():
    handler, bodies = _paged(3)
    res, _ = _run(handler, tool="token_who_bought_sold",
                  args=who_bought_sold_args(PEPE, "BUY", "1d"))
    data = json.loads(res.text)
    assert [b["pagination"]["page"] for b in bodies] == [1, 2, 3]
    assert len(data["data"]) == 300 and data["truncated"] is False
    assert data["request_ids"] == ["req-p1", "req-p2", "req-p3"]
    assert res.request_id == "req-p1" and res.credits_cost == 3 and res.credits_remaining == 997


def test_who_bought_sold_stops_at_four_pages_and_marks_truncated():
    from zalat.parsing import extract_buy_sell, is_truncated

    handler, bodies = _paged(10)
    res, _ = _run(handler, tool="token_who_bought_sold",
                  args=who_bought_sold_args(PEPE, "SELL", "1d"))
    data = json.loads(res.text)
    assert len(bodies) == 4 and len(data["data"]) == 400 and data["truncated"] is True
    assert is_truncated(res.text)
    buy, _ = extract_buy_sell(res.text, json.dumps({"data": []}))
    assert buy.wallets == 400


def test_who_bought_sold_page_failure_keeps_what_it_has():
    handler, bodies = _paged(5, fail_on=2)
    res, _ = _run(handler, tool="token_who_bought_sold",
                  args=who_bought_sold_args(PEPE, "BUY", "1d"))
    data = json.loads(res.text)
    assert res.ok and len(data["data"]) == 100 and data["truncated"] is True
    assert data["request_ids"] == ["req-p1", "req-p2"]


def test_single_page_reply_is_kept_verbatim():
    raw = fixture_text("real_wbs_buy.json")
    res, seen = _run(lambda r: httpx.Response(200, text=raw), tool="token_who_bought_sold",
                     args=who_bought_sold_args(PEPE, "BUY", "1d"))
    assert res.text == raw and len(seen) == 1
