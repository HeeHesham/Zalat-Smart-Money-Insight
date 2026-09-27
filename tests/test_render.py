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
    assert set(KIND_TEXT["en"]) == set(KIND_TEXT["ar"]) == {"token_social", "market_mood"}
    for lang in ("en", "ar"):
        for source in ("token_social", "market_mood"):
            assert set(KIND_TEXT[lang][source]) == set(KINDS)
    assert set(STRINGS["en"]) == set(STRINGS["ar"])
    assert set(LABELS["en"]) == set(LABELS["ar"])


def test_fmt():
    assert fmt_usd(1_234_567) == "$1.2M"
    assert fmt_usd(-3400) == "-$3.4k"
    assert fmt_usd(2.5e9) == "$2.5B"
    assert fmt_usd(12) == "$12"
    assert fmt_usd(0.5) == "$0.50"
    assert fmt_usd(0) == fmt_usd(0.0) == "$0"
    assert fmt_usd(None) == "n/a"
    assert fmt_score(0.4211) == "+0.42" and fmt_score(-0.1) == "-0.10" and fmt_score(None) == "n/a"


def test_t_formats_and_falls_back():
    assert t("low_wallets", "en", n=2) == "few smart-money wallets involved (only 2 wallets)"
    assert t("low_wallets", "en", n=1) == "few smart-money wallets involved (only 1 wallet)"
    assert "1 wallets" not in t("low_wallets", "en", n=1)
    assert "2 محفظتان" in t("low_wallets", "ar", n=2)
    assert "1 محفظة" in t("low_wallets", "ar", n=1)
    assert t("unknown_key", "ar") == "unknown_key"


def test_english_text():
    out = render_text(_verdict(), "en")
    assert "Smart money is buying while the overall crypto market is fearful (market-wide mood, not this token)" in out
    assert "Disagreement: YES" in out
    assert "NOT specific to Pepe (PEPE)" in out
    assert "+$1.2M" in out and "$800.0k bought" in out
    assert out.rstrip().endswith(DISCLAIMER_EN)
    assert "ليست" not in out


def test_arabic_text():
    out = render_text(_verdict(), "ar")
    assert "الأموال الذكية تشتري بينما يسود الخوف سوق الكريبتو بأكمله (مزاج السوق العام، وليس هذه العملة)" in out
    assert "ليس خاصاً بـ Pepe (PEPE)" in out  # market-wide label in Arabic
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
    assert "NOT specific to Pepe (PEPE)): Fear (30/100)" in out


def test_json_is_valid_and_complete():
    data = json.loads(render_json(_verdict()))
    assert data["kind"] == "CONTRARIAN_BULLISH"
    assert data["disagreement"] is True
    assert data["token"]["address"] == TOK.address
    assert data["sm"]["flow"]["source_columns"] == ["Segment"]
    assert data["headline"]["ar"] == "الأموال الذكية تشتري بينما يسود الخوف سوق الكريبتو بأكمله (مزاج السوق العام، وليس هذه العملة)"
    assert data["crowd_source"] == "market_mood"
    assert "crowd" not in data  # renamed to market_mood
    assert data["disclaimer"] == {"en": DISCLAIMER_EN, "ar": DISCLAIMER_AR}
    assert data["market_mood"]["scope"].startswith("market-wide")
    assert data["social"]["status"] == "not_configured"
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
    assert KIND_TEXT["ar"]["market_mood"]["NEUTRAL"][2] == \
        "لا يوجد اتجاه قوي لدى الأموال الذكية أو في مزاج السوق العام."
    assert "يسيطر الطمع على سوق الكريبتو بأكمله" in KIND_TEXT["ar"]["market_mood"]["WARNING_BEARISH"][2]
    weak = t("weak_signal", "ar", s=0.12)
    assert "|" not in weak and "<" not in weak and "0.12" in weak


def test_banner_only_for_disagreement():
    lines = render_text(_verdict(fng=20), "en").splitlines()
    assert lines[lines.index("━━ 3 · FINAL VERDICT ━━") + 1].startswith(">>> DISAGREEMENT")
    assert ">>>" not in render_text(_verdict(fng=80), "both")
    assert ">>>" not in render_text(_verdict(fng=None), "both")


def test_no_dead_i18n_keys():
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent.parent / "zalat"
    code = "".join(p.read_text(encoding="utf-8") for p in root.glob("*.py") if p.name != "i18n.py")
    # Keys built dynamically in code (f-strings / t() internals):
    dynamic = ("source_", "social_status_", "crowd_name_", "window_", "basis_")
    internal = {"fallback_clause"}
    for key in STRINGS["en"]:
        if key.startswith(dynamic) or key in internal:
            continue
        assert re.search(rf'["\']{key}["\']', code), f"unused i18n key: {key}"
    assert re.search(r'f"source_\{', code) and re.search(r'f"social_status_\{', code)


def test_token_label():
    from zalat.render import token_label

    assert token_label(TokenRef("PEPE", "PEPE", "0x1", "ethereum")) == "PEPE"
    assert token_label(TokenRef("PEPE", "", "0x1", "ethereum")) == "PEPE"
    assert token_label(TokenRef("PEPE", "Pepe", "0x1", "ethereum")) == "Pepe (PEPE)"


def test_small_volume_reason_rendered_both_languages():
    v = decide(TOK, "1d", build_sm_signal(SmFlow(40, 40, 0, None, {}), None, None), signal_from_value(15))
    en, ar = render_text(v, "en"), render_text(v, "ar")
    assert "small smart-money volume" in en
    assert "حجم تداول الأموال الذكية صغير" in ar
    assert ">>>" not in en  # dust must not trigger the disagreement banner


def test_address_only_token_label_and_json_symbol():
    tok = TokenRef("", "", "0x6982508145454ce325ddbe47a25d4ec3d2311933", "ethereum")
    v = decide(tok, "1d", build_sm_signal(None, None, None), signal_from_value(40))
    assert "Zalat Smart Money Verdict — 0x6982…1933\n" in render_text(v, "en")
    data = json.loads(render_json(v))
    assert data["token"]["symbol"] == ""
    assert data["token"]["address"] == tok.address


# ======================= Sprint 2: honest labelling, social, price =======================
import itertools  # noqa: E402

from zalat.i18n import fmt_pct, fmt_price, kind_text  # noqa: E402
from zalat.lunarcrush import SocialSignal, social_bucket  # noqa: E402
from zalat.verdict import PriceContext  # noqa: E402

AR_NOT_SPECIFIC = "ليس خاصاً بـ"


def _social(sentiment=25, status="ok", **kw):
    if status != "ok":
        return SocialSignal(status, "PEPE", **kw)
    return SocialSignal("ok", "PEPE", sentiment, social_bucket(sentiment), (sentiment - 50) / 50,
                        galaxy_score=65, price_usd=4.1e-06, pct_change_24h=-5.2)


def _v2(fng=20, social=None, price=None, score_flow=SmFlow(1.2e6, 1.5e6, 3e5, 12, {})):
    sm = build_sm_signal(score_flow, BuySellSide(8e5, 3), BuySellSide(2e5, 2))
    market = signal_from_value(fng) if fng is not None else CrowdSignal(False)
    return decide(TOK, "1d", sm, market, social, price)


@pytest.mark.parametrize("x, out", [(4e-06, "$0.000004"), (0.000358, "$0.000358"),
                                    (0.145946, "$0.1459"), (1234.5, "$1,235"), (7.85, "$7.85"),
                                    (999.95, "$1,000"), (None, "n/a")])
def test_fmt_price(x, out):
    assert fmt_price(x) == out


def test_fmt_pct():
    assert (fmt_pct(3.24), fmt_pct(-12), fmt_pct(None)) == ("+3.2%", "-12.0%", "n/a")
    assert fmt_pct(-0.0106) == fmt_pct(0.04) == fmt_pct(0) == "0.0%"


def test_kind_text_by_source():
    assert "social crowd is bearish" in kind_text("CONTRARIAN_BULLISH", "en", "token_social")[1]
    assert kind_text("CONTRARIAN_BULLISH", "en", "market_mood")[1].endswith(
        "(market-wide mood, not this token)")
    assert kind_text("SM_ONLY", "en", None) == kind_text("SM_ONLY", "en", "token_social")


@pytest.mark.parametrize("fng, social, flow", list(itertools.product(
    (10, 50, 90),
    (None, "ok_bear", "ok_bull", "not_configured", "not_authorized"),
    ("buy", "sell", "none"),
)))
def test_fng_value_always_labelled_market_wide(fng, social, flow):
    """Invariant: any rendered F&G value sits on a line that says it is market-wide."""
    sig = {None: None, "ok_bear": _social(25), "ok_bull": _social(75),
           "not_configured": _social(status="not_configured"),
           "not_authorized": _social(status="not_authorized", http_status=402)}[social]
    f = {"buy": SmFlow(1.2e6, 1.5e6, 3e5, 12, {}), "sell": SmFlow(-1.2e6, 3e5, 1.5e6, 12, {}),
         "none": None}[flow]
    v = _v2(fng, sig, PriceContext(4e-06, -5.2, "24h", "nansen_token_info", "Falling"), f)
    en, ar = render_text(v, "en"), render_text(v, "ar")
    marker = f"({fng}/100)"
    en_lines = [ln for ln in en.splitlines() if marker in ln]
    ar_lines = [ln for ln in ar.splitlines() if marker in ln]
    assert len(en_lines) == 1 and len(ar_lines) == 1
    assert "NOT specific to" in en_lines[0] and "whole crypto market" in en_lines[0]
    assert AR_NOT_SPECIFIC in ar_lines[0]
    assert "/100" not in en.replace(marker, "")  # nothing else looks like an F&G reading
    assert "Crowd mood" not in en and "e-0" not in en + ar


def test_social_primary_render():
    v = _v2(fng=85, social=_social(25))
    en = render_text(v, "en")
    assert "Smart money is buying while this token's social crowd is bearish" in en
    assert ">>> DISAGREEMENT: SMART MONEY vs TOKEN'S SOCIAL CROWD <<<" in en
    assert "Token social sentiment (PEPE, LunarCrush): Bearish - 25% positive, Galaxy Score 65" in en
    assert "Secondary context - Market-wide mood (whole crypto market" in en
    assert "this token's crowd diverges from the overall market mood" in en
    ar = render_text(v, "ar")
    assert "الأموال الذكية تشتري بينما جمهور العملة على وسائل التواصل متشائم" in ar
    assert "سياق ثانوي - مزاج السوق العام" in ar
    assert "not configured" not in en


def test_not_configured_note_both_languages():
    v = _v2(social=_social(status="not_configured"))
    assert ("Token social sentiment: not configured - needs a paid LunarCrush API plan "
            "(set LUNARCRUSH_API_KEY). Future work; this verdict compares smart money with "
            "market-wide mood instead.") in render_text(v, "en")
    assert ("المشاعر الاجتماعية الخاصة بالعملة: غير مُفعَّلة - تتطلب اشتراكاً مدفوعاً في LunarCrush "
            "(عيّن LUNARCRUSH_API_KEY). عمل مستقبلي؛ هذا الحكم يقارن الأموال الذكية بمزاج السوق "
            "العام بدلاً منها.") in render_text(v, "ar")


def test_not_authorized_note_has_code():
    v = _v2(social=_social(status="not_authorized", http_status=402))
    assert "key rejected or plan lacks social data (HTTP 402)" in render_text(v, "en")
    assert "(HTTP 402)" in render_text(v, "ar")


def test_price_lines():
    v = _v2(price=PriceContext(4e-06, -5.2, "24h", "nansen_token_info", "Falling"))
    en = render_text(v, "en")
    assert "Price: $0.000004 (-5.2% over 24h, source Nansen token_info)" in en
    assert "price falling while smart money buys" in en
    ar = render_text(v, "ar")
    assert "السعر: $0.000004 (-5.2% خلال 24 ساعة، المصدر Nansen token_info)" in ar
    assert "24h" not in ar
    v2 = _v2(price=PriceContext(4e-06, None, "24h", None, None))
    assert "Price: $0.000004 (24h change unavailable)" in render_text(v2, "en")
    assert "Price: unavailable" in render_text(_v2(price=None), "en")
    assert "السعر: غير متاح" in render_text(_v2(price=None), "ar")


def test_json_sprint2_fields():
    v = _v2(fng=85, social=_social(25),
            price=PriceContext(4e-06, -5.2, "24h", "lunarcrush", "Falling"))
    data = json.loads(render_json(v))
    assert data["crowd_source"] == "token_social"
    assert data["social"]["status"] == "ok" and data["social"]["sentiment"] == 25
    assert data["social"]["scope"] == "token-specific social (LunarCrush)"
    assert data["market_mood"]["value"] == 85
    assert data["market_mood"]["scope"] == \
        "market-wide (whole crypto market, BTC-centric), not token-specific"
    assert data["price"] == {"price_usd": 4e-06, "change_pct": -5.2, "window": "24h",
                             "source": "lunarcrush", "direction": "Falling",
                             "market_cap_usd": None, "liquidity_usd": None, "holders": None}
    assert data["headline"]["en"] == "Smart money is buying while this token's social crowd is bearish"
    assert "crowd" not in data and "price_usd" in data["token"]


def test_json_price_null_and_social_not_configured():
    data = json.loads(render_json(_v2(social=_social(status="not_configured"))))
    assert data["price"] is None and data["social"]["status"] == "not_configured"
    assert data["social"]["sentiment"] is None


def test_crowded_trade_market_variant_text():
    v = decide(TOK, "1d", build_sm_signal(SmFlow(1.2e6, 1.5e6, 3e5, 12, {}), None, None),
               signal_from_value(90))
    en, ar = render_text(v, "en"), render_text(v, "ar")
    assert ("Note: the whole crypto market is in Extreme Greed (market-wide) - "
            "trades may be crowded.") in en
    assert "سوق الكريبتو بأكمله في حالة طمع شديد" in ar
    assert "extreme optimism about this token" not in en


def test_arabic_short_names_depend_on_crowd_source():
    assert kind_text("CONTRARIAN_BULLISH", "ar", "market_mood")[0] == "صعود عكس مزاج السوق"
    assert kind_text("WARNING_BEARISH", "ar", "market_mood")[0] == "تحذير: بيع وسط طمع السوق"
    assert kind_text("CONTRARIAN_BULLISH", "ar", "token_social")[0] == "صعود عكس الجمهور"
    assert kind_text("WARNING_BEARISH", "ar", "token_social")[0] == "تحذير (هبوطي)"
    for source in ("market_mood",):
        for kind in ("CONTRARIAN_BULLISH", "WARNING_BEARISH", "CONFIRMED_BULLISH",
                     "CONFIRMED_BEARISH", "NEUTRAL"):
            assert "الجمهور" not in kind_text(kind, "ar", source)[0]
    out = render_text(_v2(fng=20), "ar")
    assert "[صعود عكس مزاج السوق]" in out


# ======================= Sprint 3: REST lines ===========================================
def test_rest_flow_lines_both_languages():
    sm = build_sm_signal(SmFlow(-1524.38, None, None, 12, {}, 6842.44), BuySellSide(2694, 6),
                         BuySellSide(145673, 6), top_pnl=SmFlow(-6.6e6, None, None, 78, {}, 1.5e6))
    price = PriceContext(4.38e-06, -0.1, "prev_close", "nansen_ohlcv", "Flat", 1.838e9, 1.717e7,
                         409302)
    v = decide(TOK, "1d", sm, signal_from_value(70), None, price)
    en, ar = render_text(v, "en"), render_text(v, "ar")
    assert "  - Net flow: -$1.5k (12 wallets, avg flow (Nansen) $6.8k)" in en
    assert "per wallet" not in en and "estimated gross" not in en
    assert "  - Top PnL traders net flow (context, not scored): -$6.6M (78 wallets)" in en
    assert ("Price: $0.00000438 (-0.1% vs the previous daily close (UTC), source Nansen OHLCV)"
            in en)
    assert "Market context: market cap $1.8B, liquidity $17.2M, holders 409,302" in en
    assert "متوسط التدفق (Nansen) $6.8k" in ar and "12 محفظة" in ar
    assert "إجمالي تقديري" not in ar and "مقارنة بإغلاق اليوم السابق (UTC)" in ar
    assert "أعلى المتداولين ربحاً" in ar and "عدد الحاملين 409,302" in ar
    assert "in n/a" not in en


def test_empty_flow_and_zero_volume_rendering():
    sm = build_sm_signal(SmFlow(0.0, None, None, 0, {}, None), BuySellSide(0, 0), BuySellSide(0, 0))
    v = decide(TOK, "1d", sm, signal_from_value(70))
    en, ar = render_text(v, "en"), render_text(v, "ar")
    assert "  - Net flow: no smart-money flow in this period" in en
    assert "  - Smart buyers vs sellers: $0 bought / $0 sold (score n/a)" in en
    assert "$0.00" not in en
    assert "لا يوجد تدفق للأموال الذكية في هذه الفترة" in ar
    assert v.kind == "INSUFFICIENT_DATA"


def test_wbs_truncated_note():
    sm = build_sm_signal(SmFlow(1e5, None, None, 5, {}), BuySellSide(8e5, 400), BuySellSide(2e5, 400),
                         wbs_truncated=True)
    v = decide(TOK, "1d", sm, signal_from_value(70))
    assert "cut at the top 400 wallets per side" in render_text(v, "en")
    assert "أعلى 400 محفظة" in render_text(v, "ar")


def test_net_only_flow_line():
    sm = build_sm_signal(SmFlow(2e5, None, None, 5, {}, None), None, None)
    v = decide(TOK, "1d", sm, signal_from_value(70))
    assert "  - Net flow: +$200.0k (5 wallets)" in render_text(v, "en")
