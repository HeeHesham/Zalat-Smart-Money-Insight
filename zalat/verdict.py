"""The verdict engine (pure functions, no I/O).

Smart-money score ``s`` in [-1, 1] combines two parts:

* ``flow_score`` from the Smart Money row of ``token_recent_flows_summary``.
  When inflow and outflow are both known it is ``net / (inflow + outflow)``:
  "what share of the smart-money volume was net buying", on the same linear
  [-1, 1] scale as the buy/sell part. Otherwise only the net figure is known
  and we squash it with ``tanh(net / flow_scale)`` so that ~$100k of net
  flow counts as a solid move.
* ``bs_score = (buy - sell) / (buy + sell)`` from smart-labelled wallets in
  ``token_who_bought_sold`` (BUY and SELL calls).

``s`` is their weighted average (flow 0.6, buy/sell 0.4), re-normalised when
only one part is available. The crowd score is ``c = (F&G - 50) / 50``.

The contrast matrix then turns (smart-money label, crowd bucket) into one of
the verdict kinds. The two *disagreement* cells are the headline:
smart money buying into fear, and smart money selling into greed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from zalat.fng import CrowdSignal, crowd_bucket  # noqa: F401 (re-exported)
from zalat.nansen_mcp import TokenRef
from zalat.parsing import BuySellSide, SmFlow

# Weights of the two smart-money parts.
W_FLOW = 0.6
W_BS = 0.4
# |s| thresholds.
SM_LABEL_THRESHOLD = 0.2   # >= +0.2 accumulating, <= -0.2 distributing
SM_STRONG = 0.6            # |s| >= 0.6 strong, >= 0.2 moderate, else weak
CONF_WEAK_SIGNAL = 0.4     # |s| below this downgrades confidence
CROWD_DISAGREE_MIN = 0.1   # |c| must exceed this for a disagreement flag
MIN_WALLETS = 3            # fewer smart wallets than this downgrades confidence
DEFAULT_FLOW_SCALE = 1e5   # USD, used when gross in/out flow is unknown

KINDS = (
    "CONTRARIAN_BULLISH",
    "WARNING_BEARISH",
    "CONFIRMED_BULLISH",
    "CONFIRMED_BEARISH",
    "NEUTRAL",
    "INSUFFICIENT_DATA",
    "SM_ONLY",
)
#: The two headline "smart money vs crowd" cells of the matrix.
DISAGREEMENT_KINDS = ("CONTRARIAN_BULLISH", "WARNING_BEARISH")
FEAR_SIDE = {"Fear", "Extreme Fear"}
GREED_SIDE = {"Greed", "Extreme Greed"}
_LEVELS = ["Low", "Medium", "High"]


@dataclass
class SmartMoneySignal:
    """Everything we know about smart money for this token and period."""

    flow: SmFlow | None
    buy: BuySellSide | None
    sell: BuySellSide | None
    flow_score: float | None
    bs_score: float | None
    score: float | None
    label: str                      # Accumulating | Distributing | Neutral | Unavailable
    strength: str | None            # strong | moderate | weak | None
    wallets: int | None
    unavailable_reasons: list[tuple[str, dict]] = field(default_factory=list)


@dataclass
class Verdict:
    """Final result; rendered as text (EN/AR) or JSON."""

    token: TokenRef
    period: str
    sm: SmartMoneySignal
    crowd: CrowdSignal
    kind: str
    divergence: float | None
    disagreement: bool
    confidence: str
    reasons: list[tuple[str, dict]]
    notes: list[tuple[str, dict]] = field(default_factory=list)
    generated_at: str = ""


def sm_label(score: float | None) -> str:
    """Label a smart-money score."""
    if score is None:
        return "Unavailable"
    if score >= SM_LABEL_THRESHOLD:
        return "Accumulating"
    if score <= -SM_LABEL_THRESHOLD:
        return "Distributing"
    return "Neutral"


def sm_strength(score: float | None) -> str | None:
    """Describe how strong a smart-money score is."""
    if score is None:
        return None
    a = abs(score)
    if a >= SM_STRONG:
        return "strong"
    if a >= SM_LABEL_THRESHOLD:
        return "moderate"
    return "weak"


def build_sm_signal(
    flow: SmFlow | None,
    buy: BuySellSide | None,
    sell: BuySellSide | None,
    flow_scale: float = DEFAULT_FLOW_SCALE,
) -> SmartMoneySignal:
    """Combine the flow and buy/sell parts into one smart-money signal."""
    reasons: list[tuple[str, dict]] = []

    flow_score = None
    if flow is not None and flow.net_usd is not None:
        if flow.inflow_usd is not None and flow.outflow_usd is not None:
            gross = max(abs(flow.inflow_usd) + abs(flow.outflow_usd), 1.0)
            # Clamp: a reported net can disagree slightly with in/out.
            flow_score = max(-1.0, min(1.0, flow.net_usd / gross))
        else:
            flow_score = math.tanh(flow.net_usd / flow_scale)
    else:
        reasons.append(("flow_unavailable", {}))

    bs_score = None
    if buy is not None and sell is not None and buy.volume_usd is not None \
            and sell.volume_usd is not None:
        total = buy.volume_usd + sell.volume_usd
        if total > 0:
            bs_score = (buy.volume_usd - sell.volume_usd) / total
        else:
            reasons.append(("no_sm_trades", {}))
    else:
        reasons.append(("bs_unavailable", {}))

    parts = [(W_FLOW, flow_score), (W_BS, bs_score)]
    avail = [(w, v) for w, v in parts if v is not None]
    score = sum(w * v for w, v in avail) / sum(w for w, _ in avail) if avail else None

    # Wallet count: the flows summary's own count if it has one. Otherwise use
    # the larger of the buyer/seller lists: the same wallet can appear on both
    # sides, so adding them would double-count. This is a lower bound.
    wallets = None
    if flow is not None and flow.wallets is not None:
        wallets = flow.wallets
    elif buy is not None and sell is not None:
        wallets = max(buy.wallets, sell.wallets)

    return SmartMoneySignal(flow, buy, sell, flow_score, bs_score, score,
                            sm_label(score), sm_strength(score), wallets, reasons)


def _classify(sm: SmartMoneySignal, crowd: CrowdSignal) -> str:
    """The contrast matrix."""
    if sm.label == "Unavailable":
        return "INSUFFICIENT_DATA"
    if not crowd.available:
        return "SM_ONLY"
    if sm.label == "Neutral" or crowd.label == "Neutral":
        return "NEUTRAL"
    if sm.label == "Accumulating":
        return "CONTRARIAN_BULLISH" if crowd.label in FEAR_SIDE else "CONFIRMED_BULLISH"
    # Distributing
    return "WARNING_BEARISH" if crowd.label in GREED_SIDE else "CONFIRMED_BEARISH"


def _confidence(sm: SmartMoneySignal, crowd: CrowdSignal) -> tuple[str, list[tuple[str, dict]]]:
    """Confidence level plus the reasons it was lowered."""
    reasons: list[tuple[str, dict]] = list(sm.unavailable_reasons)
    if not crowd.available:
        reasons.append(("crowd_unavailable", {}))
    if sm.score is None or not crowd.available:
        return "Low", reasons

    parts = sum(x is not None for x in (sm.flow_score, sm.bs_score))
    level = 2 if parts == 2 else 1  # High with both parts, Medium with one
    if parts == 1:
        reasons.append(("one_sm_part", {}))
    if abs(sm.score) < CONF_WEAK_SIGNAL:
        level -= 1
        reasons.append(("weak_signal", {"s": sm.score}))
    if sm.flow_score is not None and sm.bs_score is not None \
            and sm.flow_score * sm.bs_score < 0:
        level -= 1
        reasons.append(("parts_disagree", {}))
    if sm.wallets is not None and sm.wallets < MIN_WALLETS:
        level -= 1
        reasons.append(("low_wallets", {"n": sm.wallets}))
    if crowd.value is not None and 45 <= crowd.value <= 55:
        level -= 1
        reasons.append(("crowd_neutral", {}))
    return _LEVELS[max(0, level)], reasons


def decide(token: TokenRef, period: str, sm: SmartMoneySignal, crowd: CrowdSignal) -> Verdict:
    """Produce the final :class:`Verdict`."""
    kind = _classify(sm, crowd)

    divergence = None
    disagreement = False
    if sm.score is not None and crowd.available and crowd.score is not None:
        # Positive divergence = smart money leans against the crowd.
        divergence = sm.score * (-crowd.score)
        disagreement = (
            abs(sm.score) >= SM_LABEL_THRESHOLD
            and abs(crowd.score) > CROWD_DISAGREE_MIN
            and sm.score * crowd.score < 0
        )

    confidence, reasons = _confidence(sm, crowd)

    notes: list[tuple[str, dict]] = []
    if kind == "CONFIRMED_BULLISH" and crowd.label == "Extreme Greed":
        notes.append(("crowded_trade", {}))
    if kind == "CONFIRMED_BEARISH":
        notes.append(("capitulation", {}))
    if kind == "NEUTRAL" and sm.score is not None:
        if sm.score > 0:
            notes.append(("lean_positive", {}))
        elif sm.score < 0:
            notes.append(("lean_negative", {}))
    if kind == "SM_ONLY":
        notes.append(("sm_only", {}))

    return Verdict(
        token=token, period=period, sm=sm, crowd=crowd, kind=kind,
        divergence=divergence, disagreement=disagreement,
        confidence=confidence, reasons=reasons, notes=notes,
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )
