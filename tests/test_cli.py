"""End-to-end CLI with a fake Nansen client and a fake Fear & Greed fetcher."""

import json

import pytest

from tests.conftest import (
    FAKE_KEY,
    FakeNansenClient,
    fixture_text,
    fng_const,
    happy_responses,
    ok,
    tool_error,
)
from zalat import DISCLAIMER_AR, DISCLAIMER_EN
from zalat.cli import main
from zalat.errors import NansenAuthError, NansenNetworkError
from zalat.nansen_mcp import ToolResult


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("NANSEN_API_KEY", FAKE_KEY)


def cli(argv, fake=None, fng=20):
    fake = fake or FakeNansenClient(happy_responses())
    return main(argv, client_factory=fake.factory, fng_fetcher=fng_const(fng), env_file=None), fake


def test_help(capsys):
    assert main(["--help"]) == 0
    assert "--address" in capsys.readouterr().out


def test_happy_path_both_languages(key, capsys):
    code, fake = cli(["PEPE"])
    out, err = capsys.readouterr()
    assert code == 0
    # No LUNARCRUSH_API_KEY -> market-wide wording + future-work note.
    assert "Smart money is buying while the overall crypto market is fearful (market-wide mood, not this token)" in out
    assert "الأموال الذكية تشتري بينما يسود الخوف سوق الكريبتو بأكمله (مزاج السوق العام، وليس هذه العملة)" in out
    assert "not configured - needs a paid LunarCrush API plan" in out
    assert "غير مُفعَّلة - تتطلب اشتراكاً مدفوعاً في LunarCrush" in out
    assert DISCLAIMER_EN in out and DISCLAIMER_AR in out
    assert [c[0] for c in fake.calls] == ["general_search", "token_recent_flows_summary",
                                          "token_who_bought_sold", "token_who_bought_sold",
                                          "token_ohlcv", "token_info"]
    assert FAKE_KEY not in out + err


@pytest.mark.parametrize("fng, kind", [(20, "CONTRARIAN_BULLISH"), (80, "CONFIRMED_BULLISH"),
                                       (50, "NEUTRAL"), (None, "SM_ONLY")])
def test_json_kinds(key, capsys, fng, kind):
    code, _ = cli(["PEPE", "--json"], fng=fng)
    data = json.loads(capsys.readouterr().out)
    assert code == 0 and data["kind"] == kind


def test_bearish_kinds(key, capsys):
    responses = happy_responses()
    responses["token_recent_flows_summary"] = ok("token_recent_flows_summary",
                                                 fixture_text("flows_json.json"))

    def wbs(args):
        side = args["request"]["buy_or_sell"]
        # Swap: smart money mostly SELLING.
        name = "wbs_sell_md.txt" if side == "BUY" else "wbs_buy_md.txt"
        return ok("token_who_bought_sold", fixture_text(name))

    responses["token_who_bought_sold"] = wbs
    code, _ = cli(["PEPE", "--json"], FakeNansenClient(responses), fng=85)
    assert code == 0 and json.loads(capsys.readouterr().out)["kind"] == "WARNING_BEARISH"
    code, _ = cli(["PEPE", "--json"], FakeNansenClient(responses), fng=15)
    assert json.loads(capsys.readouterr().out)["kind"] == "CONFIRMED_BEARISH"


def test_all_data_tools_fail_gives_insufficient_data(key, capsys):
    fake = FakeNansenClient({"general_search": ok("general_search", fixture_text("search_pepe.json"))})
    code, _ = cli(["PEPE", "--lang", "en"], fake)
    out = capsys.readouterr().out
    assert code == 0
    assert "Not enough smart-money data" in out
    assert "Market-wide mood (whole crypto market, BTC-centric; NOT specific to Pepe (PEPE)): Extreme Fear" in out


def test_address_skips_search_and_period(key, capsys):
    code, fake = cli(["--address", "0xabc", "--period", "7d", "--lang", "ar"])
    out = capsys.readouterr().out
    assert code == 0
    assert [c[0] for c in fake.calls][0] == "token_recent_flows_summary"
    assert fake.calls[0][1]["request"]["tokenAddress"] == "0xabc"
    assert fake.calls[0][1]["request"]["lookbackPeriod"] == "7d"
    assert fake.calls[1][1]["request"]["time_range"]["from"] == "7D_AGO"
    assert "الحكم:" in out and "VERDICT:" not in out


def test_raw_dumps_to_stderr(key, capsys):
    responses = happy_responses()
    responses["token_who_bought_sold"] = tool_error("token_who_bought_sold")
    code, _ = cli(["PEPE", "--raw", "--lang", "en"], FakeNansenClient(responses))
    out, err = capsys.readouterr()
    assert code == 0
    assert "=== general_search ok=True" in err
    assert "=== token_who_bought_sold ok=False error=tool_error reason=unclassified_failure" in err
    assert "Smart Money" in err  # raw flows table
    assert "=== " not in out


def test_raw_is_redacted(key, capsys):
    responses = happy_responses()
    responses["token_recent_flows_summary"] = ok("token_recent_flows_summary", f"echo {FAKE_KEY}")
    cli(["PEPE", "--raw", "-v"], FakeNansenClient(responses))
    out, err = capsys.readouterr()
    assert FAKE_KEY not in out + err


def test_missing_key_exit_2_for_mcp_backend(capsys, monkeypatch):
    monkeypatch.setenv("ZALAT_NANSEN_BACKEND", "mcp")
    code, fake = cli(["PEPE"])
    assert code == 2 and "NANSEN_API_KEY is not set" in capsys.readouterr().err
    assert fake.calls == []


def test_missing_key_is_fine_for_rest_backend(capsys):
    # REST (default): no key -> no key header; a proxy may inject the credential.
    code, fake = cli(["PEPE"])
    assert code == 0 and fake.settings.api_key == "" and fake.settings.backend == "rest"


def test_bad_args_exit_2(key, capsys):
    assert main([], env_file=None) == 2
    assert main(["PEPE", "--period", "2d"], env_file=None) == 2
    assert main(["PEPE", "--timeout", "0"], env_file=None) == 2


def test_token_not_found_exit_3(key, capsys):
    code, fake = cli(["NOPE"])
    assert code == 3 and "Could not find token 'NOPE'" in capsys.readouterr().err
    assert len(fake.calls) == 1


def test_search_tool_error_exit_5(key, capsys):
    code, _ = cli(["PEPE"], FakeNansenClient({"general_search": tool_error("general_search")}))
    assert code == 5 and "Token search failed" in capsys.readouterr().err


def test_search_auth_tool_error_exit_4(key, capsys):
    res = ToolResult("general_search", False, "NANSEN_TOOL_ERROR: Unauthorized", True, "auth",
                     reason="auth")
    code, _ = cli(["PEPE"], FakeNansenClient({"general_search": res}))
    err = capsys.readouterr().err
    assert code == 4
    assert "Nansen rejected the request: check NANSEN_API_KEY in .env (missing or invalid)" in err
    assert "Token search failed" not in err and "auth: auth" not in err


def test_search_auth_tool_error_exit_4_mcp_message(key, capsys, monkeypatch):
    monkeypatch.setenv("ZALAT_NANSEN_BACKEND", "mcp")
    res = ToolResult("general_search", False, "Unauthorized", True, "auth", reason="auth")
    code, _ = cli(["PEPE"], FakeNansenClient({"general_search": res}))
    assert code == 4
    assert "Nansen rejected the API key. Check NANSEN_API_KEY / NANSEN_API_KEY_HEADER." in \
        capsys.readouterr().err


def test_address_without_symbol_uses_short_address(key, capsys):
    addr = "0x6982508145454ce325ddbe47a25d4ec3d2311933"
    code, _ = cli(["--address", addr, "--lang", "en"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Zalat Smart Money Verdict — 0x6982…1933\n" in out
    assert "0X69825081" not in out
    assert f"Address: {addr}" in out


def test_address_with_symbol_no_duplicate_name(key, capsys):
    cli(["PEPE", "--address", "0xabc", "--lang", "en"])
    out = capsys.readouterr().out
    assert "Zalat Smart Money Verdict — PEPE\n" in out and "PEPE (PEPE)" not in out


def test_resolved_token_shows_name(key, capsys):
    cli(["PEPE", "--lang", "en"])
    assert "Zalat Smart Money Verdict — Pepe (PEPE)\n" in capsys.readouterr().out


def test_disagreement_banner(key, capsys):
    cli(["PEPE"], fng=20)
    out = capsys.readouterr().out
    lines = out.splitlines()
    # the banner opens section 3 (final verdict)
    i = lines.index("━━ 3 · FINAL VERDICT ━━")
    assert lines[i + 1] == ">>> DISAGREEMENT: SMART MONEY vs OVERALL MARKET MOOD <<<"
    assert ">>> تباين: الأموال الذكية عكس مزاج السوق العام <<<" in out
    cli(["PEPE"], fng=80)  # confirmed bullish -> no banner
    assert ">>>" not in capsys.readouterr().out


def test_side_aware_volume_through_cli(key, capsys):
    both_cols = ok("token_who_bought_sold", json.dumps(
        {"data": [{"address": "0x1", "bought_volume_usd": 20000, "sold_volume_usd": 4000}]}))
    responses = happy_responses()
    responses["token_who_bought_sold"] = both_cols
    cli(["PEPE", "--json"], FakeNansenClient(responses))
    data = json.loads(capsys.readouterr().out)
    assert data["sm"]["buy"]["volume_usd"] == 20000
    assert data["sm"]["sell"]["volume_usd"] == 4000


def test_verbose_sets_asyncio_logger_info(key, capsys):
    import logging

    cli(["PEPE", "-v"])
    assert logging.getLogger("asyncio").level == logging.INFO


def test_auth_error_exit_4(key, capsys):
    fake = FakeNansenClient(enter_exc=NansenAuthError("Nansen rejected the API key (HTTP 401)."))
    code, _ = cli(["PEPE"], fake)
    out, err = capsys.readouterr()
    assert code == 4 and "HTTP 401" in err and FAKE_KEY not in out + err


def test_auth_error_during_call_exit_4(key, capsys):
    def boom(args):
        raise NansenAuthError("Nansen rejected the API key (HTTP 403).")

    code, _ = cli(["PEPE"], FakeNansenClient({"general_search": boom}))
    assert code == 4


def test_unreachable_exit_5(key, capsys):
    fake = FakeNansenClient(enter_exc=NansenNetworkError(f"cannot connect {FAKE_KEY}"))
    code, _ = cli(["PEPE"], fake)
    out, err = capsys.readouterr()
    assert code == 5 and "unreachable" in err and FAKE_KEY not in out + err


def test_unreachable_with_address_renders_crowd_only(key, capsys):
    fake = FakeNansenClient(enter_exc=NansenNetworkError("cannot connect"))
    code, _ = cli(["PEPE", "--address", "0xabc", "--json"], fake)
    out, err = capsys.readouterr()
    assert code == 0 and json.loads(out)["kind"] == "INSUFFICIENT_DATA"
    assert "Warning" in err


def test_unexpected_error_exit_1(key, capsys):
    def boom(args):
        raise RuntimeError(f"weird {FAKE_KEY}")

    code, _ = cli(["PEPE"], FakeNansenClient({"general_search": boom}))
    err = capsys.readouterr().err
    assert code == 1 and "weird ***" in err and FAKE_KEY not in err


def test_address_only_json_symbol_is_empty(key, capsys):
    addr = "0x6982508145454ce325ddbe47a25d4ec3d2311933"
    code, _ = cli(["--address", addr, "--json"])
    data = json.loads(capsys.readouterr().out)
    assert code == 0 and data["token"]["symbol"] == "" and data["token"]["address"] == addr


def test_min_gross_env_reaches_verdict(key, monkeypatch, capsys):
    # Happy-path volumes are ~$1-2M; a $10M minimum damps them to Neutral.
    monkeypatch.setenv("ZALAT_MIN_GROSS_USD", "10000000")
    cli(["PEPE", "--json"], fng=20)
    data = json.loads(capsys.readouterr().out)
    assert data["sm"]["small_volume"] is True
    assert {"key": "small_volume", "params": {}} in data["reasons"]


def test_dust_does_not_trigger_banner(key, capsys):
    responses = happy_responses()
    responses["token_recent_flows_summary"] = ok(
        "token_recent_flows_summary",
        "| Segment | Inflow | Outflow | Net Flow |\n|--|--|--|--|\n| Smart Money | $40 | $0 | $40 |")
    responses["token_who_bought_sold"] = lambda a: ok("token_who_bought_sold", json.dumps(
        {"data": [{"volumeUsd": 10 if a["request"]["buy_or_sell"] == "BUY" else 0}]}))
    code, _ = cli(["PEPE"], FakeNansenClient(responses), fng=15)
    out = capsys.readouterr().out
    assert code == 0 and ">>>" not in out and "No clear divergence" in out


# ======================= Sprint 2: LunarCrush + price in the CLI =========================
import asyncio  # noqa: E402

from tests.conftest import FAKE_LC_KEY, social_const  # noqa: E402
from zalat.lunarcrush import SocialSignal  # noqa: E402


def cli2(argv, fake=None, fng=20, social=None):
    fake = fake or FakeNansenClient(happy_responses())
    code = main(argv, client_factory=fake.factory, fng_fetcher=fng_const(fng),
                social_fetcher=social, env_file=None)
    return code, fake


def test_lc_off_default_fetcher_makes_no_request(key, capsys, monkeypatch):
    import httpx

    real_init = httpx.AsyncClient.__init__
    created = []

    def spy(self, *a, **k):
        created.append(k)
        real_init(self, *a, **k)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", spy)
    code, _ = cli2(["PEPE", "--json"])  # default social fetcher, no LUNARCRUSH_API_KEY
    data = json.loads(capsys.readouterr().out)
    assert code == 0 and data["social"]["status"] == "not_configured"
    assert data["crowd_source"] == "market_mood" and data["confidence"] == "Medium"
    assert created == []  # neither LunarCrush (nor anything else) opened a client


def test_lc_ok_gives_social_headline(key, capsys):
    code, _ = cli2(["PEPE", "--lang", "en"], fng=80, social=social_const(sentiment=25))
    out = capsys.readouterr().out
    assert code == 0
    assert "Smart money is buying while this token's social crowd is bearish" in out
    assert "Token social sentiment (PEPE, LunarCrush): Bearish - 25% positive" in out
    assert "not configured" not in out


def test_lc_402_note_and_market_fallback(key, capsys):
    sig = SocialSignal("not_authorized", "PEPE", http_status=402)
    code, _ = cli2(["PEPE", "--lang", "en"], social=social_const(sig))
    out = capsys.readouterr().out
    assert code == 0
    assert "(market-wide mood, not this token)" in out
    assert "key rejected or plan lacks social data (HTTP 402); this verdict compares" in out


def test_lc_price_mismatch_is_ignored(key, capsys):
    # LunarCrush price 100x off Nansen's search price -> different coin -> ignored.
    lc = SocialSignal("ok", "PEPE", 25, "Bearish", -0.5, price_usd=4e-04)
    cli2(["PEPE", "--json"], social=social_const(lc))
    data = json.loads(capsys.readouterr().out)
    assert data["social"]["status"] == "mismatch" and data["crowd_source"] == "market_mood"


def test_lc_symbol_passed_and_address_only_no_symbol(key, capsys):
    got = []

    async def spy(symbol, key_, base, timeout):
        got.append((symbol, key_, base))
        return SocialSignal("not_configured", symbol)

    cli2(["pepe"], social=spy)
    cli2(["--address", "0xabc"], social=spy)
    assert got[0][0] == "PEPE" and got[1][0] is None
    assert got[0][1] is None  # no LUNARCRUSH_API_KEY set


def test_lc_key_from_env_reaches_fetcher_and_is_redacted(key, capsys, monkeypatch):
    monkeypatch.setenv("LUNARCRUSH_API_KEY", FAKE_LC_KEY)
    seen = []

    async def leaky(symbol, key_, base, timeout):
        seen.append(key_)
        return SocialSignal("error", symbol, error=f"boom {key_}")

    responses = happy_responses()
    responses["token_info"] = ok("token_info", f"echo {FAKE_LC_KEY} {FAKE_KEY}")
    code, _ = cli2(["PEPE", "--raw", "-v"], FakeNansenClient(responses), social=leaky)
    out, err = capsys.readouterr()
    assert code == 0 and seen == [FAKE_LC_KEY]
    assert "=== lunarcrush status=error" in err and "=== token_info ok=True" in err
    assert FAKE_LC_KEY not in out + err and FAKE_KEY not in out + err


def test_fng_and_lc_fetched_concurrently(key, capsys):
    both_started = asyncio.Event()
    started = []

    async def fng(url, timeout):
        started.append("fng")
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), 2)
        return await fng_const(20)(url, timeout)

    async def lc(symbol, key_, base, timeout):
        started.append("lc")
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), 2)  # deadlocks (-> timeout) if sequential
        return SocialSignal("not_configured", symbol)

    fake = FakeNansenClient(happy_responses())
    code = main(["PEPE", "--json"], client_factory=fake.factory, fng_fetcher=fng,
                social_fetcher=lc, env_file=None)
    assert code == 0 and sorted(started) == ["fng", "lc"]


def test_token_info_failure_is_harmless(key, capsys):
    responses = happy_responses()
    responses["token_info"] = tool_error("token_info")
    responses["token_ohlcv"] = tool_error("token_ohlcv")
    code, _ = cli2(["PEPE", "--json"], FakeNansenClient(responses))
    data = json.loads(capsys.readouterr().out)
    assert code == 0
    # search price is still known, change is not
    assert data["price"]["price_usd"] == 4e-06 and data["price"]["change_pct"] is None


def test_price_change_prefers_ohlcv(key, capsys):
    code, _ = cli2(["PEPE", "--lang", "en"])
    out = capsys.readouterr().out
    # real OHLCV: last close 4.36928e-06 vs previous 4.37390e-06 -> -0.1%
    assert "Price: $0.000004 (-0.1% vs the previous daily close (UTC), source Nansen OHLCV)" in out
    assert "e-06" not in out


def test_price_context_from_token_info_when_ohlcv_fails(key, capsys):
    responses = happy_responses()
    responses["token_ohlcv"] = tool_error("token_ohlcv")
    cli2(["PEPE", "--lang", "en"], FakeNansenClient(responses))
    assert "Price: $0.000004 (-5.2% over 24h, source Nansen token_info)" in capsys.readouterr().out


def test_early_exit_cancels_sentiment_tasks(key, capsys):
    # token not found -> exit 3 without awaiting the (never-finishing) fetchers
    async def never(*a):
        await asyncio.sleep(3600)

    fake = FakeNansenClient(happy_responses())
    code = main(["NOPE"], client_factory=fake.factory, fng_fetcher=never,
                social_fetcher=never, env_file=None)
    assert code == 3


def test_raw_lunarcrush_dump_shows_path_not_key(key, capsys, monkeypatch):
    monkeypatch.setenv("LUNARCRUSH_API_KEY", FAKE_LC_KEY)
    cli2(["PEPE", "--raw"], social=social_const(sentiment=25))
    err = capsys.readouterr().err
    assert "GET https://lunarcrush.com/api4/public/coins/pepe/v1" in err
    assert FAKE_LC_KEY not in err


def test_raw_lunarcrush_dump_without_key_says_no_request(key, capsys):
    cli2(["PEPE", "--raw"])
    err = capsys.readouterr().err
    assert "=== lunarcrush status=not_configured" in err and "no request made" in err


# ======================= Sprint 3: REST backend end to end ==================================
from tests.conftest import real_responses  # noqa: E402


def test_real_rest_payloads_end_to_end(capsys):
    # No NANSEN_API_KEY at all: REST default works (proxy-injected credential).
    fake = FakeNansenClient(real_responses())
    code = main(["PEPE", "--lang", "en"], client_factory=fake.factory, fng_fetcher=fng_const(70),
                env_file=None)
    out = capsys.readouterr().out
    assert code == 0
    assert "Zalat Smart Money Verdict — Pepe (PEPE)\n" in out
    assert "Address: 0x6982508145454ce325ddbe47a25d4ec3d2311933" in out
    assert "Net flow: -$1.5k (12 wallets, avg flow (Nansen) $6.8k)" in out
    assert "Smart buyers vs sellers: $2.7k bought / $145.7k sold" in out
    assert "Top PnL traders net flow (context, not scored): -$165.3k (17 wallets)" in out
    assert "source Nansen OHLCV" in out and "holders 409,302" in out
    assert "Market-wide mood (whole crypto market" in out and "(70/100)" in out
    wbs_calls = [a for t, a in fake.calls if t == "token_who_bought_sold"]
    assert [a["request"]["buy_or_sell"] for a in wbs_calls] == ["BUY", "SELL"]


def test_real_rest_payloads_json(capsys):
    fake = FakeNansenClient(real_responses())
    main(["PEPE", "--json", "--period", "7d"], client_factory=fake.factory,
         fng_fetcher=fng_const(70), env_file=None)
    data = json.loads(capsys.readouterr().out)
    assert data["sm"]["flow_basis"] == "buy_sell" and data["sm"]["wallets"] == 53
    assert data["sm"]["flow_score"] == pytest.approx(
        -142508.33836082026 / (2694.2672884095823 + 145672.94049052984))
    assert data["sm"]["top_pnl"]["wallets"] == 78
    assert data["sm"]["buy"]["wallets"] == 6
    assert data["price"]["source"] == "nansen_ohlcv" and data["price"]["holders"] == 409302


def test_raw_and_verbose_show_request_ids(capsys):
    responses = real_responses()
    search = responses["general_search"]
    search.request_id, search.http_status, search.credits_remaining = "req-xyz", 200, 28090.0
    fail = ToolResult("token_recent_flows_summary", False, '{"error":"x","request_id":"req-bad"}',
                      True, "tool_error", reason="INVALID", http_status=422, request_id="req-bad")
    responses["token_recent_flows_summary"] = fail
    fake = FakeNansenClient(responses)
    code = main(["PEPE", "--raw", "-v"], client_factory=fake.factory, fng_fetcher=fng_const(70),
                env_file=None)
    err = capsys.readouterr().err
    assert code == 0
    assert "=== general_search ok=True http=200 request_id=req-xyz credits_remaining=28090" in err
    assert ("=== token_recent_flows_summary ok=False error=tool_error reason=INVALID "
            "http=422 request_id=req-bad") in err
    assert "general_search ok=True http=200 request_id=req-xyz" in err  # -v log line too


def test_rest_auth_error_exit_4_message(capsys):
    def boom(args):
        raise NansenAuthError("Nansen rejected the request (HTTP 401, request_id r1): "
                              "check NANSEN_API_KEY in .env (missing or invalid)")

    fake = FakeNansenClient({"general_search": boom})
    code = main(["PEPE"], client_factory=fake.factory, fng_fetcher=fng_const(70), env_file=None)
    assert code == 4
    assert ("Nansen rejected the request (HTTP 401, request_id r1): check NANSEN_API_KEY in .env "
            "(missing or invalid)") in capsys.readouterr().err


def test_rest_search_network_failure_exit_5_with_request_id(capsys):
    res = ToolResult("general_search", False, "HTTP 503", True, "network", reason="http_503",
                     http_status=503, request_id="req-503")
    fake = FakeNansenClient({"general_search": res})
    code = main(["PEPE"], client_factory=fake.factory, fng_fetcher=fng_const(70), env_file=None)
    err = capsys.readouterr().err
    assert code == 5 and "request_id req-503" in err


def test_default_client_factory_is_rest(capsys, monkeypatch):
    import zalat.nansen_rest as rest_mod

    made = []

    def fake_rest(settings):
        made.append(settings.backend)
        return FakeNansenClient(real_responses())

    monkeypatch.setattr(rest_mod, "NansenRESTClient", fake_rest)
    code = main(["PEPE"], fng_fetcher=fng_const(70), env_file=None)  # default client factory
    assert code == 0 and made == ["rest"]


def test_real_link_7d_distributing_via_volume_scale(capsys):
    responses = real_responses()
    responses["general_search"] = ok("general_search", fixture_text("real_search_link.json"))
    responses["token_recent_flows_summary"] = ok("token_recent_flows_summary",
                                                 fixture_text("real_link_flow_7d.json"))
    responses["token_who_bought_sold"] = ok("token_who_bought_sold", fixture_text("real_wbs_empty.json"))
    fake = FakeNansenClient(responses)
    main(["LINK", "--period", "7d", "--json"], client_factory=fake.factory,
         fng_fetcher=fng_const(70), env_file=None)
    data = json.loads(capsys.readouterr().out)
    assert data["token"]["address"].startswith("0x514910771a")
    assert data["sm"]["flow_basis"] == "volume" and data["sm"]["label"] == "Distributing"
    assert {"key": "no_sm_trades", "params": {}} in data["reasons"]


def test_real_empty_flow_and_empty_wbs_is_insufficient(capsys):
    responses = real_responses()
    responses["token_recent_flows_summary"] = ok("token_recent_flows_summary",
                                                 fixture_text("real_aave_flow_1d.json"))
    responses["token_who_bought_sold"] = ok("token_who_bought_sold", fixture_text("real_wbs_empty.json"))
    fake = FakeNansenClient(responses)
    main(["PEPE", "--lang", "en"], client_factory=fake.factory, fng_fetcher=fng_const(70),
         env_file=None)
    out = capsys.readouterr().out
    assert "Not enough smart-money data" in out
    assert "Net flow: no smart-money flow in this period" in out
    assert "$0 bought / $0 sold" in out


# ======================= Auto chain (no --chain) =======================================
_SOL_SEARCH = json.dumps({"tokens": [
    {"name": "SOL", "symbol": "SOL", "chain": "hyperliquid", "address": "SOL",
     "price": 123.0, "volume_24h": 9e9},
    {"name": "Wrapped SOL", "symbol": "SOL", "chain": "ethereum",
     "address": "0xd31a59c85ae9d8edefec411d448f90841571b89c", "price": 123.0, "volume_24h": 2e5},
    {"name": "Solana", "symbol": "SOL", "chain": "solana",
     "address": "So11111111111111111111111111111111111111112", "price": 123.1,
     "volume_24h": 3e9},
]})


def test_no_chain_searches_all_chains_and_picks_highest_volume(key, capsys):
    responses = happy_responses()
    responses["general_search"] = ok("general_search", _SOL_SEARCH)
    code, fake = cli(["SOL", "--period", "7d", "--lang", "en"], FakeNansenClient(responses))
    out = capsys.readouterr().out
    assert code == 0
    search = fake.calls[0]
    assert search[0] == "general_search" and "chain" not in search[1]
    # Perp listing skipped, low-volume wrapped copy on ethereum loses to native Solana.
    assert fake.calls[1][1]["request"]["chain"] == "solana"
    assert "Solana (SOL)" in out and "Chain: solana" in out


def test_explicit_chain_still_filters(key, capsys):
    responses = happy_responses()
    responses["general_search"] = ok("general_search", _SOL_SEARCH)
    code, fake = cli(["SOL", "--chain", "ethereum"], FakeNansenClient(responses))
    assert code == 0
    assert fake.calls[0][1]["chain"] == "ethereum"
    assert fake.calls[1][1]["request"]["chain"] == "ethereum"


def test_no_chain_not_found_message(key, capsys):
    responses = happy_responses()
    responses["general_search"] = ok("general_search", json.dumps({"tokens": []}))
    code, _ = cli(["NOPE"], FakeNansenClient(responses))
    assert code == 3
    assert "on any supported chain" in capsys.readouterr().err


def test_address_without_chain_defaults_to_ethereum(key, capsys):
    code, fake = cli(["--address", "0xabc"])
    assert code == 0
    assert fake.calls[0][1]["request"]["chain"] == "ethereum"
