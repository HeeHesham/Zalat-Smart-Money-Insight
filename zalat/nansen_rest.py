"""Nansen REST client (default backend): https://api.nansen.ai/api/v1.

It implements the same ``NansenClient`` protocol as the MCP client
(``await client.call(tool, arguments) -> ToolResult``) and accepts the same
MCP-style arguments built in :mod:`zalat.nansen_mcp`, translating them to REST
request bodies. So the CLI and the stress test don't care which backend runs.

Tool -> endpoint (all ``POST``, JSON body):

=============================  ==========================
``general_search``             ``search/general``
``token_recent_flows_summary`` ``tgm/flow-intelligence``
``token_who_bought_sold``      ``tgm/who-bought-sold``
``token_info``                 ``tgm/token-information``
``token_ohlcv``                ``tgm/token-ohlcv``
=============================  ==========================

Key handling: the key goes in the ``apiKey`` header (``NANSEN_API_KEY_HEADER``
overrides). The key is OPTIONAL here: without one no key header is sent, which
supports setups where a proxy injects the credential. HTTP 401/403 raises
:class:`NansenAuthError` (exit code 4).

Every result carries Nansen's ``X-Request-Id`` (or the error body's
``request_id``) plus credit and rate-limit headers, so failures can be
reported to Nansen support. HTTP 429 is retried, honouring ``Retry-After`` /
``Ratelimit-Reset``.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import httpx

from zalat.config import Settings, redact
from zalat.errors import NansenAuthError, classify_exception
from zalat.nansen_mcp import NansenMCPClient, ToolResult

ENDPOINTS = {
    "general_search": "search/general",
    "token_recent_flows_summary": "tgm/flow-intelligence",
    "token_who_bought_sold": "tgm/who-bought-sold",
    "token_info": "tgm/token-information",
    "token_ohlcv": "tgm/token-ohlcv",
}

#: Smart-money labels accepted by the REST who-bought-sold filter.
REST_SMART_LABELS = ["30D Smart Trader", "90D Smart Trader", "180D Smart Trader",
                     "Smart Trader", "Fund"]
#: Ignore dust trades below this USD size in who-bought-sold.
MIN_TRADE_USD = 10
MAX_429_RETRIES = 3
MAX_RETRY_WAIT_S = 30.0

AUTH_MESSAGE = "Nansen rejected the request: set NANSEN_API_KEY in .env"


def _date_window(time_range: dict | None, now: datetime | None = None) -> dict[str, str]:
    """MCP-style ``{"from": "7D_AGO", "to": "NOW"}`` -> REST datetime strings (UTC)."""
    now = now or datetime.now(timezone.utc)
    frm = (time_range or {}).get("from", "1D_AGO")
    days = 7 if str(frm).upper().startswith("7D") else 1
    fmt = "%Y-%m-%d %H:%M:%S"
    return {"from": (now - timedelta(days=days)).strftime(fmt), "to": now.strftime(fmt)}


def rest_request(tool: str, arguments: dict, now: datetime | None = None) -> tuple[str, dict]:
    """Translate an MCP-style call into ``(endpoint path, JSON body)``.

    Raises ``KeyError`` for tools that have no REST endpoint.
    """
    path = ENDPOINTS[tool]
    req = arguments.get("request", arguments)
    if tool == "general_search":
        return path, {"search_query": arguments["query"]}
    if tool == "token_recent_flows_summary":
        return path, {"chain": req["chain"], "token_address": req["tokenAddress"],
                      "timeframe": req.get("lookbackPeriod", "1d")}
    if tool == "token_who_bought_sold":
        return path, {
            "token_address": req["tokenAddress"],
            "buy_or_sell": req["buy_or_sell"],
            "date": _date_window(req.get("time_range"), now),
            "chain": req["chain"],
            "filters": {"include_smart_money_labels": list(REST_SMART_LABELS),
                        "trade_volume_usd": {"min": MIN_TRADE_USD}},
            "order_by": [{"field": "token_trade_volume", "direction": "DESC"}],
            "pagination": {"page": 1, "per_page": 25},
        }
    # token_info / token_ohlcv
    return path, {"chain": req["chain"], "token_address": req["tokenAddress"],
                  "timeframe": req.get("timeframe", "1d")}


def _num(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def _retry_after(resp: httpx.Response, attempt: int) -> float:
    """Seconds to wait after a 429: Retry-After, else Ratelimit-Reset, else backoff."""
    for h in ("Retry-After", "Ratelimit-Reset", "X-Ratelimit-Reset"):
        v = _num(resp.headers.get(h))
        if v is not None and v >= 0:
            return min(max(v, 0.5), MAX_RETRY_WAIT_S)
    return min(2.0 ** attempt, MAX_RETRY_WAIT_S)


class NansenRESTClient:
    """Async REST client; one ``httpx.AsyncClient`` for all calls of a run."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None,
                 sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep) -> None:
        # ``transport`` / ``sleep`` are injectable for tests.
        self.settings = settings
        self._transport = transport
        self._sleep = sleep
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "NansenRESTClient":
        s = self.settings
        headers = {"Accept": "application/json", "User-Agent": "zalat-smart-money-verdict"}
        if s.api_key:  # optional: without a key we send no key header at all
            headers[s.rest_key_header] = s.api_key
        self._http = httpx.AsyncClient(
            base_url=s.rest_url.rstrip("/") + "/", headers=headers,
            timeout=httpx.Timeout(s.timeout, read=s.timeout * 2), transport=self._transport,
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _meta(self, res: ToolResult, resp: httpx.Response) -> ToolResult:
        h = resp.headers
        res.http_status = resp.status_code
        res.request_id = h.get("X-Request-Id") or res.request_id
        res.credits_cost = _num(h.get("X-Nansen-Credits-Cost"))
        res.credits_remaining = _num(h.get("X-Nansen-Credits-Remaining"))
        rl = _num(h.get("Ratelimit-Remaining") or h.get("X-Ratelimit-Remaining"))
        res.ratelimit_remaining = int(rl) if rl is not None else None
        return res

    async def call(self, tool: str, arguments: dict) -> ToolResult:
        """Call one endpoint. Raises only :class:`NansenAuthError` (401/403)."""
        if self._http is None:
            raise RuntimeError("NansenRESTClient used outside 'async with'")
        secrets = self.settings.secrets()
        try:
            path, body = rest_request(tool, arguments)
        except KeyError as exc:
            return ToolResult(tool, False, f"no REST endpoint for {tool} ({exc})", False,
                              "protocol", reason="unknown_tool")

        start = time.perf_counter()
        retries = 0
        while True:
            try:
                resp = await self._http.post(path, json=body)
            except (httpx.TimeoutException, asyncio.TimeoutError):
                ms = (time.perf_counter() - start) * 1000
                return ToolResult(tool, False, "timeout", False, "timeout", None, ms, "timeout",
                                  retries=retries)
            except Exception as exc:  # noqa: BLE001 - network problems become a result
                ms = (time.perf_counter() - start) * 1000
                err = classify_exception(exc, secrets)
                return ToolResult(tool, False, str(err), False, "network", None, ms, "network",
                                  retries=retries)
            if resp.status_code == 429 and retries < MAX_429_RETRIES:
                wait = _retry_after(resp, retries)
                retries += 1
                await self._sleep(wait)
                continue
            break

        ms = (time.perf_counter() - start) * 1000
        text = redact(resp.text, secrets)
        code = resp.status_code
        res = ToolResult(tool, 200 <= code < 300, text, False, None, None, ms, None,
                         retries=retries)
        self._meta(res, resp)
        if res.ok:
            return res

        # Error bodies look like {"error","message","code","status","request_id","doc_url"}.
        try:
            err_body = json.loads(resp.text)
        except ValueError:
            err_body = {}
        if isinstance(err_body, dict):
            res.request_id = res.request_id or err_body.get("request_id")
            reason = err_body.get("code") or err_body.get("error")
        else:
            reason = None
        res.is_error = True
        res.reason = str(reason or f"http_{code}")
        if code in (401, 403):
            rid = f", request_id {res.request_id}" if res.request_id else ""
            raise NansenAuthError(f"{AUTH_MESSAGE} (HTTP {code}{rid})")
        if code == 429:
            res.error_kind = "rate_limited"
        elif code >= 500:
            res.error_kind = "network"
        else:
            res.error_kind = "tool_error"
        return res


def make_client(settings: Settings) -> Any:
    """The Nansen client for ``settings.backend`` ("rest" default, or "mcp")."""
    if settings.backend == "mcp":
        return NansenMCPClient(settings)
    return NansenRESTClient(settings)
