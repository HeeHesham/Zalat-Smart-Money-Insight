"""Bilingual HTML card (--html) and the 3-section output layout / EN-AR parity."""

import itertools
import json
import re

import pytest

from tests.conftest import FAKE_KEY, FakeNansenClient, fng_const, real_responses
from zalat.card import (
    _isolate_ltr,
    default_card_path,
    main as card_main,
    nice_max,
    render_card,
    verdict_from_dict,
    write_card,
)
from zalat.cli import main
from zalat.fng import CrowdSignal, signal_from_value
from zalat.lunarcrush import SocialSignal, social_bucket
from zalat.nansen_mcp import TokenRef
from zalat.parsing import BuySellSide, SmFlow
from zalat.render import build_sections, display_name, render_json, render_text, section_texts
from zalat.verdict import PriceContext, build_sm_signal, decide

LINK = TokenRef("LINK", "ChainLink Token", "0x514910771af9ca656af840dff83e8264ecf986ca", "ethereum",
                6.4e6, 14.07)
HEADERS_EN = ["1 · ON-CHAIN SMART MONEY (Nansen)", "2 · MARKET SENTIMENT", "3 · FINAL VERDICT"]


def _social(state):
    if state == "ok":
        return SocialSignal("ok", "LINK", 25, social_bucket(25), -0.5, galaxy_score=61)
    if state == "denied":
        return SocialSignal("not_authorized", "LINK", http_status=402)
    return SocialSignal("not_configured", "LINK") if state == "off" else None


FLOWS = {
    "rest": (SmFlow(-117_658.9, None, None, 4, {}, 26_950.6), BuySellSide(13_600, 5), BuySellSide(132_000, 5)),
    "inout": (SmFlow(1.2e6, 1.5e6, 3e5, 12, {}), BuySellSide(8e5, 3), BuySellSide(2e5, 2)),
    "empty": (SmFlow(0.0, None, None, 0, {}), BuySellSide(0, 0), BuySellSide(0, 0)),
    "none": (None, None, None),
}
PRICES = {
    "full": PriceContext(14.07, -0.01, "prev_close", "nansen_ohlcv", "Flat", 1.05e10, 2.04e7, 642713),
    "move": PriceContext(14.07, -25.0, "24h", "lunarcrush", "Falling"),
    "none": None,
}


def make(fng=70, social="off", flow="rest", price="full", truncated=False, tok=LINK):
    f, b, s = FLOWS[flow]
    sm = build_sm_signal(f, b, s, top_pnl=SmFlow(-6.6e6, None, None, 67, {}) if flow == "rest" else None,
                         volume_24h=tok.volume_24h, wbs_truncated=truncated)
    market = signal_from_value(fng) if fng is not None else CrowdSignal(False, error="x")
    return decide(tok, "7d", sm, market, _social(social), PRICES[price])


def _split(text):
    """Header block + sections, keyed by position."""
    blocks = [[]]
    for ln in text.rstrip("\n").split("\n"):
        if ln.startswith("━━ "):
            blocks.append([ln])
        else:
            blocks[-1].append(ln)
    return blocks


# ---- display name -------------------------------------------------------------------------
@pytest.mark.parametrize("tok, name", [
    (TokenRef("LINK", "ChainLink Token", "0x1", "ethereum"), "ChainLink (LINK)"),
    (TokenRef("UNI", "Uniswap", "0x1", "ethereum"), "Uniswap (UNI)"),
    (TokenRef("PEPE", "Pepe", "0x1", "ethereum"), "Pepe (PEPE)"),
    (TokenRef("ENA", "ENA", "0x1", "ethereum"), "ENA"),
    (TokenRef("ABC", "", "0x1", "ethereum"), "ABC"),
    (TokenRef("X", "Token", "0x1", "ethereum"), "Token (X)"),
    (TokenRef("", "", "0x514910771af9ca656af840dff83e8264ecf986ca", "ethereum"), "0x5149…86ca"),
])
def test_display_name(tok, name):
    assert display_name(tok) == name


def test_title_names_the_token():
    en = render_text(make(), "en")
    assert en.startswith("Zalat Smart Money Verdict — ChainLink (LINK)\n")
    assert render_text(make(), "ar").startswith("حكم زلط للأموال الذكية — ChainLink (LINK)\n")


# ---- sections -------------------------------------------------------------------------------
def test_three_titled_sections_in_order():
    blocks = _split(render_text(make(), "en"))
    assert len(blocks) == 4
    assert [b[0] for b in blocks[1:]] == [f"━━ {h} ━━" for h in HEADERS_EN]
    header, s1, s2, s3 = ("\n".join(b) for b in blocks)
    assert "Chain: ethereum · Lookback: 7d · Generated:" in header and "UTC" in header
    assert "Price: $14.07" in header and "holders 642,713" in header
    # 1: only Nansen smart-money data
    assert "Smart money: Distributing" in s1 and "Net flow: -$117.7k" in s1
    assert "Top PnL traders" in s1 and "Flow scored against:" in s1
    for word in ("Fear & Greed", "Market-wide mood", "LunarCrush", "social", "VERDICT"):
        assert word not in s1
    # 2: only sentiment
    assert "Market-wide mood (whole crypto market" in s2 and "Token social sentiment" in s2
    for word in ("Net flow", "Smart money:", "bought", "VERDICT", "Confidence"):
        assert word not in s2
    # 3: verdict
    assert s3.split("\n")[1].startswith(">>> DISAGREEMENT")
    assert "VERDICT:" in s3 and "Confidence:" in s3 and "Why:" in s3
    assert s3.rstrip().endswith("Not financial advice. For research and education only.")


def test_notes_go_to_the_right_section():
    v = make(fng=15, social="ok", price="move", truncated=True)
    _, s1, s2, s3 = ("\n".join(b) for b in _split(render_text(v, "en")))
    assert "cut at the top 400 wallets" in s1
    assert "this token's crowd diverges" not in s2  # both fearful here
    assert "price falling while smart money sells" in s3
    v2 = make(fng=85, social="ok")
    assert "this token's crowd diverges from the overall market mood" in \
        "\n".join(_split(render_text(v2, "en"))[2])


STATES = list(itertools.product((10, 50, 90, None), ("off", "ok", "denied", None),
                                ("rest", "inout", "empty", "none"), ("full", "none")))

# English words allowed inside Arabic lines: proper nouns / sources / chains / tickers.
AR_ALLOWED = {"Nansen", "LunarCrush", "alternative", "me", "OHLCV", "Galaxy", "Score", "ethereum",
              "ChainLink", "LINK", "UTC", "HTTP", "BTC"}


def _latin_leaks(line: str) -> set[str]:
    line = re.sub(r"0x[0-9a-fA-F]+(?:…[0-9a-fA-F]+)?", " ", line)  # addresses
    line = re.sub(r"--[a-z-]+", " ", line)                         # CLI flags
    line = re.sub(r"\b[A-Z][A-Z0-9_]{2,}\b", " ", line)            # env vars, acronyms
    line = line.replace("token_info", " ")
    line = re.sub(r"[$+\-]?\d[\d.,]*[kMBT]?", " ", line)            # numbers ($1.2k, 7d...)
    return {w for w in re.findall(r"[A-Za-z]{2,}", line)} - AR_ALLOWED


@pytest.mark.parametrize("fng, social, flow, price", STATES)
def test_en_ar_parity(fng, social, flow, price):
    v = make(fng, social, flow, price)
    en, ar = _split(render_text(v, "en")), _split(render_text(v, "ar"))
    assert len(en) == len(ar) == 4
    assert [len(b) for b in en] == [len(b) for b in ar]
    for block in ar:
        for line in block:
            assert not _latin_leaks(line), (line, _latin_leaks(line))
    # JSON carries the same structure for both languages
    data = json.loads(render_json(v))
    assert [len(s["lines"]) for s in data["sections"]["en"]] == \
        [len(s["lines"]) for s in data["sections"]["ar"]]


def test_arabic_has_no_na():
    ar = render_text(make(flow="none", price="none"), "ar")
    assert "n/a" not in ar and "غير متاح" in ar


def test_json_new_fields_keep_old_ones():
    data = json.loads(render_json(make()))
    assert data["display_name"] == "ChainLink (LINK)"
    assert data["sections"]["en"][1]["title"] == HEADERS_EN[0]
    assert data["sections"]["ar"][0]["title"] is None
    for key in ("kind", "sm", "market_mood", "social", "price", "crowd_source", "headline",
                "reasons", "notes", "disclaimer", "token"):
        assert key in data


def test_build_sections_shape():
    secs = build_sections(make())
    assert [s.header for s in secs] == [None, "sec_onchain", "sec_sentiment", "sec_verdict"]
    assert section_texts(make(), "ar")[1][0] == "1 · الأموال الذكية على السلسلة (Nansen)"


# ---- card ----------------------------------------------------------------------------------
def test_card_is_self_contained_and_bilingual(tmp_path):
    html = render_card(make())
    assert html.startswith("<!doctype html>")
    assert not re.search(r'(src|href)\s*=\s*["\']?https?:', html, re.I)
    assert "@import" not in html and "url(" not in html and "<link" not in html
    assert 'dir="rtl"' in html and 'lang="ar"' in html and 'lang="en"' in html
    assert "ChainLink (LINK)" in html and "Warning (Bearish)" in html
    assert "تحذير: بيع وسط طمع السوق" in html
    for head in HEADERS_EN:
        assert head in html
    assert html.count("<svg") == 3  # buy/sell bars, net flow, F&G gauge
    assert "Not configured (needs a paid LunarCrush plan)" in html  # social placeholder
    assert html.count('class="sr-only"') == 3  # one data table per chart
    assert "prefers-color-scheme: dark" in html and "background: var(--page)" in html
    assert 'class="mark"' in html and "data-tip=" in html
    assert "#2a78d6" in html and "#e34948" in html  # validated diverging pair


def test_card_placeholders_never_fake_bars():
    html = render_card(make(fng=None, flow="empty", social="denied"))
    assert html.count("<svg") == 0
    assert "no smart-money flow in this period" in html
    assert "no smart-money buys or sells in this period" in html
    assert "Market-wide mood (whole crypto market): unavailable" in html
    assert "HTTP 402" in html
    html2 = render_card(make(flow="none", social="ok"))
    assert "Data unavailable for this period" in html2
    assert html2.count("<svg") == 2  # F&G + LunarCrush gauges only


def test_net_flow_bar_direction_and_labels():
    neg = render_card(make(flow="rest"))
    assert "-$117.7k" in neg and "var(--neg)" in neg
    pos = render_card(make(flow="inout"))
    assert "+$1.2M" in pos and "var(--pos)" in pos
    # symmetric domain = max(|net|, bought + sold) rounded up
    assert "-$200.0k" in neg and "+$200.0k" in neg


def test_nice_max_and_isolation():
    assert [nice_max(x) for x in (0, 7, 145_672, 1.2e6, 250)] == [1.0, 10, 200_000, 2e6, 250]
    out = _isolate_ltr("الدرجة -0.96 و 2026-09-27 21:07 UTC")
    assert '<bdi dir="ltr">-0.96</bdi>' in out and '<bdi dir="ltr">2026-09-27 21:07 UTC</bdi>' in out
    assert _isolate_ltr("<script>") == "&lt;<bdi dir=\"ltr\">script</bdi>&gt;"


def test_default_card_path_and_write(tmp_path):
    v = make()
    p = default_card_path(v, tmp_path)
    assert re.fullmatch(r"zalat_LINK_7d_\d{8}-\d{4}\.html", p.name)
    written = write_card(v, tmp_path / "sub" / "c.html")
    assert written.exists() and "ChainLink (LINK)" in written.read_text(encoding="utf-8")
    addr_only = make(tok=TokenRef("", "", LINK.address, "ethereum"))
    assert default_card_path(addr_only).name.startswith("zalat_0x514986ca_7d_")


def test_from_json_roundtrip(tmp_path, capsys):
    v = make(social="ok", truncated=True)
    src = tmp_path / "v.json"
    src.write_text(render_json(v), encoding="utf-8")
    rebuilt = verdict_from_dict(json.loads(src.read_text(encoding="utf-8")))
    assert render_text(rebuilt, "both") == render_text(v, "both")
    out = tmp_path / "card.html"
    assert card_main(["--from-json", str(src), "--out", str(out)]) == 0
    assert str(out) in capsys.readouterr().out and out.exists()
    assert card_main(["--from-json", str(tmp_path / "missing.json")]) == 2


def test_cli_html_default_path_and_no_key(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NANSEN_API_KEY", FAKE_KEY)
    fake = FakeNansenClient(real_responses())
    code = main(["PEPE", "--html"], client_factory=fake.factory, fng_fetcher=fng_const(70),
                env_file=None)
    out = capsys.readouterr().out
    assert code == 0
    m = re.search(r"HTML card: (cards/zalat_PEPE_1d_\d{8}-\d{4}\.html)", out)
    assert m, out[-300:]
    html = (tmp_path / m.group(1)).read_text(encoding="utf-8")
    assert "Pepe (PEPE)" in html and FAKE_KEY not in html


def test_cli_html_with_json_keeps_stdout_json(tmp_path, capsys):
    fake = FakeNansenClient(real_responses())
    target = tmp_path / "x.html"
    code = main(["PEPE", "--json", "--html", str(target)], client_factory=fake.factory,
                fng_fetcher=fng_const(70), env_file=None)
    cap = capsys.readouterr()
    assert code == 0 and json.loads(cap.out)["display_name"] == "Pepe (PEPE)"
    assert f"HTML card: {target}" in cap.err and target.exists()
