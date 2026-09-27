"""Nansen MCP client: token resolution, argument shapes, result conversion, errors."""

import asyncio
import json

import httpx
import pytest
from mcp.shared.exceptions import McpError
from mcp.types import CallToolResult, ErrorData, TextContent

from tests.conftest import FAKE_KEY, FakeNansenClient, fixture_text, ok, tool_error
from zalat.config import Settings
from zalat.errors import (
    NansenAuthError,
    NansenNetworkError,
    NansenProtocolError,
    classify_exception,
)
from zalat.nansen_mcp import (
    SMART_LABELS,
    NansenMCPClient,
    TokenRef,
    get_flows,
    get_who_bought_sold,
    parse_search_candidates,
    resolve_token,
    tool_result_from_mcp,
)

PEPE = "0x6982508145454ce325ddbe47a25d4ec3d2311933"


def run(coro):
    return asyncio.run(coro)


def test_resolve_token_real_sample():
    fake = FakeNansenClient({"general_search": ok("general_search", fixture_text("search_pepe.json"))})
    token, res = run(resolve_token(fake, "pepe", "ethereum"))
    assert res.ok
    assert token is not None
    assert (token.symbol, token.address, token.chain) == ("PEPE", PEPE, "ethereum")
    assert token.volume_24h == pytest.approx(1.2e6)
    tool, args = fake.calls[0]
    assert tool == "general_search"
    # general_search takes FLAT arguments (no "request" wrapper).
    assert args == {"query": "pepe", "result_type": "token", "max_results": 10, "chain": "ethereum"}


def test_resolve_token_no_exact_match_and_wrong_chain():
    fake = FakeNansenClient({"general_search": ok("general_search", fixture_text("search_pepe.json"))})
    assert run(resolve_token(fake, "PEP", "ethereum"))[0] is None
    assert run(resolve_token(fake, "PEPE", "base"))[0] is None


def test_resolve_token_picks_highest_volume():
    md = ("| Name | Symbol | Contract Address | Chain | Volume 24h USD |\n|--|--|--|--|--|\n"
          "| Fake | ABC | 0xlow | ethereum | 10k |\n| Real | ABC | 0xhigh | ethereum | 5M |\n")
    fake = FakeNansenClient({"general_search": ok("general_search", json.dumps({"result": md}))})
    token, _ = run(resolve_token(fake, "ABC", "ethereum"))
    assert token.address == "0xhigh"


def test_resolve_token_tool_error():
    fake = FakeNansenClient({"general_search": tool_error("general_search")})
    token, res = run(resolve_token(fake, "PEPE", "ethereum"))
    assert token is None and not res.ok and res.reason == "unclassified_failure"


def test_parse_search_candidates_count():
    assert len(parse_search_candidates(fixture_text("search_pepe.json"))) == 3


def test_data_tool_argument_shapes():
    fake = FakeNansenClient()
    tok = TokenRef("PEPE", "Pepe", PEPE, "ethereum")
    run(get_flows(fake, tok, "1h"))
    run(get_who_bought_sold(fake, tok, "BUY", "1d"))
    run(get_who_bought_sold(fake, tok, "SELL", "7d"))
    (t1, a1), (t2, a2), (t3, a3) = fake.calls
    assert t1 == "token_recent_flows_summary"
    assert a1 == {"request": {"chain": "ethereum", "tokenAddress": PEPE,
                              "lookbackPeriod": "1h", "mode": "onchain_tokens"}}
    assert t2 == t3 == "token_who_bought_sold"
    assert a2["request"]["buy_or_sell"] == "BUY"
    assert a2["request"]["time_range"] == {"from": "1D_AGO", "to": "NOW"}
    assert a2["request"]["include_labels"] == SMART_LABELS
    assert a3["request"]["time_range"] == {"from": "7D_AGO", "to": "NOW"}


# ---- CallToolResult conversion -------------------------------------------------
def test_tool_result_ok_text():
    r = tool_result_from_mcp("x", CallToolResult(content=[TextContent(type="text", text="hi")]))
    assert r.ok and r.text == "hi"


def test_tool_result_is_error():
    r = tool_result_from_mcp("x", CallToolResult(
        content=[TextContent(type="text", text="NANSEN_TOOL_ERROR reason: unclassified_failure")],
        isError=True))
    assert not r.ok and r.error_kind == "tool_error" and r.reason == "unclassified_failure"


def test_tool_result_error_text_without_flag_and_auth():
    r = tool_result_from_mcp("x", CallToolResult(
        content=[TextContent(type="text", text="NANSEN_TOOL_ERROR: Unauthorized - invalid API key")]))
    assert not r.ok and r.error_kind == "auth"


def test_tool_result_structured_only_and_empty():
    r = tool_result_from_mcp("x", CallToolResult(content=[], structuredContent={"data": [{"a": 1}]}))
    assert r.ok and json.loads(r.text) == {"data": [{"a": 1}]}
    e = tool_result_from_mcp("x", CallToolResult(content=[]))
    assert not e.ok and e.error_kind == "protocol"


# ---- classify_exception ------------------------------------------------------
def _status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://mcp.example/")
    return httpx.HTTPStatusError("x", request=req, response=httpx.Response(code, request=req))


def test_classify_exception_groups():
    grp = ExceptionGroup("tg", [ExceptionGroup("inner", [_status_error(401)])])
    assert isinstance(classify_exception(grp), NansenAuthError)
    assert isinstance(classify_exception(_status_error(403)), NansenAuthError)
    assert isinstance(classify_exception(_status_error(502)), NansenNetworkError)
    err = classify_exception(ExceptionGroup("tg", [httpx.ConnectError(f"boom {FAKE_KEY}")]), [FAKE_KEY])
    assert isinstance(err, NansenNetworkError) and FAKE_KEY not in str(err)
    assert isinstance(classify_exception(TimeoutError()), NansenNetworkError)
    assert isinstance(classify_exception(McpError(ErrorData(code=-1, message="Unauthorized"))),
                      NansenAuthError)
    assert isinstance(classify_exception(McpError(ErrorData(code=-1, message="bad params"))),
                      NansenProtocolError)
    assert isinstance(classify_exception(ValueError("?")), NansenProtocolError)


# ---- the real client against an in-process fake MCP server (httpx.MockTransport) --
def _fake_mcp_server(seen: list, call_result: dict | None = None, status: int = 200):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if status != 200:
            return httpx.Response(status, json={"error": "unauthorized"})
        if req.method != "POST":
            return httpx.Response(405 if req.method == "GET" else 200)
        msg = json.loads(req.content)
        if "id" not in msg:
            return httpx.Response(202)
        if msg["method"] == "initialize":
            res = {"protocolVersion": msg["params"]["protocolVersion"], "capabilities": {"tools": {}},
                   "serverInfo": {"name": "fake-nansen", "version": "0"}}
        elif msg["method"] == "tools/call":
            res = call_result or {"content": [{"type": "text", "text": "ok"}], "isError": False}
        else:
            res = {"tools": []}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": msg["id"], "result": res},
                              headers={"mcp-session-id": "s1"})
    return httpx.MockTransport(handler)


def _settings(**kw):
    return Settings(api_key=FAKE_KEY, mcp_url="https://mcp.example/ra/mcp/", timeout=3, **kw)


def test_real_client_happy_path_sends_key_only_in_header():
    seen: list[httpx.Request] = []

    async def go():
        async with NansenMCPClient(_settings(), transport=_fake_mcp_server(seen)) as c:
            return await c.call("general_search", {"query": "PEPE"})

    res = run(go())
    assert res.ok and res.text == "ok"
    assert seen and all(r.headers.get("NANSEN-API-KEY") == FAKE_KEY for r in seen)
    assert all(FAKE_KEY not in str(r.url) for r in seen)


def test_real_client_custom_header():
    seen: list[httpx.Request] = []

    async def go():
        async with NansenMCPClient(_settings(key_header="X-Api-Key"),
                                   transport=_fake_mcp_server(seen)) as c:
            await c.call("t", {})

    run(go())
    assert all(r.headers.get("X-Api-Key") == FAKE_KEY for r in seen)


def test_real_client_tool_error_does_not_raise():
    seen: list = []
    err = {"content": [{"type": "text", "text": "NANSEN_TOOL_ERROR reason: unclassified_failure"}],
           "isError": True}

    async def go():
        async with NansenMCPClient(_settings(), transport=_fake_mcp_server(seen, err)) as c:
            return await c.call("token_info", {"request": {}})

    res = run(go())
    assert not res.ok and res.reason == "unclassified_failure"


@pytest.mark.parametrize("status, exc", [(401, NansenAuthError), (403, NansenAuthError),
                                         (500, NansenNetworkError)])
def test_real_client_http_errors_on_connect(status, exc):
    async def go():
        async with NansenMCPClient(_settings(), transport=_fake_mcp_server([], status=status)):
            pass

    with pytest.raises(exc) as info:
        run(go())
    assert FAKE_KEY not in str(info.value)


def test_real_client_unreachable():
    def refuse(req):
        raise httpx.ConnectError(f"refused {FAKE_KEY}")

    async def go():
        async with NansenMCPClient(_settings(), transport=httpx.MockTransport(refuse)):
            pass

    with pytest.raises(NansenNetworkError) as info:
        run(go())
    assert FAKE_KEY not in str(info.value)


def test_real_client_requires_context_manager():
    with pytest.raises(RuntimeError):
        run(NansenMCPClient(_settings()).call("x", {}))
