"""Verdict engine: scoring, contrast matrix, boundaries, confidence, divergence."""

import math

import pytest

from zalat.fng import CrowdSignal, signal_from_value
from zalat.lunarcrush import SocialSignal, social_bucket
from zalat.nansen_mcp import TokenRef
from zalat.parsing import BuySellSide, SmFlow
from zalat.verdict import (
    SmartMoneySignal,
    build_sm_signal,
    decide,
    sm_label,
    sm_strength,
)

TOK = TokenRef("PEPE", "Pepe", "0xabc", "ethereum")
NO_CROWD = CrowdSignal(False, error="offline")


def social_sig(sentiment, status="ok", **kw):
    """A LunarCrush SocialSignal with the given 0-100 sentiment."""
    if status != "ok":
        return SocialSignal(status, "PEPE", **kw)
    return SocialSignal("ok", "PEPE", sentiment, social_bucket(sentiment),
                        (sentiment - 50) / 50, **kw)


def sm(score, flow_score="same", bs_score="same", wallets=20):
    """A SmartMoneySignal with a given score (both parts equal by default)."""
    fs = score if flow_score == "same" else flow_score
    bs = score if bs_score == "same" else bs_score
    return SmartMoneySignal(None, None, None, fs, bs, score, sm_label(score), sm_strength(score),
                            wallets, [])


# ---- scoring -------------------------------------------------------------------
def test_build_sm_signal_both_parts():
    s = build_sm_signal(SmFlow(1.2e6, 1.5e6, 3e5, 12), BuySellSide(8e5, 3), BuySellSide(2e5, 2))
    # gross known -> linear ratio net / (in + out), same scale as bs_score
    assert s.flow_score == pytest.approx(1.2e6 / 1.8e6)
    assert s.bs_score == pytest.approx(0.6)
    assert s.score == pytest.approx(0.6 * (1.2e6 / 1.8e6) + 0.4 * 0.6)
    assert s.label == "Accumulating" and s.wallets == 12 and s.unavailable_reasons == []


def test_build_sm_signal_renormalises_single_part():
    only_bs = build_sm_signal(None, BuySellSide(1e5, 2), BuySellSide(3e5, 2))
    assert only_bs.score == pytest.approx(-0.5) and only_bs.flow_score is None
    assert ("flow_unavailable", {}) in only_bs.unavailable_reasons
    assert only_bs.wallets == 2  # max(buyers, sellers): no double counting
    only_flow = build_sm_signal(SmFlow(-1e5, None, None, None), None, None)
    assert only_flow.score == pytest.approx(math.tanh(-1.0))  # fixed 1e5 scale
    assert ("bs_unavailable", {}) in only_flow.unavailable_reasons


def test_build_sm_signal_nothing_available():
    s = build_sm_signal(None, None, None)
    assert s.score is None and s.label == "Unavailable" and s.strength is None


def test_build_sm_signal_zero_trades():
    s = build_sm_signal(None, BuySellSide(0, 0), BuySellSide(0, 0))
    assert s.bs_score is None and ("no_sm_trades", {}) in s.unavailable_reasons


@pytest.mark.parametrize("score, label, strength", [
    (0.2, "Accumulating", "moderate"), (0.1999, "Neutral", "weak"),
    (-0.2, "Distributing", "moderate"), (-0.1999, "Neutral", "weak"),
    (0.6, "Accumulating", "strong"), (0.5999, "Accumulating", "moderate"),
    (-0.6, "Distributing", "strong"), (0.0, "Neutral", "weak"), (None, "Unavailable", None),
])
def test_label_and_strength_boundaries(score, label, strength):
    assert sm_label(score) == label
    assert sm_strength(score) == strength


# ---- contrast matrix -------------------------------------------------------------
@pytest.mark.parametrize("score, fng, kind, disagreement", [
    (0.7, 10, "CONTRARIAN_BULLISH", True),
    (0.7, 30, "CONTRARIAN_BULLISH", True),
    (-0.7, 70, "WARNING_BEARISH", True),
    (-0.7, 90, "WARNING_BEARISH", True),
    (0.7, 70, "CONFIRMED_BULLISH", False),
    (0.7, 90, "CONFIRMED_BULLISH", False),
    (-0.7, 30, "CONFIRMED_BEARISH", False),
    (-0.7, 10, "CONFIRMED_BEARISH", False),
    (0.1, 10, "NEUTRAL", False),      # SM neutral
    (0.7, 50, "NEUTRAL", False),      # crowd neutral
    (-0.7, 45, "NEUTRAL", False),     # crowd neutral edge
    (0.7, 44, "CONTRARIAN_BULLISH", True),   # first Fear value
    (-0.7, 56, "WARNING_BEARISH", True),     # first Greed value
])
def test_matrix(score, fng, kind, disagreement):
    v = decide(TOK, "1d", sm(score), signal_from_value(fng))
    assert v.kind == kind
    assert v.disagreement is disagreement


def test_sm_unavailable_is_insufficient_data_but_keeps_crowd():
    v = decide(TOK, "1d", build_sm_signal(None, None, None), signal_from_value(20))
    assert v.kind == "INSUFFICIENT_DATA"
    assert v.crowd.available and v.crowd.label == "Extreme Fear"
    assert v.confidence == "Low" and v.divergence is None


def test_crowd_unavailable_is_sm_only():
    v = decide(TOK, "1d", sm(0.8), NO_CROWD)
    assert v.kind == "SM_ONLY" and v.confidence == "Low"
    assert ("crowd_unavailable", {}) in v.reasons
    assert v.divergence is None and not v.disagreement


def test_both_unavailable():
    v = decide(TOK, "1d", build_sm_signal(None, None, None), NO_CROWD)
    assert v.kind == "INSUFFICIENT_DATA" and v.confidence == "Low"


# ---- divergence -------------------------------------------------------------------
def test_divergence_sign():
    buy_fear = decide(TOK, "1d", sm(0.5), signal_from_value(20))
    assert buy_fear.divergence == pytest.approx(0.5 * 0.6)  # opposes crowd -> positive
    buy_greed = decide(TOK, "1d", sm(0.5), signal_from_value(80))
    assert buy_greed.divergence < 0


# ---- confidence -------------------------------------------------------------------
def test_confidence_market_mood_only_is_capped_at_medium():
    # Everything strong, but the only crowd signal is market-wide -> Medium.
    v = decide(TOK, "1d", sm(0.7), signal_from_value(20))
    assert v.confidence == "Medium" and v.reasons == [("crowd_market_wide", {})]


def test_confidence_high_with_token_social():
    v = decide(TOK, "1d", sm(0.7), signal_from_value(20), social_sig(20))
    assert v.confidence == "High" and v.reasons == []


def test_confidence_single_part_is_medium():
    v = decide(TOK, "1d", sm(0.7, bs_score=None), signal_from_value(20))
    assert v.confidence == "Medium" and ("one_sm_part", {}) in v.reasons


def test_confidence_downgrades_accumulate_to_low():
    s = sm(0.3, flow_score=0.8, bs_score=-0.45, wallets=2)
    v = decide(TOK, "1d", s, signal_from_value(50))
    keys = [k for k, _ in v.reasons]
    assert {"weak_signal", "parts_disagree", "low_wallets", "crowd_neutral"} <= set(keys)
    assert v.confidence == "Low"
    assert ("low_wallets", {"n": 2}) in v.reasons


def test_confidence_one_downgrade():
    # With token social: High -> Medium for one penalty.
    v = decide(TOK, "1d", sm(0.3), signal_from_value(20), social_sig(20))
    assert v.confidence == "Medium" and [k for k, _ in v.reasons] == ["weak_signal"]
    # Market-only: the Medium ceiling applies first, so one penalty -> Low.
    v2 = decide(TOK, "1d", sm(0.3), signal_from_value(20))
    assert v2.confidence == "Low"
    assert [k for k, _ in v2.reasons] == ["crowd_market_wide", "weak_signal"]


def test_notes():
    market_greed = decide(TOK, "1d", sm(0.7), signal_from_value(90)).notes
    assert ("crowded_trade_market", {}) in market_greed and ("crowded_trade", {}) not in market_greed
    assert ("capitulation", {}) in decide(TOK, "1d", sm(-0.7), signal_from_value(10)).notes
    assert ("lean_positive", {}) in decide(TOK, "1d", sm(0.1), signal_from_value(20)).notes
    assert ("lean_negative", {}) in decide(TOK, "1d", sm(-0.1), signal_from_value(20)).notes


def test_flow_score_linear_when_gross_known_and_clamped():
    assert build_sm_signal(SmFlow(-250_000, 50_000, 300_000, 7), None, None).flow_score \
        == pytest.approx(-250_000 / 350_000)
    # All inflow -> exactly +1 (tanh would cap at 0.76).
    assert build_sm_signal(SmFlow(1e6, 1e6, 0, 5), None, None).flow_score == pytest.approx(1.0)
    # Inconsistent net vs in/out is clamped to [-1, 1].
    assert build_sm_signal(SmFlow(5e6, 1e6, 0, 5), None, None).flow_score == 1.0


def test_flow_score_tanh_fallback_when_gross_unknown():
    s = build_sm_signal(SmFlow(2e5, 1e5, None, None), None, None)
    assert s.flow_score == pytest.approx(math.tanh(2.0))


def test_wallets_not_double_counted():
    s = build_sm_signal(None, BuySellSide(1e5, 5), BuySellSide(1e5, 3))
    assert s.wallets == 5


# ---- minimum-size damping ------------------------------------------------------------
from zalat.verdict import MIN_GROSS_USD  # noqa: E402


def test_dust_flow_is_damped_not_strong():
    s = build_sm_signal(SmFlow(40, 40, 0, None, {}), None, None)
    assert s.flow_score == pytest.approx(40 / MIN_GROSS_USD)
    assert s.label == "Neutral" and s.small_volume
    v = decide(TOK, "1d", s, signal_from_value(15))
    assert v.kind == "NEUTRAL" and not v.disagreement
    assert ("small_volume", {}) in v.reasons


def test_dust_buy_sell_is_damped():
    s = build_sm_signal(None, BuySellSide(10, 1), BuySellSide(0, 0))
    assert s.bs_score == pytest.approx(10 / MIN_GROSS_USD)
    assert s.label == "Neutral" and s.small_volume


def test_damping_is_linear_below_and_off_above_threshold():
    half = build_sm_signal(SmFlow(5_000, 5_000, 0, None), None, None)
    assert half.flow_score == pytest.approx(0.5)
    full = build_sm_signal(SmFlow(10_000, 10_000, 0, None), None, None)
    assert full.flow_score == pytest.approx(1.0) and not full.small_volume
    bs = build_sm_signal(None, BuySellSide(3_000, 2), BuySellSide(1_000, 2))
    assert bs.bs_score == pytest.approx(0.5 * 0.4)  # ratio 0.5 x size 4k/10k


def test_min_gross_override_and_disable():
    s = build_sm_signal(SmFlow(40, 40, 0, None), None, None, min_gross_usd=0)
    assert s.flow_score == pytest.approx(1.0) and not s.small_volume
    s2 = build_sm_signal(SmFlow(500, 500, 0, None), None, None, min_gross_usd=1_000)
    assert s2.flow_score == pytest.approx(0.5)


def test_tanh_fallback_small_net_flags_small_volume():
    s = build_sm_signal(SmFlow(500, None, None, None), None, None)
    assert s.flow_score == pytest.approx(math.tanh(500 / 1e5)) and s.small_volume


def test_small_volume_downgrades_confidence():
    s = build_sm_signal(SmFlow(8_000, 8_000, 0, 20), BuySellSide(8_000, 5), BuySellSide(0, 0))
    assert s.score == pytest.approx(0.8) and s.small_volume
    v = decide(TOK, "1d", s, signal_from_value(15), social_sig(15))
    assert v.kind == "CONTRARIAN_BULLISH"
    assert ("small_volume", {}) in v.reasons and v.confidence == "Medium"
    market_only = decide(TOK, "1d", s, signal_from_value(15))
    assert market_only.confidence == "Low"


# ======================= Sprint 2: merged crowd model ===================================
from zalat.verdict import (  # noqa: E402
    PriceContext,
    build_price_context,
    crowd_side,
    price_direction,
)


def price(change, price_usd=1.0, source="nansen_token_info"):
    return PriceContext(price_usd, change, "24h", source, price_direction(change))


@pytest.mark.parametrize("social, market, source", [
    (social_sig(20), signal_from_value(80), "token_social"),
    (social_sig(20), NO_CROWD, "token_social"),
    (social_sig(None, "not_configured"), signal_from_value(80), "market_mood"),
    (social_sig(None, "not_authorized", http_status=402), NO_CROWD, None),
    (None, signal_from_value(80), "market_mood"),
    (None, NO_CROWD, None),
])
def test_primary_crowd_selection(social, market, source):
    v = decide(TOK, "1d", sm(0.7), market, social)
    assert v.crowd_source == source
    if source is None:
        assert v.kind == "SM_ONLY"


@pytest.mark.parametrize("score, sentiment, kind", [
    (0.7, 10, "CONTRARIAN_BULLISH"), (0.7, 30, "CONTRARIAN_BULLISH"),
    (-0.7, 70, "WARNING_BEARISH"), (-0.7, 90, "WARNING_BEARISH"),
    (0.7, 70, "CONFIRMED_BULLISH"), (0.7, 85, "CONFIRMED_BULLISH"),
    (-0.7, 30, "CONFIRMED_BEARISH"), (-0.7, 10, "CONFIRMED_BEARISH"),
    (0.1, 10, "NEUTRAL"), (0.7, 50, "NEUTRAL"),
    (0.7, 41, "NEUTRAL"), (0.7, 60, "NEUTRAL"),        # Mixed band edges
    (0.7, 40, "CONTRARIAN_BULLISH"), (-0.7, 61, "WARNING_BEARISH"),
])
def test_matrix_with_token_social(score, sentiment, kind):
    # Market mood deliberately points the other way: token social must win.
    market = signal_from_value(90 if sentiment < 50 else 10)
    v = decide(TOK, "1d", sm(score), market, social_sig(sentiment))
    assert v.kind == kind
    assert v.crowd_source == "token_social"
    assert v.disagreement is (kind in ("CONTRARIAN_BULLISH", "WARNING_BEARISH"))


@pytest.mark.parametrize("sentiment, bucket", [
    (0, "Very Bearish"), (20, "Very Bearish"), (21, "Bearish"), (40, "Bearish"),
    (41, "Mixed"), (60, "Mixed"), (61, "Bullish"), (79, "Bullish"),
    (80, "Very Bullish"), (100, "Very Bullish"),
])
def test_social_buckets(sentiment, bucket):
    assert social_bucket(sentiment) == bucket


def test_kinds_identical_to_sprint1_without_social():
    for score, fng, kind in [(0.7, 20, "CONTRARIAN_BULLISH"), (-0.7, 80, "WARNING_BEARISH"),
                             (0.7, 80, "CONFIRMED_BULLISH"), (-0.7, 20, "CONFIRMED_BEARISH"),
                             (0.7, 50, "NEUTRAL")]:
        a = decide(TOK, "1d", sm(score), signal_from_value(fng))
        b = decide(TOK, "1d", sm(score), signal_from_value(fng), social_sig(None, "not_configured"))
        assert a.kind == b.kind == kind


def test_crowd_side():
    assert crowd_side("Extreme Fear") == crowd_side("Very Bearish") == crowd_side("Bearish") == -1
    assert crowd_side("Greed") == crowd_side("Very Bullish") == 1
    assert crowd_side("Neutral") == crowd_side("Mixed") == crowd_side(None) == 0


def test_divergence_uses_primary_crowd():
    v = decide(TOK, "1d", sm(0.5), signal_from_value(90), social_sig(25))
    assert v.divergence == pytest.approx(0.5 * 0.5)  # vs social c=-0.5, not F&G


def test_social_neutral_reason_and_market_neutral_not_used_when_social_primary():
    v = decide(TOK, "1d", sm(0.7), signal_from_value(50), social_sig(55))
    keys = [k for k, _ in v.reasons]
    assert "social_neutral" in keys and "crowd_neutral" not in keys


def test_crowd_market_wide_is_a_ceiling_applied_before_penalties():
    # Always listed when the market mood is the crowd, even if already Medium.
    one_part = decide(TOK, "1d", sm(0.7, bs_score=None), signal_from_value(20))
    assert one_part.confidence == "Medium"
    assert [k for k, _ in one_part.reasons] == ["one_sm_part", "crowd_market_wide"]
    # Market-only + any penalty -> Low (the penalty is not absorbed by the cap).
    for kw in ({"wallets": 2}, {"flow_score": 0.8, "bs_score": -0.1}):
        v = decide(TOK, "1d", sm(0.7, **kw), signal_from_value(20))
        assert v.confidence == "Low" and ("crowd_market_wide", {}) in v.reasons
    # Never listed when token social is the crowd.
    assert ("crowd_market_wide", {}) not in \
        decide(TOK, "1d", sm(0.7), signal_from_value(20), social_sig(20)).reasons


def test_token_vs_market_note():
    v = decide(TOK, "1d", sm(0.7), signal_from_value(85), social_sig(25))
    assert ("token_vs_market", {}) in v.notes
    same = decide(TOK, "1d", sm(0.7), signal_from_value(15), social_sig(25))
    assert ("token_vs_market", {}) not in same.notes


def test_social_status_note_always_present_when_not_ok():
    v = decide(TOK, "1d", sm(0.7), signal_from_value(20), social_sig(None, "not_configured"))
    assert ("social_status_not_configured", {"fallback": True}) in v.notes
    v2 = decide(TOK, "1d", sm(0.7), NO_CROWD, social_sig(None, "not_authorized", http_status=402))
    assert ("social_status_not_authorized", {"fallback": False, "code": 402}) in v2.notes


def test_market_unavailable_note_when_social_primary():
    v = decide(TOK, "1d", sm(0.7), NO_CROWD, social_sig(20))
    assert ("market_unavailable", {}) in v.notes and v.confidence == "High"


def test_crowded_trade_with_very_bullish_social():
    v = decide(TOK, "1d", sm(0.7), signal_from_value(50), social_sig(90))
    assert v.kind == "CONFIRMED_BULLISH" and ("crowded_trade", {}) in v.notes


@pytest.mark.parametrize("change, direction", [
    (3.0, "Rising"), (2.99, "Flat"), (-3.0, "Falling"), (-2.99, "Flat"), (0, "Flat"), (None, None),
])
def test_price_direction_boundaries(change, direction):
    assert price_direction(change) == direction


@pytest.mark.parametrize("score, change, note", [
    (0.7, -5, "accumulation_on_dip"), (0.7, 5, "buying_momentum"),
    (-0.7, 5, "distribution_into_strength"), (-0.7, -5, "exiting_weakness"),
])
def test_price_notes(score, change, note):
    v = decide(TOK, "1d", sm(score), signal_from_value(20), None, price(change))
    assert (note, {}) in v.notes
    base = decide(TOK, "1d", sm(score), signal_from_value(20))
    assert v.kind == base.kind  # price never changes the kind


def test_no_price_note_when_flat_or_neutral_sm():
    v = decide(TOK, "1d", sm(0.7), signal_from_value(20), None, price(1.0))
    assert not any(k in ("accumulation_on_dip", "buying_momentum") for k, _ in v.notes)
    v2 = decide(TOK, "1d", sm(0.1), signal_from_value(20), None, price(-10))
    assert not any(k == "accumulation_on_dip" for k, _ in v2.notes)


def test_price_volatile_downgrade():
    v = decide(TOK, "1d", sm(0.7), signal_from_value(20), social_sig(20), price(-20))
    assert v.confidence == "Medium" and ("price_volatile", {}) in v.reasons
    v2 = decide(TOK, "1d", sm(0.7), signal_from_value(20), social_sig(20), price(-19.9))
    assert v2.confidence == "High"


def test_build_price_context_priorities():
    tok = TokenRef("PEPE", "Pepe", "0x1", "ethereum", price_usd=4e-06)
    lc = SocialSignal("ok", "PEPE", 70, "Bullish", 0.4, price_usd=5e-06, pct_change_24h=-5.0)
    # search price wins; token_info change wins over LunarCrush
    p = build_price_context(tok, (3e-06, 12.0), lc)
    assert (p.price_usd, p.change_pct, p.source, p.direction) == (4e-06, 12.0, "nansen_token_info", "Rising")
    # token_info failed -> LunarCrush change
    p2 = build_price_context(tok, None, lc)
    assert (p2.change_pct, p2.source) == (-5.0, "lunarcrush")
    # untrusted (mismatch) LunarCrush is ignored
    bad = SocialSignal("mismatch", "PEPE", price_usd=1.0, pct_change_24h=50.0)
    p3 = build_price_context(tok, None, bad)
    assert p3.change_pct is None and p3.source is None and p3.price_usd == 4e-06
    # no price anywhere -> None; token_info price used when search had none
    assert build_price_context(TokenRef("X", "", "0x2", "ethereum"), None, None) is None
    p4 = build_price_context(TokenRef("X", "", "0x2", "ethereum"), (7.85, None), None)
    assert p4.price_usd == 7.85 and p4.direction is None


def test_verdict_crowd_alias():
    v = decide(TOK, "1d", sm(0.7), signal_from_value(20))
    assert v.crowd is v.market_mood
