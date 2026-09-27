"""Verdict engine: scoring, contrast matrix, boundaries, confidence, divergence."""

import math

import pytest

from zalat.fng import CrowdSignal, signal_from_value
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


def sm(score, flow_score="same", bs_score="same", wallets=20):
    """A SmartMoneySignal with a given score (both parts equal by default)."""
    fs = score if flow_score == "same" else flow_score
    bs = score if bs_score == "same" else bs_score
    return SmartMoneySignal(None, None, None, fs, bs, score, sm_label(score), sm_strength(score),
                            wallets, [])


# ---- scoring -------------------------------------------------------------------
def test_build_sm_signal_both_parts():
    s = build_sm_signal(SmFlow(1.2e6, 1.5e6, 3e5, 12), BuySellSide(8e5, 3), BuySellSide(2e5, 2))
    assert s.flow_score == pytest.approx(math.tanh(1.2e6 / 1.8e6))
    assert s.bs_score == pytest.approx(0.6)
    assert s.score == pytest.approx(0.6 * math.tanh(1.2e6 / 1.8e6) + 0.4 * 0.6)
    assert s.label == "Accumulating" and s.wallets == 12 and s.unavailable_reasons == []


def test_build_sm_signal_renormalises_single_part():
    only_bs = build_sm_signal(None, BuySellSide(1e5, 2), BuySellSide(3e5, 2))
    assert only_bs.score == pytest.approx(-0.5) and only_bs.flow_score is None
    assert ("flow_unavailable", {}) in only_bs.unavailable_reasons
    assert only_bs.wallets == 4
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
def test_confidence_high():
    v = decide(TOK, "1d", sm(0.7), signal_from_value(20))
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
    v = decide(TOK, "1d", sm(0.3), signal_from_value(20))
    assert v.confidence == "Medium" and [k for k, _ in v.reasons] == ["weak_signal"]


def test_notes():
    assert ("crowded_trade", {}) in decide(TOK, "1d", sm(0.7), signal_from_value(90)).notes
    assert ("capitulation", {}) in decide(TOK, "1d", sm(-0.7), signal_from_value(10)).notes
    assert ("lean_positive", {}) in decide(TOK, "1d", sm(0.1), signal_from_value(20)).notes
    assert ("lean_negative", {}) in decide(TOK, "1d", sm(-0.1), signal_from_value(20)).notes
