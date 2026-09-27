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
only one part is available. Only smart money sets the direction.

The *primary crowd* it is contrasted with is, in order of preference:

1. token-specific social sentiment (LunarCrush, optional, paid plan):
   ``c = (sentiment - 50) / 50``, buckets Very Bearish .. Very Bullish;
2. the market-wide Fear & Greed Index (whole crypto market, BTC-centric,
   NOT token-specific): ``c = (F&G - 50) / 50``. Verdicts based only on this
   are capped at Medium confidence.

The contrast matrix turns (smart-money label, crowd side) into one of the
verdict kinds. The two *disagreement* cells are the headline: smart money
buying into a bearish/fearful crowd, and selling into a bullish/greedy one.
Price movement is context only (notes and confidence), never the kind.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from zalat.fng import CrowdSignal, crowd_bucket  # noqa: F401 (re-exported)
from zalat.lunarcrush import SocialSignal
from zalat.nansen_mcp import TokenRef
from zalat.parsing import BuySellSide, SmFlow

# Weights of the two smart-money parts.
W_FLOW = 0.6
W_BS = 0.4
# |s| thresholds.
SM_LABEL_THRESHOLD = 0.2   # >= +0.2 accumulating, <= -0.2 distributing
SM_STRONG = 0.6            # |s| >= 0.6 strong, >= 0.2 moderate, else weak
CONF_WEAK_SIGNAL = 0.4     # |s| below this downgrades confidence
MIN_WALLETS = 3            # fewer smart wallets than this downgrades confidence
DEFAULT_FLOW_SCALE = 1e5   # USD, used when gross in/out flow is unknown
#: Below this much gross smart-money volume (USD) a part is scaled down
#: linearly, so $40 of one-sided "dust" can't produce a +1.00 strong signal.
#: Override with ZALAT_MIN_GROSS_USD (0 disables the damping).
MIN_GROSS_USD = 10_000.0

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
#: Crowd labels on the bearish ("fear") and bullish ("greed") side, for both
#: the market-wide F&G buckets and the token social buckets.
FEAR_SIDE = {"Fear", "Extreme Fear", "Bearish", "Very Bearish"}
GREED_SIDE = {"Greed", "Extreme Greed", "Bullish", "Very Bullish"}
_LEVELS = ["Low", "Medium", "High"]
# Price context thresholds (24h change, percent).
PRICE_MOVE_PCT = 3.0        # >= +3% Rising, <= -3% Falling, else Flat
PRICE_VOLATILE_PCT = 20.0   # |change| >= 20% lowers confidence one level


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
    #: True if any available part was damped for having < MIN_GROSS_USD volume.
    small_volume: bool = False
    #: True if flow_score used an ESTIMATED gross (avg flow x wallets, REST).
    gross_estimated: bool = False
    #: Top-PnL traders' flow (REST): secondary context, not part of the score.
    top_pnl: SmFlow | None = None


@dataclass
class PriceContext:
    """Token price and its recent change (context only)."""

    price_usd: float | None
    change_pct: float | None
    window: str = "24h"
    #: Where change_pct came from: "nansen_token_info" | "lunarcrush" | None.
    source: str | None = None
    direction: str | None = None   # Rising | Falling | Flat | None
    # Market context (Nansen token-information), display only.
    market_cap_usd: float | None = None
    liquidity_usd: float | None = None
    holders: float | None = None


@dataclass
class Verdict:
    """Final result; rendered as text (EN/AR) or JSON."""

    token: TokenRef
    period: str
    sm: SmartMoneySignal
    #: Fear & Greed: market-wide mood (whole crypto market), NOT token-specific.
    market_mood: CrowdSignal
    kind: str
    divergence: float | None
    disagreement: bool
    confidence: str
    reasons: list[tuple[str, dict]]
    notes: list[tuple[str, dict]] = field(default_factory=list)
    generated_at: str = ""
    social: SocialSignal | None = None
    price: PriceContext | None = None
    #: Which crowd the verdict contrasts with: "token_social" | "market_mood" | None.
    crowd_source: str | None = None

    @property
    def crowd(self) -> CrowdSignal:
        """Read-only alias of :attr:`market_mood` for older callers."""
        return self.market_mood


def crowd_side(label: str | None) -> int:
    """-1 for a fearful/bearish crowd, +1 for greedy/bullish, 0 otherwise."""
    if label in FEAR_SIDE:
        return -1
    if label in GREED_SIDE:
        return 1
    return 0


def price_direction(change_pct: float | None) -> str | None:
    """Rising / Falling / Flat from a percent change (None if unknown)."""
    if change_pct is None:
        return None
    if change_pct >= PRICE_MOVE_PCT:
        return "Rising"
    if change_pct <= -PRICE_MOVE_PCT:
        return "Falling"
    return "Flat"


def build_price_context(
    token: TokenRef,
    info: tuple[float | None, float | None] | None,
    social: SocialSignal | None,
    ohlcv: tuple[float | None, float | None] | None = None,
    market: dict[str, float] | None = None,
) -> PriceContext | None:
    """Merge price sources.

    Price: Nansen search > Nansen token_info > Nansen OHLCV last close >
    LunarCrush. 24h change: Nansen OHLCV (last close vs previous close) >
    Nansen token_info > LunarCrush (LunarCrush only when its status is "ok").
    ``market`` adds market cap / liquidity / holders for display.
    Returns None when nothing is known.
    """
    info_price, info_change = info if info else (None, None)
    ohlcv_close, ohlcv_change = ohlcv if ohlcv else (None, None)
    lc_ok = social is not None and social.available
    price = next((p for p in (token.price_usd, info_price, ohlcv_close,
                              social.price_usd if lc_ok else None) if p is not None), None)
    change, source = None, None
    if ohlcv_change is not None:
        change, source = ohlcv_change, "nansen_ohlcv"
    elif info_change is not None:
        change, source = info_change, "nansen_token_info"
    elif lc_ok and social.pct_change_24h is not None:
        change, source = social.pct_change_24h, "lunarcrush"
    m = market or {}
    if price is None and change is None and not m:
        return None
    return PriceContext(price, change, "24h", source, price_direction(change),
                        m.get("market_cap_usd"), m.get("liquidity_usd"), m.get("holders"))


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


def _size_factor(gross: float, min_gross: float) -> float:
    """Linear damping for small volume: 1.0 at/above ``min_gross``, less below."""
    if min_gross <= 0:
        return 1.0
    return min(1.0, abs(gross) / min_gross)


def build_sm_signal(
    flow: SmFlow | None,
    buy: BuySellSide | None,
    sell: BuySellSide | None,
    flow_scale: float = DEFAULT_FLOW_SCALE,
    min_gross_usd: float | None = None,
    top_pnl: SmFlow | None = None,
) -> SmartMoneySignal:
    """Combine the flow and buy/sell parts into one smart-money signal.

    Each part is a direction ratio in [-1, 1] multiplied by a size factor
    ``min(1, gross / min_gross_usd)``: a one-sided but tiny flow counts as
    tiny, not as a strong signal.
    """
    min_gross = MIN_GROSS_USD if min_gross_usd is None else min_gross_usd
    reasons: list[tuple[str, dict]] = []
    small = False
    estimated = False

    flow_score = None
    if flow is not None and flow.net_usd is not None:
        if flow.inflow_usd is not None and flow.outflow_usd is not None:
            gross = abs(flow.inflow_usd) + abs(flow.outflow_usd)
            # Clamp: a reported net can disagree slightly with in/out.
            ratio = max(-1.0, min(1.0, flow.net_usd / max(gross, 1.0)))
            flow_score = ratio * _size_factor(gross, min_gross)
        elif flow.estimated_gross_usd is not None:
            # Nansen REST gives net flow, average flow per wallet and the
            # wallet count, but no in/out split: estimate gross = avg x count.
            gross = flow.estimated_gross_usd
            ratio = max(-1.0, min(1.0, flow.net_usd / gross))
            flow_score = ratio * _size_factor(gross, min_gross)
            estimated = True
        else:
            # Only the net is known. tanh(net / flow_scale) already shrinks
            # small nets toward 0; |net| is the best lower bound on gross.
            gross = abs(flow.net_usd)
            flow_score = math.tanh(flow.net_usd / flow_scale)
        small = small or gross < min_gross
    else:
        reasons.append(("flow_unavailable", {}))

    bs_score = None
    if buy is not None and sell is not None and buy.volume_usd is not None \
            and sell.volume_usd is not None:
        total = buy.volume_usd + sell.volume_usd
        if total > 0:
            bs_score = ((buy.volume_usd - sell.volume_usd) / total
                        * _size_factor(total, min_gross))
            small = small or total < min_gross
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
                            sm_label(score), sm_strength(score), wallets, reasons, small,
                            estimated, top_pnl)


def _primary(market: CrowdSignal, social: SocialSignal | None
             ) -> tuple[str | None, str | None, float | None]:
    """(crowd_source, label, score) of the crowd we contrast with."""
    if social is not None and social.available:
        return "token_social", social.label, social.score
    if market.available:
        return "market_mood", market.label, market.score
    return None, None, None


def _classify(sm: SmartMoneySignal, source: str | None, label: str | None) -> str:
    """The contrast matrix (only smart money sets the direction)."""
    if sm.label == "Unavailable":
        return "INSUFFICIENT_DATA"
    if source is None:
        return "SM_ONLY"
    side = crowd_side(label)
    if sm.label == "Neutral" or side == 0:
        return "NEUTRAL"
    if sm.label == "Accumulating":
        return "CONTRARIAN_BULLISH" if side < 0 else "CONFIRMED_BULLISH"
    # Distributing
    return "WARNING_BEARISH" if side > 0 else "CONFIRMED_BEARISH"


def _confidence(sm: SmartMoneySignal, market: CrowdSignal, social: SocialSignal | None,
                source: str | None, price: PriceContext | None
                ) -> tuple[str, list[tuple[str, dict]]]:
    """Confidence level plus the reasons it was lowered."""
    reasons: list[tuple[str, dict]] = list(sm.unavailable_reasons)
    if source is None:
        reasons.append(("crowd_unavailable", {}))
    if sm.score is None or source is None:
        return "Low", reasons

    parts = sum(x is not None for x in (sm.flow_score, sm.bs_score))
    level = 2 if parts == 2 else 1  # High with both parts, Medium with one
    if parts == 1:
        reasons.append(("one_sm_part", {}))
    # The market-wide mood says nothing about THIS token's crowd, so it sets a
    # ceiling of Medium *before* any penalty: market-only + any penalty = Low.
    if source == "market_mood":
        level = min(level, 1)
        reasons.append(("crowd_market_wide", {}))
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
    if sm.small_volume:
        level -= 1
        reasons.append(("small_volume", {}))
    if source == "market_mood" and market.value is not None and 45 <= market.value <= 55:
        level -= 1
        reasons.append(("crowd_neutral", {}))
    if source == "token_social" and social is not None and social.label == "Mixed":
        level -= 1
        reasons.append(("social_neutral", {}))
    if price is not None and price.change_pct is not None \
            and abs(price.change_pct) >= PRICE_VOLATILE_PCT:
        level -= 1
        reasons.append(("price_volatile", {}))
    return _LEVELS[max(0, level)], reasons


_PRICE_NOTES = {
    ("Accumulating", "Falling"): "accumulation_on_dip",
    ("Accumulating", "Rising"): "buying_momentum",
    ("Distributing", "Rising"): "distribution_into_strength",
    ("Distributing", "Falling"): "exiting_weakness",
}


def decide(
    token: TokenRef,
    period: str,
    sm: SmartMoneySignal,
    market: CrowdSignal,
    social: SocialSignal | None = None,
    price: PriceContext | None = None,
) -> Verdict:
    """Produce the final :class:`Verdict`.

    ``market`` is the Fear & Greed signal; ``social`` (optional) the token's
    LunarCrush sentiment; ``price`` (optional) context for notes/confidence.
    """
    source, label, cscore = _primary(market, social)
    kind = _classify(sm, source, label)

    divergence = None
    if sm.score is not None and cscore is not None:
        # Positive divergence = smart money leans against the crowd.
        divergence = sm.score * (-cscore)
    # The matrix already encodes the thresholds: |s| >= 0.2 and a crowd
    # outside its neutral band (F&G 45-55, social 41-60) on the opposite side.
    disagreement = kind in DISAGREEMENT_KINDS

    confidence, reasons = _confidence(sm, market, social, source, price)

    notes: list[tuple[str, dict]] = []
    if kind == "CONFIRMED_BULLISH" and label == "Very Bullish":
        notes.append(("crowded_trade", {}))
    elif kind == "CONFIRMED_BULLISH" and label == "Extreme Greed":
        # Market-wide variant: it is the whole market that is euphoric.
        notes.append(("crowded_trade_market", {}))
    if kind == "CONFIRMED_BEARISH":
        notes.append(("capitulation", {}))
    if kind == "NEUTRAL" and sm.score is not None:
        if sm.score > 0:
            notes.append(("lean_positive", {}))
        elif sm.score < 0:
            notes.append(("lean_negative", {}))
    if kind == "SM_ONLY":
        notes.append(("sm_only", {}))
    if price is not None and (key := _PRICE_NOTES.get((sm.label, price.direction or ""))):
        notes.append((key, {}))
    if social is not None and social.available and market.available \
            and crowd_side(social.label) * crowd_side(market.label) < 0:
        notes.append(("token_vs_market", {}))
    if social is not None and not social.available:
        params: dict = {"fallback": source == "market_mood"}
        if social.http_status is not None and social.status == "not_authorized":
            params["code"] = social.http_status
        notes.append((f"social_status_{social.status}", params))
    if source == "token_social" and not market.available:
        notes.append(("market_unavailable", {}))

    return Verdict(
        token=token, period=period, sm=sm, market_mood=market, kind=kind,
        divergence=divergence, disagreement=disagreement,
        confidence=confidence, reasons=reasons, notes=notes,
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        social=social, price=price, crowd_source=source,
    )
