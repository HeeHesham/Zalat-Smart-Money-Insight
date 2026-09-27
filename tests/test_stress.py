"""Stress-test script with a fake client (offline)."""

import asyncio
import importlib.util
import json

from tests.conftest import FAKE_KEY, ROOT, FakeNansenClient, happy_responses, ok, tool_error
from zalat.config import Settings
from zalat.errors import NansenAuthError, NansenNetworkError
from zalat.nansen_mcp import ToolResult

_spec = importlib.util.spec_from_file_location("stress_test", ROOT / "scripts" / "stress_test.py")
stress = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stress)

SETTINGS = Settings(api_key=FAKE_KEY)


async def _nosleep(_s):
    return None


def _run(argv, fake):
    return asyncio.run(stress.main(argv, client_factory=fake.factory, settings=SETTINGS,
                                   sleep=_nosleep))


def _files_text(out):
    return "".join(p.read_text(encoding="utf-8") for p in out.rglob("*") if p.is_file())


def test_reaches_100_calls_and_writes_report(tmp_path, capsys):
    responses = happy_responses()
    # Leak the key into a tool response to prove it gets redacted from files.
    responses["token_recent_flows_summary"] = ok("token_recent_flows_summary",
                                                 f"| Segment | Net Flow |\n|--|--|\n| Smart Money | 1M |\n{FAKE_KEY}")
    fake = FakeNansenClient(responses)
    code = _run(["--tokens", "PEPE,UNI", "--out", str(tmp_path)], fake)
    assert code == 0
    assert len(fake.calls) == 100
    rep = json.loads((tmp_path / "stress_report.json").read_text(encoding="utf-8"))
    assert rep["total_calls"] == 100 and rep["status"] == "completed"
    assert rep["successes"] + rep["failures"] == 100
    assert set(rep["per_tool"]) == {"general_search", "token_recent_flows_summary",
                                    "token_who_bought_sold", "token_info"}
    for t in rep["per_tool"].values():
        assert {"calls", "ok", "fail", "avg_ms", "p95_ms"} <= set(t)
    # UNI is not in the PEPE search sample -> its searches don't resolve.
    assert rep["parse_stats"]["search_no_match"] > 0
    assert rep["parse_stats"]["flows_parsed"] > 0
    assert list((tmp_path / "raw").glob("*.txt"))
    assert FAKE_KEY not in _files_text(tmp_path)
    summary = capsys.readouterr().out
    assert "total calls : 100" in summary and FAKE_KEY not in summary


def test_counts_failures_by_tool_and_reason(tmp_path, capsys):
    responses = happy_responses()
    responses["token_who_bought_sold"] = tool_error("token_who_bought_sold", "unclassified_failure")
    fake = FakeNansenClient(responses)
    code = _run(["--tokens", "PEPE", "--min-calls", "30", "--out", str(tmp_path)], fake)
    rep = json.loads((tmp_path / "stress_report.json").read_text(encoding="utf-8"))
    assert code == 0 and rep["total_calls"] == 30
    wbs = rep["per_tool"]["token_who_bought_sold"]
    assert wbs["ok"] == 0 and wbs["fail"] == wbs["calls"] > 0
    assert rep["error_reasons"]["token_who_bought_sold"] == {"unclassified_failure": wbs["calls"]}
    assert "failed: unclassified_failure" in capsys.readouterr().out


def test_retries_network_errors_and_counts_them(tmp_path):
    attempts = {"n": 0}

    def flaky(args):
        attempts["n"] += 1
        if attempts["n"] % 2:
            return ToolResult("general_search", False, "timeout", False, "network", reason="network")
        return happy_responses()["general_search"]

    responses = happy_responses()
    responses["general_search"] = flaky
    fake = FakeNansenClient(responses)
    _run(["--tokens", "PEPE", "--min-calls", "20", "--out", str(tmp_path)], fake)
    rep = json.loads((tmp_path / "stress_report.json").read_text(encoding="utf-8"))
    assert rep["total_calls"] == 20
    assert rep["error_reasons"]["general_search"]["network"] >= 1
    assert any(c["attempt"] == 2 for c in rep["calls"])


def test_auth_abort(tmp_path):
    def boom(args):
        raise NansenAuthError("Nansen rejected the API key (HTTP 401).")

    code = _run(["--out", str(tmp_path)], FakeNansenClient({"general_search": boom}))
    rep = json.loads((tmp_path / "stress_report.json").read_text(encoding="utf-8"))
    assert code == 4 and rep["status"] == "aborted_auth"


def test_unreachable_abort(tmp_path):
    fake = FakeNansenClient(enter_exc=NansenNetworkError(f"nope {FAKE_KEY}"))
    code = _run(["--out", str(tmp_path)], fake)
    assert code == 5
    assert FAKE_KEY not in _files_text(tmp_path)


def test_empty_token_list_exits_2_without_calls(tmp_path, capsys):
    for tokens in (",", "", " , "):
        fake = FakeNansenClient(happy_responses())
        code = _run(["--tokens", tokens, "--out", str(tmp_path)], fake)
        assert code == 2 and fake.calls == []
    assert "--tokens" in capsys.readouterr().err


def test_invalid_periods_exit_2(tmp_path, capsys):
    fake = FakeNansenClient(happy_responses())
    assert _run(["--periods", "1d,2d", "--out", str(tmp_path)], fake) == 2
    assert fake.calls == [] and "2d" in capsys.readouterr().err


def test_round_with_zero_calls_breaks_loop(tmp_path):
    run = stress.StressRun(FakeNansenClient(happy_responses()), SETTINGS, tmp_path, 0, 50, _nosleep)
    asyncio.run(asyncio.wait_for(run.run([], "ethereum", ["1d"], 10), timeout=5))
    assert run.total == 0


def test_stress_uses_side_aware_parsing(tmp_path):
    fake = FakeNansenClient(happy_responses())
    _run(["--tokens", "PEPE", "--min-calls", "12", "--out", str(tmp_path)], fake)
    rep = json.loads((tmp_path / "stress_report.json").read_text(encoding="utf-8"))
    assert rep["parse_stats"].get("wbs_parsed", 0) >= 2
    assert "wbs_unparsed" not in rep["parse_stats"]


def test_token_info_in_rotation_and_lunarcrush_never_called(tmp_path, monkeypatch):
    import zalat.lunarcrush as lc

    async def forbidden(*a, **k):
        raise AssertionError("stress test must not call LunarCrush")

    monkeypatch.setattr(lc, "fetch_social", forbidden)
    s = Settings(api_key=FAKE_KEY, lunarcrush_key="lc-SECRET-should-not-leak")
    fake = FakeNansenClient(happy_responses())
    code = asyncio.run(stress.main(["--tokens", "PEPE", "--out", str(tmp_path)],
                                   client_factory=fake.factory, settings=s, sleep=_nosleep))
    assert code == 0 and len(fake.calls) == 100
    assert {c[0] for c in fake.calls} == {"general_search", "token_recent_flows_summary",
                                         "token_who_bought_sold", "token_info"}
    rep = json.loads((tmp_path / "stress_report.json").read_text(encoding="utf-8"))
    assert rep["total_calls"] == 100 and rep["per_tool"]["token_info"]["calls"] > 0
    assert rep["parse_stats"]["token_info_parsed"] > 0
    assert "lc-SECRET-should-not-leak" not in _files_text(tmp_path)
    assert not hasattr(stress, "fetch_social")
