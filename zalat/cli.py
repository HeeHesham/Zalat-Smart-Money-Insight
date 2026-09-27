"""Command-line interface: ``python -m zalat PEPE --chain ethereum --period 1d``.

Exit codes:
    0  verdict rendered (even partial / INSUFFICIENT_DATA)
    1  unexpected error
    2  bad arguments or configuration (e.g. missing API key)
    3  token could not be resolved from its symbol
    4  Nansen rejected the API key (HTTP 401/403)
    5  Nansen MCP unreachable (and no --address given)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import traceback
from typing import Any, Awaitable, Callable

from zalat import __version__
from zalat.config import Settings, load_settings, redact
from zalat.errors import ConfigError, NansenAuthError, NansenNetworkError
from zalat.fng import CrowdSignal, fetch_fng
from zalat.nansen_mcp import (
    LOOKBACK,
    NansenMCPClient,
    ToolResult,
    TokenRef,
    get_flows,
    get_who_bought_sold,
    resolve_token,
)
from zalat.parsing import extract_side_volume, extract_sm_flow
from zalat.render import render_json, render_text
from zalat.verdict import build_sm_signal, decide

EXIT_OK, EXIT_UNEXPECTED, EXIT_CONFIG, EXIT_NOT_FOUND, EXIT_AUTH, EXIT_UNREACHABLE = 0, 1, 2, 3, 4, 5

ClientFactory = Callable[[Settings], Any]          # returns an async context manager
FngFetcher = Callable[[str, float], Awaitable[CrowdSignal]]

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
            "Contrast Nansen smart-money activity on a token with the crowd's mood "
            "(Fear & Greed Index) and print a bilingual (English/Arabic) verdict. "
            "Not financial advice."
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
                   help="also print the raw text of every Nansen tool call to stderr")
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
    secrets = [settings.api_key] if settings else None
    print(redact(msg, secrets), file=sys.stderr)


def _dump_raw(res: ToolResult, settings: Settings) -> None:
    extra = f" error={res.error_kind} reason={res.reason}" if not res.ok else ""
    _err(f"=== {res.tool} ok={res.ok}{extra} ({res.latency_ms:.0f} ms) ===\n{res.text}\n", settings)


async def run(
    args: argparse.Namespace,
    settings: Settings,
    client_factory: ClientFactory = NansenMCPClient,
    fng_fetcher: FngFetcher | None = None,
) -> tuple[int, str]:
    """Do the work. Returns ``(exit_code, text_to_print_on_stdout)``."""
    fetch = fng_fetcher or (lambda url, timeout: fetch_fng(url, timeout))
    # The crowd side is independent of Nansen, so fetch it concurrently.
    crowd_task = asyncio.ensure_future(fetch(settings.fng_url, settings.timeout))

    chain = args.chain.strip().lower()
    token: TokenRef | None = None
    if args.address:
        sym = (args.symbol or args.address[:10]).upper()
        token = TokenRef(symbol=sym, name=args.symbol or "", address=args.address.strip(), chain=chain)

    flow = buy = sell = None
    try:
        async with client_factory(settings) as nc:
            if token is None:
                token, res = await resolve_token(nc, args.symbol, chain)
                if args.raw:
                    _dump_raw(res, settings)
                if token is None:
                    crowd_task.cancel()
                    if not res.ok:
                        _err(f"Token search failed ({res.error_kind}: {res.reason}). "
                             "Try again, or pass --address <contract>.", settings)
                    else:
                        _err(f"Could not find token '{args.symbol}' on chain '{chain}'. "
                             "Check the symbol/chain or pass --address <contract>.", settings)
                    return EXIT_NOT_FOUND, ""
                log.debug("resolved %s -> %s", args.symbol, token.address)

            fres = await get_flows(nc, token, args.period)
            bres = await get_who_bought_sold(nc, token, "BUY", args.period)
            sres = await get_who_bought_sold(nc, token, "SELL", args.period)
            for r in (fres, bres, sres):
                if args.raw:
                    _dump_raw(r, settings)
                if not r.ok:
                    log.debug("%s failed: %s %s", r.tool, r.error_kind, r.reason)
            # Each part independently: a failed or unparseable tool -> None.
            flow = extract_sm_flow(fres.text) if fres.ok else None
            buy = extract_side_volume(bres.text) if bres.ok else None
            sell = extract_side_volume(sres.text) if sres.ok else None
    except NansenAuthError as exc:
        crowd_task.cancel()
        _err(f"Error: {exc}", settings)
        return EXIT_AUTH, ""
    except NansenNetworkError as exc:
        if token is None:  # no --address and search never ran
            crowd_task.cancel()
            _err(f"Error: Nansen MCP unreachable at {settings.mcp_url}: {exc}", settings)
            return EXIT_UNREACHABLE, ""
        _err(f"Warning: Nansen MCP unreachable ({exc}); showing crowd mood only.", settings)

    crowd = await crowd_task
    if not crowd.available:
        log.debug("Fear & Greed unavailable: %s", crowd.error)
    sm = build_sm_signal(flow, buy, sell)
    verdict = decide(token, args.period, sm, crowd)
    out = render_json(verdict) if args.json else render_text(verdict, args.lang)
    return EXIT_OK, redact(out, [settings.api_key])


def main(
    argv: list[str] | None = None,
    *,
    client_factory: ClientFactory = NansenMCPClient,
    fng_fetcher: FngFetcher | None = None,
    env_file: str | None = ".env",
) -> int:
    """CLI entry point. ``client_factory``/``fng_fetcher`` are injectable for tests."""
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
        handler.addFilter(_RedactFilter([settings.api_key]))
        logging.basicConfig(level=logging.DEBUG, handlers=[handler], force=True)
    # Never let HTTP libraries log request headers.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger("mcp").setLevel(logging.ERROR)

    try:
        code, out = asyncio.run(run(args, settings, client_factory, fng_fetcher))
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
