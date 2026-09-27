"""Nansen MCP client and tool wrappers.

We talk to Nansen's remote MCP server over *streamable HTTP* using the
official ``mcp`` Python SDK (pinned to 1.x). One :class:`NansenMCPClient`
holds one MCP session for all calls of a run.

Tool-level failures (``isError=True``, ``NANSEN_TOOL_ERROR`` text, timeouts,
JSON-RPC errors) never raise: they come back as a :class:`ToolResult` with
``ok=False`` so the verdict can still be rendered with that signal missing.
Only a rejected API key raises (:class:`NansenAuthError`), because nothing
else can work after that.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal, Protocol

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from zalat.config import Settings, redact
from zalat.errors import (
    AUTH_RE,
    NansenAuthError,
    NansenNetworkError,
    classify_exception,
)
from zalat.parsing import find_col, parse_number, records_from, unwrap_payload

LOOKBACK = ("5m", "1h", "6h", "12h", "1d", "7d")
SMART_LABELS = [
    "30D Smart Trader",
    "90D Smart Trader",
    "180D Smart Trader",
    "All Time Smart Trader",
    "Fund",
]
_REASON_RE = re.compile(r"reason:\s*([A-Za-z0-9_\-]+)", re.I)


@dataclass
class ToolResult:
    """Outcome of one Nansen tool call (MCP or REST; success or failure)."""

    tool: str
    ok: bool
    text: str
    is_error: bool = False
    #: "tool_error" | "auth" | "network" | "timeout" | "protocol" | "rate_limited" | None
    error_kind: str | None = None
    structured: dict | None = None
    latency_ms: float = 0.0
    #: Short machine reason, e.g. "unclassified_failure" from NANSEN_TOOL_ERROR.
    reason: str | None = None
    # --- REST metadata (None for the MCP backend) ---
    http_status: int | None = None
    #: Nansen's X-Request-Id (or the error body's request_id): quote it to support.
    request_id: str | None = None
    credits_cost: float | None = None
    credits_remaining: float | None = None
    ratelimit_remaining: int | None = None
    #: How many times a 429 was retried before this result.
    retries: int = 0


class NansenClient(Protocol):
    """Anything that can call a Nansen tool (MCP client, REST client or a test fake)."""

    async def call(self, tool: str, arguments: dict) -> ToolResult: ...


def tool_result_from_mcp(tool: str, result: Any, latency_ms: float = 0.0) -> ToolResult:
    """Convert an ``mcp.types.CallToolResult`` into our :class:`ToolResult`."""
    texts = [
        getattr(block, "text", "")
        for block in (getattr(result, "content", None) or [])
        if getattr(block, "type", None) == "text"
    ]
    text = "\n".join(t for t in texts if t)
    structured = getattr(result, "structuredContent", None)
    if not text and structured:
        text = json.dumps(structured, ensure_ascii=False)
    is_error = bool(getattr(result, "isError", False))

    if is_error or "NANSEN_TOOL_ERROR" in text:
        m = _REASON_RE.search(text)
        kind = "auth" if AUTH_RE.search(text) else "tool_error"
        return ToolResult(tool, False, text, True, kind, structured, latency_ms,
                          m.group(1) if m else ("auth" if kind == "auth" else "tool_error"))
    if not text:
        return ToolResult(tool, False, "", False, "protocol", structured, latency_ms, "empty_response")
    return ToolResult(tool, True, text, False, None, structured, latency_ms)


class NansenMCPClient:
    """Real client: one streamable-HTTP MCP session to Nansen.

    Usage::

        async with NansenMCPClient(settings) as nc:
            res = await nc.call("general_search", {...})
    """

    def __init__(self, settings: Settings,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        # ``transport`` is only for tests (e.g. ``httpx.MockTransport``).
        self.settings = settings
        self._transport = transport
        self._stack: AsyncExitStack | None = None
        self._session: Any = None

    async def __aenter__(self) -> "NansenMCPClient":
        s = self.settings
        stack = AsyncExitStack()
        try:
            # The key lives ONLY in this headers dict; it never goes into the URL.
            http = await stack.enter_async_context(
                httpx.AsyncClient(
                    headers={s.key_header: s.api_key},
                    timeout=httpx.Timeout(s.timeout, read=s.timeout * 4),
                    follow_redirects=True,
                    transport=self._transport,
                )
            )
            read, write, _ = await stack.enter_async_context(
                streamable_http_client(s.mcp_url, http_client=http)
            )
            session = await stack.enter_async_context(
                ClientSession(read, write, read_timeout_seconds=timedelta(seconds=s.timeout * 4))
            )
            await asyncio.wait_for(session.initialize(), timeout=s.timeout)
        except BaseException as exc:  # noqa: BLE001 - we re-raise a classified error
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                await _quiet_close(stack)
                raise
            # When the transport fails (401, connection refused...), anyio
            # cancels this task, so ``exc`` is often just a CancelledError and
            # the real cause is raised while closing the stack. Prefer that.
            cause: BaseException = exc
            try:
                await stack.aclose()
            except BaseException as close_exc:  # noqa: BLE001
                if isinstance(exc, asyncio.CancelledError):
                    cause = close_exc
            err = classify_exception(cause, [s.api_key])
            if isinstance(err, NansenAuthError):
                raise err from None
            raise NansenNetworkError(str(err)) from None
        self._stack, self._session = stack, session
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        stack, self._stack, self._session = self._stack, None, None
        if stack is None:
            return
        try:
            await stack.aclose()
        except BaseException as close_exc:  # noqa: BLE001
            # If the transport's task group died mid-session (e.g. HTTP 401 on a
            # later request), anyio cancels us and the real cause only shows up
            # here. Surface it instead of a bare CancelledError.
            if exc_type is not None and issubclass(exc_type, asyncio.CancelledError):
                err = classify_exception(close_exc, [self.settings.api_key])
                if isinstance(err, NansenAuthError):
                    raise err from None
                raise NansenNetworkError(str(err)) from None
            # Otherwise cleanup noise must not mask the real outcome.

    async def call(self, tool: str, arguments: dict) -> ToolResult:
        """Call one tool. Raises only :class:`NansenAuthError`."""
        if self._session is None:
            raise RuntimeError("NansenMCPClient used outside 'async with'")
        timeout = self.settings.timeout * 4
        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                self._session.call_tool(tool, arguments,
                                        read_timeout_seconds=timedelta(seconds=timeout)),
                timeout=timeout + 5,
            )
        except (asyncio.TimeoutError, TimeoutError):
            ms = (time.perf_counter() - start) * 1000
            return ToolResult(tool, False, "timeout", False, "timeout", None, ms, "timeout")
        except Exception as exc:  # noqa: BLE001 - classified below
            ms = (time.perf_counter() - start) * 1000
            err = classify_exception(exc, [self.settings.api_key])
            if isinstance(err, NansenAuthError):
                raise err from None
            kind = "network" if isinstance(err, NansenNetworkError) else "protocol"
            return ToolResult(tool, False, str(err), False, kind, None, ms, kind)
        ms = (time.perf_counter() - start) * 1000
        res = tool_result_from_mcp(tool, result, ms)
        res.text = redact(res.text, [self.settings.api_key])
        return res


async def _quiet_close(stack: AsyncExitStack) -> None:
    try:
        await stack.aclose()
    except BaseException:  # noqa: BLE001 - cleanup errors are secondary
        pass


# --------------------------------------------------------------------------- #
# Tool wrappers
# --------------------------------------------------------------------------- #
@dataclass
class TokenRef:
    """A resolved token."""

    symbol: str
    name: str
    address: str
    chain: str
    volume_24h: float | None = None
    #: Live price from the search result ("Price USD"), if present.
    price_usd: float | None = None
    #: Market cap from the search result, if present (used to pick the canonical
    #: listing when the same asset is bridged to several chains).
    market_cap_usd: float | None = None


def search_args(symbol: str, chain: str | None, max_results: int = 10) -> dict:
    """Arguments for ``general_search`` (flat, not wrapped in ``request``)."""
    args: dict[str, Any] = {"query": symbol, "result_type": "token", "max_results": max_results}
    if chain:
        args["chain"] = chain
    return args


def flows_args(token: TokenRef, period: str) -> dict:
    """Arguments for ``token_recent_flows_summary``."""
    return {"request": {"chain": token.chain, "tokenAddress": token.address,
                        "lookbackPeriod": period, "mode": "onchain_tokens"}}


def who_bought_sold_args(token: TokenRef, side: str, period: str) -> dict:
    """Arguments for ``token_who_bought_sold``.

    The tool only takes coarse day ranges, so any lookback up to 1d maps to
    the last day and 7d maps to the last week.
    """
    frm = "7D_AGO" if period == "7d" else "1D_AGO"
    return {"request": {"chain": token.chain, "tokenAddress": token.address,
                        "buy_or_sell": side, "include_labels": list(SMART_LABELS),
                        "time_range": {"from": frm, "to": "NOW"}}}


#: Search results on these "chains" are perp markets, not token contracts.
NON_TOKEN_CHAINS = {"hyperliquid"}
_EVM_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
_B58_ADDR = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,48}$")          # Solana etc.
_OTHER_ADDR = re.compile(r"^[A-Za-z0-9:_\-\.]{20,120}$")          # TON, Sui, NEAR...


def looks_like_address(addr: str) -> bool:
    """True for something that looks like a token contract / mint address."""
    return bool(_EVM_ADDR.match(addr) or _B58_ADDR.match(addr) or _OTHER_ADDR.match(addr))


def parse_search_candidates(text: str, default_chain: str | None = None) -> list[TokenRef]:
    """Parse every token row from a ``general_search`` response."""
    # records_from() already flattens every markdown table in the text.
    rows = records_from(unwrap_payload(text))
    out: list[TokenRef] = []
    for r in rows:
        cols = list(r.keys())
        sym_c = find_col(cols, [["symbol"], ["ticker"]])
        addr_c = find_col(cols, [["contract", "address"], ["token", "address"], ["address"]])
        name_c = find_col(cols, [["name"]], exclude=["symbol"])
        chain_c = find_col(cols, [["chain"], ["network"]])
        vol_c = find_col(cols, [["volume", "24"], ["volume"]])
        price_c = find_col(cols, [["price", "usd"], ["price"]],
                           exclude=["change", "pct", "percent", "volume"])
        mcap_c = find_col(cols, [["market", "cap"], ["mcap"]])
        if not sym_c or not addr_c or not r.get(addr_c):
            continue
        chain = (str(r.get(chain_c, "")).strip().lower() if chain_c else "") or (default_chain or "")
        address = str(r.get(addr_c, "")).strip()
        # Perp markets (e.g. Hyperliquid "kPEPE") are not on-chain tokens.
        if chain in NON_TOKEN_CHAINS or not looks_like_address(address):
            continue
        out.append(TokenRef(
            symbol=str(r.get(sym_c, "")).strip(),
            name=str(r.get(name_c, "")).strip() if name_c else "",
            address=address,
            chain=chain,
            volume_24h=parse_number(r.get(vol_c)) if vol_c else None,
            price_usd=parse_number(r.get(price_c)) if price_c else None,
            market_cap_usd=parse_number(r.get(mcap_c)) if mcap_c else None,
        ))
    return out


#: When one asset is listed on several chains (bridged / native copies), prefer
#: its main chain in this order; anything not listed ranks after these.
CHAIN_PRIORITY = ("ethereum", "solana", "bitcoin", "bnb", "base", "arbitrum", "polygon",
                  "optimism", "avalanche", "tron", "ton", "sui", "near")
#: Listings within this fraction of the largest market cap count as the same asset.
SAME_ASSET_MCAP_TOLERANCE = 0.05


def pick_candidate(cands: list[TokenRef]) -> TokenRef | None:
    """Choose the canonical listing among exact-symbol matches.

    1. The listings with the largest market cap are the real asset (copycat
       tokens with the same ticker are far smaller).
    2. Among listings within 5% of that market cap - the same asset bridged to
       several chains, e.g. native ETH on ethereum/base/robinhood - prefer the
       main chain (CHAIN_PRIORITY), then the highest 24h volume.
    Without market caps (e.g. MCP markdown search), fall back to 24h volume.
    """
    if not cands:
        return None

    def vol(t: TokenRef) -> float:
        return t.volume_24h if t.volume_24h is not None else -1.0

    def prio(t: TokenRef) -> int:
        return CHAIN_PRIORITY.index(t.chain) if t.chain in CHAIN_PRIORITY else len(CHAIN_PRIORITY)

    caps = [t.market_cap_usd for t in cands if t.market_cap_usd]
    if not caps:
        return max(cands, key=vol)
    top = max(caps)
    group = [t for t in cands if t.market_cap_usd and t.market_cap_usd >= top * (1 - SAME_ASSET_MCAP_TOLERANCE)]
    return min(group, key=lambda t: (prio(t), -vol(t)))


async def resolve_token(c: NansenClient, symbol: str, chain: str) -> tuple[TokenRef | None, ToolResult]:
    """Resolve ``symbol`` via ``general_search``.

    Only an exact (case-insensitive) symbol match is accepted, on ``chain`` if
    one is given (otherwise on any chain); the canonical listing is chosen by
    :func:`pick_candidate`, which avoids low-volume copycats with the same
    ticker and odd bridged copies of a native asset.
    """
    res = await c.call("general_search", search_args(symbol, chain))
    if not res.ok:
        return None, res
    want = symbol.strip().casefold()
    cands = [t for t in parse_search_candidates(res.text, chain)
             if t.symbol.casefold() == want and (not chain or t.chain == chain.lower())]
    return pick_candidate(cands), res


def token_info_args(token: TokenRef, timeframe: str = "1d") -> dict:
    """Arguments for ``token_info`` (price / market context)."""
    return {"request": {"chain": token.chain, "tokenAddress": token.address,
                        "timeframe": timeframe}}


def token_ohlcv_args(token: TokenRef, timeframe: str = "1d") -> dict:
    """Arguments for ``token_ohlcv`` (daily candles -> 24h price change)."""
    return {"request": {"chain": token.chain, "tokenAddress": token.address,
                        "timeframe": timeframe}}


async def get_token_ohlcv(c: NansenClient, token: TokenRef) -> ToolResult:
    """Daily OHLCV candles for the token (price context; failure is harmless)."""
    return await c.call("token_ohlcv", token_ohlcv_args(token))


async def get_token_info(c: NansenClient, token: TokenRef) -> ToolResult:
    """Price / market data for the token (context only; failure is harmless)."""
    return await c.call("token_info", token_info_args(token))


async def get_flows(c: NansenClient, token: TokenRef, period: str) -> ToolResult:
    """Smart-money / cohort flow summary for the token."""
    return await c.call("token_recent_flows_summary", flows_args(token, period))


async def get_who_bought_sold(
    c: NansenClient, token: TokenRef, side: Literal["BUY", "SELL"], period: str
) -> ToolResult:
    """Smart-labelled wallets that bought (or sold) the token."""
    return await c.call("token_who_bought_sold", who_bought_sold_args(token, side, period))
