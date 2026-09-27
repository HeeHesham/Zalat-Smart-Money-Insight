"""Command-line interface: ``python -m zalat PEPE --chain ethereum --period 1d``.

Exit codes:
    0  verdict rendered (even partial / INSUFFICIENT_DATA)
    1  unexpected error
    2  bad arguments or configuration (e.g. missing API key)
    3  token could not be resolved from its symbol
    4  Nansen rejected the API key (HTTP 401/403)
    5  Nansen unreachable, or the token search itself failed (no --address)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import traceback
from urllib.parse import quote
from typing import Any, Awaitable, Callable

from zalat import __version__
from zalat.config import Settings, load_settings, redact
from zalat.errors import ConfigError, NansenAuthError, NansenNetworkError, auth_message
from zalat.fng import CrowdSignal, fetch_fng
from zalat.lunarcrush import SocialSignal, apply_price_guard, fetch_social
from zalat.nansen_mcp import (
    LOOKBACK,
    ToolResult,
    TokenRef,
    get_flows,
    get_token_info,
    get_token_ohlcv,
    get_who_bought_sold,
    resolve_token,
)
from zalat.nansen_rest import AUTH_MESSAGE as REST_AUTH_MESSAGE
from zalat.nansen_rest import make_client
from zalat.parsing import (
    extract_buy_sell,
    extract_ohlcv_change,
    extract_price_info,
    extract_sm_flow,
    extract_token_market,
    extract_top_pnl_flow,
)
from zalat.render import render_json, render_text
from zalat.verdict import build_price_context, build_sm_signal, decide

EXIT_OK, EXIT_UNEXPECTED, EXIT_CONFIG, EXIT_NOT_FOUND, EXIT_AUTH, EXIT_UNREACHABLE = 0, 1, 2, 3, 4, 5

ClientFactory = Callable[[Settings], Any]          # returns an async context manager
FngFetcher = Callable[[str, float], Awaitable[CrowdSignal]]
# (symbol, key, base_url, timeout) -> SocialSignal
SocialFetcher = Callable[[str | None, str | None, str, float], Awaitable[SocialSignal]]

log = logging.getLogger("zalat")


class _RedactFilter(logging.Filter):
    """Scrub secrets from every log record before it is emitted."""

    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self.secrets = secrets

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage(), self.secrets)
        record.args = ()
        return True


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m zalat",
        description=(
            "Contrast Nansen smart-money activity on a token with crowd sentiment and print "
            "a bilingual (English/Arabic) verdict. Crowd = the token's social sentiment "
            "(LunarCrush, only if LUNARCRUSH_API_KEY is set; needs a paid plan), otherwise the "
            "market-wide mood (alternative.me Fear & Greed: whole crypto market, not "
            "token-specific). Not financial advice."
        ),
    )
    p.add_argument("symbol", nargs="?", help="token symbol, e.g. PEPE (optional with --address)")
    p.add_argument("--address", help="token contract address; skips the symbol search")
    p.add_argument("--chain", default="ethereum", help="chain name (default: ethereum)")
    p.add_argument("--period", default="1d", choices=LOOKBACK,
                   help="smart-money lookback period (default: 1d)")
    p.add_argument("--lang", default="both", choices=("en", "ar", "both"),
                   help="output language (default: both)")
    p.add_argument("--json", action="store_true", help="print machine-readable JSON")
    p.add_argument("--raw", action="store_true",
                   help="also print the raw text of every Nansen tool call (and the LunarCrush status) to stderr")
    p.add_argument("--timeout", type=float, default=None,
                   help="network timeout in seconds (default: 30 or ZALAT_TIMEOUT)")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging (key redacted)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _reconfigure_streams() -> None:
    """Make sure Arabic prints on consoles that default to a legacy code page."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def _err(msg: str, settings: Settings | None = None) -> None:
    secrets = settings.secrets() if settings else None
    print(redact(msg, secrets), file=sys.stderr)


def _cancel(*tasks: asyncio.Future) -> None:
    for task in tasks:
        task.cancel()


def _dump_social(sig: SocialSignal, settings: Settings) -> None:
    # The requested path (never the key: it only travels in a header).
    path = (f"GET {settings.lunarcrush_url}/public/coins/{quote(sig.symbol.lower(), safe='')}/v1"
            if settings.lunarcrush_key and sig.symbol else "no request made")
    detail = (f"{path}\n"
              f"sentiment={sig.sentiment} galaxy_score={sig.galaxy_score} "
              f"price={sig.price_usd} pct_change_24h={sig.pct_change_24h}")
    err = f" error={sig.error}" if sig.error else ""
    _err(f"=== lunarcrush status={sig.status} http={sig.http_status} ===\n{detail}{err}\n", settings)


def _meta(res: ToolResult) -> str:
    """HTTP status / request id / credits of a REST call ("" for MCP)."""
    parts = []
    if res.http_status is not None:
        parts.append(f"http={res.http_status}")
    if res.request_id:
        parts.append(f"request_id={res.request_id}")
    if res.credits_cost is not None:
        parts.append(f"credits_cost={res.credits_cost:g}")
    if res.credits_remaining is not None:
        parts.append(f"credits_remaining={res.credits_remaining:g}")
    if res.retries:
        parts.append(f"retries_429={res.retries}")
    return (" " + " ".join(parts)) if parts else ""


def _dump_raw(res: ToolResult, settings: Settings) -> None:
    extra = f" error={res.error_kind} reason={res.reason}" if not res.ok else ""
    _err(f"=== {res.tool} ok={res.ok}{extra}{_meta(res)} ({res.latency_ms:.0f} ms) ===\n"
         f"{res.text}\n", settings)


def _log_call(res: ToolResult) -> None:
    log.debug("%s ok=%s%s latency=%.0fms%s", res.tool, res.ok, _meta(res), res.latency_ms,
              "" if res.ok else f" error={res.error_kind} reason={res.reason}")


async def run(
    args: argparse.Namespace,
    settings: Settings,
    client_factory: ClientFactory = make_client,
    fng_fetcher: FngFetcher | None = None,
    social_fetcher: SocialFetcher | None = None,
) -> tuple[int, str]:
    """Do the work. Returns ``(exit_code, text_to_print_on_stdout)``."""
    fetch = fng_fetcher or (lambda url, timeout: fetch_fng(url, timeout))
    fetch_lc = social_fetcher or fetch_social
    # Both sentiment sources are independent of Nansen: fetch them concurrently
    # while the Nansen calls run. Without LUNARCRUSH_API_KEY, fetch_social
    # returns "not_configured" immediately and makes no request.
    market_task = asyncio.ensure_future(fetch(settings.fng_url, settings.timeout))
    social_task = asyncio.ensure_future(fetch_lc(
        args.symbol.upper() if args.symbol else None,
        settings.lunarcrush_key, settings.lunarcrush_url, settings.timeout))

    chain = args.chain.strip().lower()
    token: TokenRef | None = None
    if args.address:
        addr = args.address.strip()
        # Without a symbol, show a shortened address rather than inventing a ticker.
        # Without a symbol we keep it empty (JSON gets ""); text output shows
        # a shortened address instead of inventing a ticker.
        sym = args.symbol.upper() if args.symbol else ""
        token = TokenRef(symbol=sym, name="", address=addr, chain=chain)

    flow = buy = sell = top_pnl = None
    ires: ToolResult | None = None
    ores: ToolResult | None = None
    try:
        async with client_factory(settings) as nc:
            if token is None:
                token, res = await resolve_token(nc, args.symbol, chain)
                _log_call(res)
                if args.raw:
                    _dump_raw(res, settings)
                if token is None:
                    _cancel(market_task, social_task)
                    if not res.ok and res.error_kind == "auth":
                        msg = REST_AUTH_MESSAGE if settings.backend == "rest" else auth_message()
                        _err(f"Error: {msg}", settings)
                        return EXIT_AUTH, ""
                    if not res.ok:
                        # The search itself failed (tool error, timeout...): that is
                        # a Nansen-side problem, not "token does not exist".
                        rid = f", request_id {res.request_id}" if res.request_id else ""
                        _err(f"Token search failed ({res.error_kind}: {res.reason}{rid}). "
                             "Try again, or pass --address <contract>.", settings)
                        return EXIT_UNREACHABLE, ""
                    else:
                        _err(f"Could not find token '{args.symbol}' on chain '{chain}'. "
                             "Check the symbol/chain or pass --address <contract>.", settings)
                    return EXIT_NOT_FOUND, ""
                log.debug("resolved %s -> %s", args.symbol, token.address)

            fres = await get_flows(nc, token, args.period)
            bres = await get_who_bought_sold(nc, token, "BUY", args.period)
            sres = await get_who_bought_sold(nc, token, "SELL", args.period)
            # Price / market context (optional): failures here are harmless.
            ores = await get_token_ohlcv(nc, token)
            ires = await get_token_info(nc, token)
            for r in (fres, bres, sres, ores, ires):
                _log_call(r)
                if args.raw:
                    _dump_raw(r, settings)
            # Each part independently: a failed or unparseable tool -> None.
            flow = extract_sm_flow(fres.text) if fres.ok else None
            top_pnl = extract_top_pnl_flow(fres.text) if fres.ok else None
            # BUY and SELL lists are merged by wallet (REST rows carry both sides).
            buy, sell = extract_buy_sell(bres.text if bres.ok else None,
                                         sres.text if sres.ok else None)
    except NansenAuthError as exc:
        _cancel(market_task, social_task)
        _err(f"Error: {exc}", settings)
        return EXIT_AUTH, ""
    except NansenNetworkError as exc:
        if token is None:  # no --address and search never ran
            _cancel(market_task, social_task)
            url = settings.rest_url if settings.backend == "rest" else settings.mcp_url
            _err(f"Error: Nansen unreachable at {url}: {exc}", settings)
            return EXIT_UNREACHABLE, ""
        _err(f"Warning: Nansen unreachable ({exc}); showing sentiment only.", settings)

    market, social = await asyncio.gather(market_task, social_task)
    if not market.available:
        log.debug("Fear & Greed unavailable: %s", market.error)
    # Same symbol, different coin? Compare LunarCrush's price with Nansen's.
    social = apply_price_guard(social, token.price_usd)
    if args.raw:
        _dump_social(social, settings)
    info = extract_price_info(ires.text) if ires is not None and ires.ok else None
    market_ctx = extract_token_market(ires.text) if ires is not None and ires.ok else None
    ohlcv = extract_ohlcv_change(ores.text) if ores is not None and ores.ok else None
    price = build_price_context(token, info, social, ohlcv, market_ctx)
    sm = build_sm_signal(flow, buy, sell, min_gross_usd=settings.min_gross_usd, top_pnl=top_pnl)
    verdict = decide(token, args.period, sm, market, social, price)
    out = render_json(verdict) if args.json else render_text(verdict, args.lang)
    return EXIT_OK, redact(out, settings.secrets())


def main(
    argv: list[str] | None = None,
    *,
    client_factory: ClientFactory = make_client,
    fng_fetcher: FngFetcher | None = None,
    social_fetcher: SocialFetcher | None = None,
    env_file: str | None = ".env",
) -> int:
    """CLI entry point. ``client_factory`` and the fetchers are injectable for tests."""
    _reconfigure_streams()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse exits 2 on error, 0 on --help/--version
        return int(exc.code or 0)
    if not args.symbol and not args.address:
        parser.print_usage(sys.stderr)
        _err("error: give a token symbol (e.g. PEPE) or --address")
        return EXIT_CONFIG
    if args.timeout is not None and args.timeout <= 0:
        _err("error: --timeout must be positive")
        return EXIT_CONFIG

    try:
        settings = load_settings(env_file, timeout=args.timeout)
    except ConfigError as exc:
        _err(f"Error: {exc}")
        return EXIT_CONFIG

    if args.verbose:
        handler = logging.StreamHandler(sys.stderr)
        handler.addFilter(_RedactFilter(settings.secrets()))
        logging.basicConfig(level=logging.DEBUG, handlers=[handler], force=True)
        logging.getLogger("asyncio").setLevel(logging.INFO)
    # Never let HTTP libraries log request headers.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger("mcp").setLevel(logging.ERROR)

    try:
        code, out = asyncio.run(run(args, settings, client_factory, fng_fetcher, social_fetcher))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001 - last-resort handler
        _err(f"Unexpected error: {type(exc).__name__}: {exc}", settings)
        if args.verbose:
            _err(traceback.format_exc(), settings)
        return EXIT_UNEXPECTED
    if out:
        print(out, end="" if out.endswith("\n") else "\n")
    return code
