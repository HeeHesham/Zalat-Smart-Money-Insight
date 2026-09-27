"""Rendering: bilingual text, disclaimers, JSON validity, number formatting."""

import json

import pytest

from zalat import DISCLAIMER_AR, DISCLAIMER_EN
from zalat.fng import CrowdSignal, signal_from_value
from zalat.i18n import KIND_TEXT, LABELS, STRINGS, fmt_score, fmt_usd, fmt_wallets, t
from zalat.nansen_mcp import TokenRef
from zalat.parsing import BuySellSide, SmFlow
from zalat.render import render_json, render_text
from zalat.verdict import KINDS, build_sm_signal, decide

TOK = TokenRef("PEPE", "Pepe", "0x6982508145454ce325ddbe47a25d4ec3d2311933", "ethereum")


def _verdict(fng=20, flow=SmFlow(1.2e6, 1.5e6, 3e5, 12, {"Segment": "Smart Money"})):
    sm = build_sm_signal(flow, BuySellSide(8e5, 3), BuySellSide(2e5, 2))
    crowd = signal_from_value(fng) if fng is not None else CrowdSignal(False)
    return decide(TOK, "1d", sm, crowd)


def test_i18n_tables_are_complete():
    assert set(KIND_TEXT["en"]) == set(KIND_TEXT["ar"]) == set(KINDS)
    assert set(STRINGS["en"]) == set(STRINGS["ar"])
    assert set(LABELS["en"]) == set(LABELS["ar"])


def test_fmt():
    assert fmt_usd(1_234_567) == "$1.2M"
    assert fmt_usd(-3400) == "-$3.4k"
    assert fmt_usd(2.5e9) == "$2.5B"
    assert fmt_usd(12) == "$12"
    assert fmt_usd(0.5) == "$0.50"
    assert fmt_usd(None) == "n/a"
    assert fmt_score(0.4211) == "+0.42" and fmt_score(-0.1) == "-0.10" and fmt_score(None) == "n/a"


def test_t_formats_and_falls_back():
    assert t("low_wallets", "en", n=2) == "only 2 smart wallets involved"
    assert "2" in t("low_wallets", "ar", n=2)
    assert t("unknown_key", "ar") == "unknown_key"


def test_english_text():
    out = render_text(_verdict(), "en")
    assert "Smart money is buying into fear" in out
    assert "Disagreement: YES" in out
    assert "market-wide" in out
    assert "+$1.2M" in out and "$800.0k bought" in out
    assert out.rstrip().endswith(DISCLAIMER_EN)
    assert "ليست" not in out


def test_arabic_text():
    out = render_text(_verdict(), "ar")
    assert "الأموال الذكية تشتري وسط الخوف" in out
    assert "للسوق كله" in out  # market-wide note in Arabic
    assert "+$1.2M" in out  # Western digits kept
    assert out.rstrip().endswith(DISCLAIMER_AR)
    assert "Not financial advice" not in out


def test_both_languages():
    out = render_text(_verdict(), "both")
    assert out.index("VERDICT:") < out.index("الحكم:")
    assert DISCLAIMER_EN in out and DISCLAIMER_AR in out


@pytest.mark.parametrize("fng", [10, 50, 90, None])
@pytest.mark.parametrize("lang", ["en", "ar", "both"])
def test_every_kind_renders(fng, lang):
    out = render_text(_verdict(fng=fng), lang)
    assert out.strip()


def test_insufficient_data_render():
    v = decide(TOK, "1d", build_sm_signal(None, None, None), signal_from_value(30))
    out = render_text(v, "both")
    assert "Smart money: Unavailable" in out and "الأموال الذكية: غير متاح" in out
    assert "Crowd mood: Fear (30/100)" in out


def test_json_is_valid_and_complete():
    data = json.loads(render_json(_verdict()))
    assert data["kind"] == "CONTRARIAN_BULLISH"
    assert data["disagreement"] is True
    assert data["token"]["address"] == TOK.address
    assert data["sm"]["flow"]["source_columns"] == ["Segment"]
    assert data["headline"]["ar"] == "الأموال الذكية تشتري وسط الخوف"
    assert data["disclaimer"] == {"en": DISCLAIMER_EN, "ar": DISCLAIMER_AR}
    assert data["crowd"]["scope"].startswith("market-wide")
    assert "api_key" not in json.dumps(data)


def test_json_with_unavailable_parts():
    v = decide(TOK, "1d", build_sm_signal(None, None, None), CrowdSignal(False, error="x"))
    data = json.loads(render_json(v))
    assert data["kind"] == "INSUFFICIENT_DATA"
    assert {"key": "crowd_unavailable", "params": {}} in data["reasons"]


@pytest.mark.parametrize("n, en, ar", [(1, "1 wallet", "1 محفظة"), (2, "2 wallets", "2 محفظتان"),
                                       (3, "3 wallets", "3 محافظ"), (10, "10 wallets", "10 محافظ"),
                                       (11, "11 wallets", "11 محفظة"), (150, "150 wallets", "150 محفظة")])
def test_wallet_plurals(n, en, ar):
    assert fmt_wallets(n, "en") == en
    assert fmt_wallets(n, "ar") == ar


def test_arabic_wording():
    out = render_text(_verdict(), "ar")
    assert "وارد $1.5M / صادر $300.0k" in out
    assert "12 محفظة" in out
    assert "داخل" not in out and "خارج" not in out
    assert KIND_TEXT["ar"]["NEUTRAL"][2] == "لا يوجد اتجاه قوي لدى الأموال الذكية أو لدى الجمهور."
    assert "يسيطر الطمع على الجمهور" in KIND_TEXT["ar"]["WARNING_BEARISH"][2]
    weak = t("weak_signal", "ar", s=0.12)
    assert "|" not in weak and "<" not in weak and "0.12" in weak


def test_banner_only_for_disagreement():
    assert render_text(_verdict(fng=20), "en").splitlines()[1].startswith(">>> DISAGREEMENT")
    assert ">>>" not in render_text(_verdict(fng=80), "both")
    assert ">>>" not in render_text(_verdict(fng=None), "both")


def test_no_dead_i18n_keys():
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent.parent / "zalat"
    code = "".join(p.read_text(encoding="utf-8") for p in root.glob("*.py") if p.name != "i18n.py")
    for key in STRINGS["en"]:
        assert re.search(rf'["\']{key}["\']', code), f"unused i18n key: {key}"


def test_token_label():
    from zalat.render import token_label

    assert token_label(TokenRef("PEPE", "PEPE", "0x1", "ethereum")) == "PEPE"
    assert token_label(TokenRef("PEPE", "", "0x1", "ethereum")) == "PEPE"
    assert token_label(TokenRef("PEPE", "Pepe", "0x1", "ethereum")) == "PEPE (Pepe)"
