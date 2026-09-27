"""Turn a :class:`~zalat.verdict.Verdict` into text (EN / AR / both) or JSON."""

from __future__ import annotations

import dataclasses
import json
from typing import Literal

from zalat import __version__
from zalat.i18n import (
    DISCLAIMER,
    Lang,
    fmt_pct,
    fmt_price,
    fmt_score,
    fmt_usd,
    fmt_wallets,
    kind_text,
    label,
    t,
)
from zalat.lunarcrush import SocialSignal
from zalat.nansen_mcp import TokenRef
from zalat.verdict import DISAGREEMENT_KINDS, Verdict

DIVIDER = "=" * 60
MARKET_SCOPE = "market-wide (whole crypto market, BTC-centric), not token-specific"
SOCIAL_SCOPE = "token-specific social (LunarCrush)"


def short_address(addr: str) -> str:
    """``0x6982508145454ce325ddbe47a25d4ec3d2311933`` -> ``0x6982…1933``."""
    return addr if len(addr) <= 12 else f"{addr[:6]}…{addr[-4:]}"


def token_label(tok: TokenRef) -> str:
    """"PEPE (Pepe)"; "PEPE" when there is no distinct name; a shortened
    address when there is no symbol (``--address`` without a symbol)."""
    if not tok.symbol:
        return short_address(tok.address)
    if tok.name and tok.name != tok.symbol:
        return f"{tok.symbol} ({tok.name})"
    return tok.symbol


def _signed_usd(x: float) -> str:
    return ("+" if x > 0 else "") + fmt_usd(x)


def _wallets_paren(f, lang: Lang) -> str:
    return t("wallets_paren", lang, wallets=fmt_wallets(f.wallets, lang)) if f.wallets else ""


def _crowd_name(v: Verdict, lang: Lang) -> str:
    key = "crowd_name_social" if v.crowd_source == "token_social" else "crowd_name_market"
    return t(key, lang)


def _market_line(v: Verdict, lang: Lang) -> str:
    """The ONLY place the Fear & Greed value is printed; always says market-wide."""
    m = v.market_mood
    if not m.available:
        return t("market_na", lang)
    return t("market_line", lang, token=token_label(v.token), label=label(m.label, lang),
             value=m.value)


def _block(v: Verdict, lang: Lang) -> str:
    """Render the verdict in one language."""
    tok, sm = v.token, v.sm
    short, headline, explanation = kind_text(v.kind, lang, v.crowd_source)
    crowd_name = _crowd_name(v, lang)
    lines = [t("title", lang)]
    if v.kind in DISAGREEMENT_KINDS:
        # The headline case: make it impossible to miss.
        lines.append(t("banner", lang, crowd_name=crowd_name.upper()))
    lines += [
        t("token_line", lang, token=token_label(tok), chain=tok.chain, period=v.period),
        t("address", lang, address=tok.address),
        "-" * 60,
        t("verdict", lang, headline=headline, kind=short),
        explanation,
        t("disagree_yes", lang, crowd_name=crowd_name) if v.disagreement else t("disagree_no", lang),
        "",
    ]

    # --- smart money (primary) ---
    if sm.label == "Unavailable":
        lines.append(t("sm_unavailable", lang))
    else:
        strength = f" ({label(sm.strength, lang)})" if sm.strength else ""
        lines.append(t("sm_line", lang, label=label(sm.label, lang), strength=strength,
                       score=fmt_score(sm.score)))
    f = sm.flow
    if f is not None and f.is_empty:
        lines.append(t("flow_empty", lang))
    elif f is not None and f.net_usd is not None:
        net = _signed_usd(f.net_usd)
        if f.inflow_usd is not None or f.outflow_usd is not None:
            wallets = (t("wallets_part", lang, wallets=fmt_wallets(f.wallets, lang))
                       if f.wallets is not None else "")
            lines.append(t("flow_line", lang, net=net, inflow=fmt_usd(f.inflow_usd),
                           outflow=fmt_usd(f.outflow_usd), wallets=wallets))
        elif f.avg_usd is not None:
            lines.append(t("flow_line_avg", lang, net=net,
                           wallets=fmt_wallets(f.wallets or 0, lang), avg=fmt_usd(f.avg_usd)))
        else:
            lines.append(t("flow_line_net", lang, net=net, wallets=_wallets_paren(f, lang)))
    else:
        lines.append(t("flow_na", lang))
    if sm.buy is not None and sm.sell is not None:
        lines.append(t("bs_line", lang, buy=fmt_usd(sm.buy.volume_usd),
                       sell=fmt_usd(sm.sell.volume_usd), score=fmt_score(sm.bs_score)))
    else:
        lines.append(t("bs_na", lang))
    tp = sm.top_pnl
    if tp is not None and tp.net_usd is not None:
        lines.append(t("top_pnl_line", lang, net=_signed_usd(tp.net_usd),
                       wallets=_wallets_paren(tp, lang)))

    # --- price context ---
    p = v.price
    if p is not None:
        if p.change_pct is not None:
            lines.append(t("price_line", lang, price=fmt_price(p.price_usd),
                           change=fmt_pct(p.change_pct), window=t(f"window_{p.window}", lang),
                           source=t(f"source_{p.source}", lang)))
        elif p.price_usd is not None:
            lines.append(t("price_line_no_change", lang, price=fmt_price(p.price_usd)))
        if any(x is not None for x in (p.market_cap_usd, p.liquidity_usd, p.holders)):
            holders = f"{int(p.holders):,}" if p.holders is not None else "n/a"
            lines.append(t("market_ctx_line", lang, mcap=fmt_usd(p.market_cap_usd),
                           liq=fmt_usd(p.liquidity_usd), holders=holders))

    # --- crowd: token social first when it is the primary signal ---
    social = v.social
    if social is not None and social.available:
        galaxy = f"{social.galaxy_score:.0f}" if social.galaxy_score is not None else "n/a"
        lines.append(t("social_line", lang, symbol=social.symbol or token_label(tok),
                       label=label(social.label, lang), sentiment=f"{social.sentiment:.0f}",
                       galaxy=galaxy))
        lines.append(f"{t('secondary_market', lang)} {_market_line(v, lang)}")
    else:
        lines.append(_market_line(v, lang))
    if v.divergence is not None:
        lines.append(t("divergence", lang, d=fmt_score(v.divergence), crowd_name=crowd_name))

    lines.append("")
    lines.append(t("confidence", lang, level=label(v.confidence, lang)))
    if v.reasons:
        lines.append(t("why", lang))
        lines.extend(f"  - {t(key, lang, **params)}" for key, params in v.reasons)
    notes = list(v.notes)
    if sm.wbs_truncated:
        notes.append(("wbs_truncated", {}))
    if notes:
        lines.append("")
        lines.extend(t(key, lang, **params) for key, params in notes)
    lines.append("")
    lines.append(DISCLAIMER[lang])
    return "\n".join(lines)


def render_text(v: Verdict, lang: Literal["en", "ar", "both"] = "both") -> str:
    """Human-readable verdict. ``both`` = English block, divider, Arabic block."""
    if lang == "both":
        return f"{_block(v, 'en')}\n\n{DIVIDER}\n\n{_block(v, 'ar')}\n"
    return _block(v, lang) + "\n"


def render_json(v: Verdict) -> str:
    """Machine-readable verdict (no settings, never the API key)."""
    data = dataclasses.asdict(v)
    # Drop the raw source row (can be large / noisy) but keep its keys for debugging.
    flow = data["sm"].get("flow")
    if flow and "source_row" in flow:
        flow["source_columns"] = list(flow.pop("source_row").keys())
    data["reasons"] = [{"key": k, "params": p} for k, p in v.reasons]
    data["notes"] = [{"key": k, "params": p} for k, p in v.notes]
    data["sm"]["unavailable_reasons"] = [{"key": k, "params": p}
                                         for k, p in v.sm.unavailable_reasons]
    data["headline"] = {"en": kind_text(v.kind, "en", v.crowd_source)[1],
                        "ar": kind_text(v.kind, "ar", v.crowd_source)[1]}
    data["market_mood"]["scope"] = MARKET_SCOPE
    if data["social"] is None:
        # Library callers may omit the social source: report it as not configured.
        data["social"] = {f.name: None for f in dataclasses.fields(SocialSignal)}
        data["social"]["status"] = "not_configured"
    data["social"]["scope"] = SOCIAL_SCOPE
    data["disclaimer"] = {"en": DISCLAIMER["en"], "ar": DISCLAIMER["ar"]}
    data["version"] = __version__
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)
