#!/usr/bin/env python3
"""Stress test: make at least N real Nansen MCP tool calls and report on them.

Usage (from the repository root, with your key in .env)::

    python scripts/stress_test.py
    python scripts/stress_test.py --tokens PEPE,UNI,LINK --chain ethereum --min-calls 100

For each token, in rounds, it calls ``general_search`` then
``token_recent_flows_summary`` for several lookback periods and
``token_who_bought_sold`` for BUY and SELL, then ``token_info``, until at
least ``--min-calls`` calls were made. Everything happens in ONE MCP session
with a small delay between calls. Failures never stop the run (except a
rejected API key). Only Nansen MCP calls are made and counted: this script
never calls LunarCrush or the Fear & Greed API.

Outputs:
    reports/stress_report.json   totals, per-tool success/failure/latency, error reasons
    reports/raw/<tool>_<token>[_<variant>].txt   raw text of the latest call of each kind

API keys are never written to any file; the script double-checks that.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Allow "python scripts/stress_test.py" from the repo root without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zalat.config import Settings, load_settings, redact  # noqa: E402
from zalat.errors import ConfigError, NansenAuthError, NansenNetworkError  # noqa: E402
from zalat.nansen_mcp import (  # noqa: E402
    LOOKBACK,
    NansenMCPClient,
    ToolResult,
    TokenRef,
    flows_args,
    parse_search_candidates,
    search_args,
    token_info_args,
    who_bought_sold_args,
)
from zalat.parsing import extract_price_info, extract_side_volume, extract_sm_flow  # noqa: E402

DEFAULT_TOKENS = "PEPE,UNI,LINK,AAVE,SHIB,LDO,MKR,ARB,ONDO,ENA"
RETRYABLE = {"network", "timeout"}
MAX_RETRIES = 3


def _sdk_version() -> str:
    try:
        from importlib.metadata import version

        return version("mcp")
    except Exception:  # noqa: BLE001
        return "unknown"


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, math.ceil(0.95 * len(s)) - 1)]


def _safe(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)


class StressRun:
    """Keeps counts, writes raw samples and builds the final report."""

    def __init__(self, client: Any, settings: Settings, out_dir: Path, delay: float,
                 max_calls: int, sleep: Callable[[float], Any] = asyncio.sleep) -> None:
        self.client = client
        self.settings = settings
        self.out_dir = out_dir
        self.raw_dir = out_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.max_calls = max_calls
        self.sleep = sleep
        self.calls: list[dict[str, Any]] = []
        self.parse_stats: Counter[str] = Counter()

    @property
    def total(self) -> int:
        return len(self.calls)

    def _write_raw(self, res: ToolResult, token: str, variant: str) -> None:
        name = _safe(f"{res.tool}_{token}" + (f"_{variant}" if variant else "")) + ".txt"
        header = (f"# tool={res.tool} token={token} variant={variant or '-'} ok={res.ok} "
                  f"error_kind={res.error_kind} reason={res.reason} latency_ms={res.latency_ms:.0f}\n")
        (self.raw_dir / name).write_text(redact(header + res.text, self.settings.secrets()),
                                         encoding="utf-8")

    async def call(self, tool: str, args: dict, token: str, variant: str = "") -> ToolResult:
        """One logical call, with up to MAX_RETRIES retries (each retry counts as a call)."""
        res: ToolResult | None = None
        for attempt in range(MAX_RETRIES + 1):
            if self.total >= self.max_calls:
                break
            if self.total:
                await self.sleep(self.delay * (2 ** attempt if attempt else 1))
            start = time.perf_counter()
            res = await self.client.call(tool, args)  # may raise NansenAuthError
            latency = res.latency_ms or (time.perf_counter() - start) * 1000
            rate_limited = "429" in (res.text or "")[:500] or "rate limit" in (res.text or "").lower()
            self.calls.append({
                "n": self.total + 1, "tool": tool, "token": token, "variant": variant,
                "attempt": attempt + 1, "ok": res.ok, "error_kind": res.error_kind,
                "reason": ("rate_limited" if rate_limited and not res.ok else res.reason),
                "latency_ms": round(latency, 1),
            })
            self._write_raw(res, token, variant)
            if res.ok or not (res.error_kind in RETRYABLE or rate_limited):
                break
        return res or ToolResult(tool, False, "call budget exhausted", False, "protocol")

    async def run(self, tokens: list[str], chain: str, periods: list[str], min_calls: int) -> None:
        """Cycle through the tokens until at least ``min_calls`` calls were made."""
        resolved: dict[str, TokenRef | None] = {}
        rnd = 0
        while self.total < min_calls and self.total < self.max_calls:
            rnd += 1
            before = self.total
            for sym in tokens:
                if self.total >= min_calls:
                    return
                res = await self.call("general_search", search_args(sym, chain), sym)
                if res.ok:
                    want = sym.casefold()
                    cands = [t for t in parse_search_candidates(res.text, chain)
                             if t.symbol.casefold() == want and t.chain == chain]
                    cands.sort(key=lambda t: t.volume_24h or -1.0, reverse=True)
                    if cands:
                        resolved[sym] = cands[0]
                        self.parse_stats["search_resolved"] += 1
                    else:
                        self.parse_stats["search_no_match"] += 1
                token = resolved.get(sym)
                if token is None:
                    continue  # nothing to query without an address; search still counted
                for period in periods:
                    if self.total >= min_calls:
                        return
                    r = await self.call("token_recent_flows_summary", flows_args(token, period),
                                        sym, period)
                    if r.ok:
                        key = "flows_parsed" if extract_sm_flow(r.text) else "flows_unparsed"
                        self.parse_stats[key] += 1
                for side in ("BUY", "SELL"):
                    if self.total >= min_calls:
                        return
                    period = periods[rnd % len(periods)]
                    r = await self.call("token_who_bought_sold",
                                        who_bought_sold_args(token, side, period), sym, side)
                    if r.ok:
                        key = "wbs_parsed" if extract_side_volume(r.text, side) else "wbs_unparsed"
                        self.parse_stats[key] += 1
                if self.total >= min_calls:
                    return
                r = await self.call("token_info", token_info_args(token), sym)
                if r.ok:
                    price, change = extract_price_info(r.text)
                    key = "token_info_parsed" if (price, change) != (None, None) else "token_info_unparsed"
                    self.parse_stats[key] += 1
            if self.total == before:
                break  # a full round made no calls (e.g. empty token list): don't spin forever

    def report(self, meta: dict[str, Any]) -> dict[str, Any]:
        per_tool: dict[str, dict[str, Any]] = {}
        lat: dict[str, list[float]] = defaultdict(list)
        reasons: dict[str, Counter[str]] = defaultdict(Counter)
        for c in self.calls:
            t = per_tool.setdefault(c["tool"], {"calls": 0, "ok": 0, "fail": 0})
            t["calls"] += 1
            t["ok" if c["ok"] else "fail"] += 1
            lat[c["tool"]].append(c["latency_ms"])
            if not c["ok"]:
                reasons[c["tool"]][c["reason"] or c["error_kind"] or "unknown"] += 1
        for tool, t in per_tool.items():
            t["avg_ms"] = round(sum(lat[tool]) / len(lat[tool]), 1)
            t["p95_ms"] = round(_p95(lat[tool]), 1)
        ok = sum(1 for c in self.calls if c["ok"])
        return {
            **meta,
            "total_calls": self.total,
            "successes": ok,
            "failures": self.total - ok,
            "per_tool": per_tool,
            "error_reasons": {k: dict(v) for k, v in reasons.items()},
            "parse_stats": dict(self.parse_stats),
            "calls": self.calls,
        }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Make >= N Nansen MCP calls and write a report.")
    p.add_argument("--tokens", default=DEFAULT_TOKENS, help="comma-separated symbols")
    p.add_argument("--chain", default="ethereum")
    p.add_argument("--periods", default="1h,1d,7d",
                   help=f"comma-separated flow lookback periods ({', '.join(LOOKBACK)})")
    p.add_argument("--min-calls", type=int, default=100)
    p.add_argument("--max-calls", type=int, default=None,
                   help="hard cap on calls incl. retries (default: min-calls + 20)")
    p.add_argument("--delay", type=float, default=0.3, help="seconds between calls")
    p.add_argument("--timeout", type=float, default=None)
    p.add_argument("--out", default="reports", help="output directory")
    return p


def _print_summary(rep: dict[str, Any]) -> None:
    print(f"\nNansen MCP stress test - {rep['status']}")
    print(f"  total calls : {rep['total_calls']}  (target {rep['min_calls']})")
    print(f"  successes   : {rep['successes']}")
    print(f"  failures    : {rep['failures']}")
    for tool, t in sorted(rep["per_tool"].items()):
        print(f"  - {tool}: {t['calls']} calls, {t['ok']} ok, {t['fail']} failed, "
              f"avg {t['avg_ms']} ms, p95 {t['p95_ms']} ms")
        for reason, n in sorted(rep["error_reasons"].get(tool, {}).items()):
            print(f"      failed: {reason} x{n}")
    if rep.get("parse_stats"):
        print(f"  parsing     : {rep['parse_stats']}")
    if rep.get("error"):
        print(f"  error       : {rep['error']}")
    print(f"  report      : {rep['report_path']}")


async def main(
    argv: list[str] | None = None,
    client_factory: Callable[[Settings], Any] = NansenMCPClient,
    settings: Settings | None = None,
    env_file: str | None = ".env",
    sleep: Callable[[float], Any] = asyncio.sleep,
) -> int:
    """Run the stress test. ``client_factory``/``settings``/``sleep`` are injectable for tests.

    Exit codes: 0 target reached, 1 target not reached, 2 config error,
    4 auth rejected, 5 MCP unreachable.
    """
    args = build_parser().parse_args(argv)
    tokens = [t.strip() for t in args.tokens.split(",") if t.strip()]
    if not tokens:
        print("Error: --tokens must list at least one symbol, e.g. PEPE,UNI", file=sys.stderr)
        return 2
    periods = [p.strip() for p in args.periods.split(",") if p.strip()] or ["1d"]
    bad = [p for p in periods if p not in LOOKBACK]
    if bad:
        print(f"Error: invalid --periods {bad}; allowed: {', '.join(LOOKBACK)}", file=sys.stderr)
        return 2
    if args.min_calls < 1:
        print("Error: --min-calls must be at least 1", file=sys.stderr)
        return 2
    if settings is None:
        try:
            settings = load_settings(env_file, timeout=args.timeout)
        except ConfigError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
    max_calls = args.max_calls or args.min_calls + 20
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    meta: dict[str, Any] = {
        "started_at": started.replace(microsecond=0).isoformat(),
        "mcp_url": settings.mcp_url,
        "mcp_sdk_version": _sdk_version(),
        "chain": args.chain,
        "tokens": tokens,
        "periods": periods,
        "min_calls": args.min_calls,
        "delay_s": args.delay,
    }
    run: StressRun | None = None
    status, error, code = "completed", None, 0
    try:
        async with client_factory(settings) as client:
            run = StressRun(client, settings, out_dir, args.delay, max_calls, sleep)
            await run.run(tokens, args.chain.lower(), periods, args.min_calls)
    except NansenAuthError as exc:
        status, error, code = "aborted_auth", str(exc), 4
    except NansenNetworkError as exc:
        status, error, code = "aborted_unreachable", str(exc), 5
    if run is None:
        run = StressRun(None, settings, out_dir, args.delay, max_calls, sleep)
    if code == 0 and run.total < args.min_calls:
        status, code = "target_not_reached", 1

    rep = run.report(meta)
    rep.update({
        "status": status,
        "error": redact(error, settings.secrets()) if error else None,
        "finished_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "duration_s": round(time.perf_counter() - t0, 2),
        "report_path": str(out_dir / "stress_report.json"),
    })
    report_path = out_dir / "stress_report.json"
    report_path.write_text(redact(json.dumps(rep, indent=2, ensure_ascii=False),
                                  settings.secrets()), encoding="utf-8")

    # Belt and braces: make sure the key did not end up in any written file.
    for f in [report_path, *sorted((out_dir / "raw").glob("*.txt"))]:
        if any(k in f.read_text(encoding="utf-8") for k in settings.secrets()):
            f.write_text(redact(f.read_text(encoding="utf-8"), settings.secrets()), encoding="utf-8")
            print(f"WARNING: redacted an API key from {f}", file=sys.stderr)

    _print_summary(rep)
    return code


if __name__ == "__main__":
    import logging

    logging.getLogger("mcp").setLevel(logging.ERROR)
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    sys.exit(asyncio.run(main()))
