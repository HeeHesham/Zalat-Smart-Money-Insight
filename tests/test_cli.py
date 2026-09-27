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
    assert "Smart money is buying into fear" in out
    assert "الأموال الذكية تشتري وسط الخوف" in out
    assert DISCLAIMER_EN in out and DISCLAIMER_AR in out
    assert [c[0] for c in fake.calls] == ["general_search", "token_recent_flows_summary",
                                          "token_who_bought_sold", "token_who_bought_sold"]
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
    assert "Not enough smart-money data" in out and "Crowd mood: Extreme Fear" in out


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


def test_missing_key_exit_2(capsys):
    code, fake = cli(["PEPE"])
    assert code == 2 and "NANSEN_API_KEY is not set" in capsys.readouterr().err
    assert fake.calls == []


def test_bad_args_exit_2(key, capsys):
    assert main([], env_file=None) == 2
    assert main(["PEPE", "--period", "2d"], env_file=None) == 2
    assert main(["PEPE", "--timeout", "0"], env_file=None) == 2


def test_token_not_found_exit_3(key, capsys):
    code, fake = cli(["NOPE"])
    assert code == 3 and "Could not find token 'NOPE'" in capsys.readouterr().err
    assert len(fake.calls) == 1


def test_search_tool_error_exit_3(key, capsys):
    code, _ = cli(["PEPE"], FakeNansenClient({"general_search": tool_error("general_search")}))
    assert code == 3 and "--address" in capsys.readouterr().err


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
