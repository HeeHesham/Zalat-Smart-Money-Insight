"""Turn a :class:`~zalat.verdict.Verdict` into text (EN / AR / both) or JSON."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Callable, Literal

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


def display_name(tok: TokenRef) -> str:
    """How the token is named everywhere: "ChainLink (LINK)".

    Nansen's name with a trailing " Token" removed (casing kept), then the
    symbol in brackets. No distinct name -> just the symbol; no symbol
    (``--address`` only) -> a shortened address.
    """
    if not tok.symbol:
        return short_address(tok.address)
    name = (tok.name or "").strip()
    if name.lower().endswith(" token"):
        name = name[: -len(" token")].strip()
    if name and name != tok.symbol:
        return f"{name} ({tok.symbol})"
    return tok.symbol


#: Kept for backwards compatibility: the old name of :func:`display_name`.
token_label = display_name


def _signed_usd(x: float) -> str:
    return ("+" if x > 0 else "") + fmt_usd(x)


def _wallets_paren(f, lang: Lang) -> str:
    return t("wallets_paren", lang, wallets=fmt_wallets(f.wallets, lang)) if f.wallets else ""


def _crowd_name(v: Verdict, lang: Lang) -> str:
    key = "crowd_name_social" if v.crowd_source == "token_social" else "crowd_name_market"
    return t(key, lang)


def _timestamp(v: Verdict) -> str:
    """"2026-09-27 21:05" (UTC) from the ISO ``generated_at``."""
    return (v.generated_at or "")[:16].replace("T", " ")


# --------------------------------------------------------------------------- #
# Section model. Every line is a function of the language, so the English and
# Arabic outputs have exactly the same sections and lines, in the same order.
# --------------------------------------------------------------------------- #
LineFn = Callable[[Lang], str]
#: Notes that belong to the sentiment section; all other notes go to the verdict.
SENTIMENT_NOTES = ("token_vs_market", "market_unavailable")


@dataclass
class Section:
    """One block of output: an optional header key and its lines."""

    header: str | None          # i18n key of the section header (None = top header block)
    lines: list[LineFn] = field(default_factory=list)


def _k(key: str, **params: object) -> LineFn:
    return lambda lang: t(key, lang, **params)


def price_line(v: Verdict) -> LineFn:
    p = v.price

    def fn(lang: Lang) -> str:
        if p is not None and p.change_pct is not None:
            return t("price_line", lang, price=fmt_price(p.price_usd), change=fmt_pct(p.change_pct),
                     window=t(f"window_{p.window}", lang), source=t(f"source_{p.source}", lang))
        if p is not None and p.price_usd is not None:
            return t("price_line_no_change", lang, price=fmt_price(p.price_usd))
        return t("price_na", lang)
    return fn


def market_ctx_line(v: Verdict) -> LineFn:
    """Market cap / liquidity / holders - only the values Nansen actually returned.

    Zero or missing values are left out rather than printed as "$0" or "n/a"
    (e.g. native SOL reports no liquidity and no holder count).
    """
    p = v.price

    def fn(lang: Lang) -> str:
        parts: list[str] = []
        if p is not None:
            if p.market_cap_usd:
                parts.append(t("ctx_mcap", lang, v=fmt_usd(p.market_cap_usd)))
            if p.liquidity_usd:
                parts.append(t("ctx_liq", lang, v=fmt_usd(p.liquidity_usd)))
            if p.holders:
                parts.append(t("ctx_holders", lang, v=f"{int(p.holders):,}"))
        if not parts:
            return t("market_ctx_na", lang)
        return t("market_ctx_line", lang, parts=t("list_sep", lang).join(parts))
    return fn


def market_line(v: Verdict) -> LineFn:
    """The ONLY place the Fear & Greed value is printed; always says market-wide."""
    m = v.market_mood
    secondary = v.social is not None and v.social.available

    def fn(lang: Lang) -> str:
        if not m.available:
            text = t("market_na", lang)
        else:
            text = t("market_line", lang, token=display_name(v.token), label=label(m.label, lang),
                     value=m.value)
        return f"{t('secondary_market', lang)} {text}" if secondary else text
    return fn


def social_line(v: Verdict) -> LineFn:
    social = v.social

    def fn(lang: Lang) -> str:
        if social is not None and social.available:
            galaxy = f"{social.galaxy_score:.0f}" if social.galaxy_score is not None else "n/a"
            return t("social_line", lang, symbol=social.symbol or display_name(v.token),
                     label=label(social.label, lang), sentiment=f"{social.sentiment:.0f}",
                     galaxy=galaxy)
        # Not available: the status note (e.g. "not configured - future work").
        for key, params in v.notes:
            if key.startswith("social_status_"):
                return t(key, lang, **params)
        return t("social_status_not_configured", lang, fallback=v.crowd_source == "market_mood")
    return fn


def _flow_line(v: Verdict) -> LineFn:
    f = v.sm.flow

    def fn(lang: Lang) -> str:
        if f is not None and f.is_empty:
            return t("flow_empty", lang)
        if f is None or f.net_usd is None:
            return t("flow_na", lang)
        net = _signed_usd(f.net_usd)
        if f.inflow_usd is not None or f.outflow_usd is not None:
            wallets = (t("wallets_part", lang, wallets=fmt_wallets(f.wallets, lang))
                       if f.wallets is not None else "")
            return t("flow_line", lang, net=net, inflow=fmt_usd(f.inflow_usd),
                     outflow=fmt_usd(f.outflow_usd), wallets=wallets)
        if f.avg_usd is not None:
            return t("flow_line_avg", lang, net=net, wallets=fmt_wallets(f.wallets or 0, lang),
                     avg=fmt_usd(f.avg_usd))
        return t("flow_line_net", lang, net=net, wallets=_wallets_paren(f, lang))
    return fn


def build_sections(v: Verdict) -> list[Section]:
    """The four output blocks: header, 1 on-chain smart money, 2 sentiment, 3 verdict."""
    sm = v.sm
    name = display_name(v.token)

    # --- header: what token, when, and plain token facts -------------------
    header = Section(None, [
        _k("title", name=name),
        _k("meta_line", chain=v.token.chain or "?", period=v.period, ts=_timestamp(v)),
        _k("address", address=v.token.address),
        price_line(v),
        market_ctx_line(v),
    ])

    # --- 1: on-chain smart money (Nansen only) ------------------------------
    s1 = Section("sec_onchain")
    if sm.label == "Unavailable":
        s1.lines.append(_k("sm_unavailable"))
    else:
        s1.lines.append(lambda lang: t(
            "sm_line", lang, label=label(sm.label, lang),
            strength=f" ({label(sm.strength, lang)})" if sm.strength else "",
            score=fmt_score(sm.score)))
    s1.lines.append(_flow_line(v))
    if sm.buy is not None and sm.sell is not None:
        s1.lines.append(_k("bs_line", buy=fmt_usd(sm.buy.volume_usd),
                           sell=fmt_usd(sm.sell.volume_usd), score=fmt_score(sm.bs_score)))
    else:
        s1.lines.append(_k("bs_na"))
    tp = sm.top_pnl
    if tp is not None and tp.net_usd is not None:
        s1.lines.append(lambda lang: t("top_pnl_line", lang, net=_signed_usd(tp.net_usd),
                                       wallets=_wallets_paren(tp, lang)))
    if sm.flow_basis:
        s1.lines.append(_k(f"basis_{sm.flow_basis}"))
    if sm.wbs_truncated:
        s1.lines.append(_k("wbs_truncated"))

    # --- 2: market sentiment (no on-chain data) -----------------------------
    s2 = Section("sec_sentiment", [market_line(v), social_line(v)])
    s2.lines += [_k(key, **params) for key, params in v.notes if key in SENTIMENT_NOTES]

    # --- 3: final verdict ---------------------------------------------------
    s3 = Section("sec_verdict")
    if v.kind in DISAGREEMENT_KINDS:
        s3.lines.append(lambda lang: t("banner", lang, crowd_name=_crowd_name(v, lang).upper()))
    s3.lines += [
        lambda lang: t("verdict", lang, headline=kind_text(v.kind, lang, v.crowd_source)[1],
                       kind=kind_text(v.kind, lang, v.crowd_source)[0]),
        lambda lang: kind_text(v.kind, lang, v.crowd_source)[2],
        lambda lang: (t("disagree_yes", lang, crowd_name=_crowd_name(v, lang)) if v.disagreement
                      else t("disagree_no", lang)),
    ]
    if v.divergence is not None:
        s3.lines.append(lambda lang: t("divergence", lang, d=fmt_score(v.divergence),
                                       crowd_name=_crowd_name(v, lang)))
    s3.lines.append(lambda lang: t("confidence", lang, level=label(v.confidence, lang)))
    if v.reasons:
        s3.lines.append(_k("why"))
        s3.lines += [(lambda key, params: (lambda lang: f"  - {t(key, lang, **params)}"))(k, p)
                     for k, p in v.reasons]
    other = [(k, p) for k, p in v.notes
             if k not in SENTIMENT_NOTES and not k.startswith("social_status_")]
    s3.lines += [_k(k, **p) for k, p in other]
    s3.lines += [lambda lang: "", lambda lang: DISCLAIMER[lang]]
    return [header, s1, s2, s3]


def _localise(text: str, lang: Lang) -> str:
    # Number formatters are language-neutral; only "n/a" needs translating.
    return text.replace("n/a", t("na", lang)) if lang == "ar" else text


def section_texts(v: Verdict, lang: Lang) -> list[tuple[str | None, list[str]]]:
    """``[(header text or None, [line, ...]), ...]`` for one language."""
    out = []
    for sec in build_sections(v):
        head = t(sec.header, lang) if sec.header else None
        out.append((head, [_localise(fn(lang), lang) for fn in sec.lines]))
    return out


def _block(v: Verdict, lang: Lang) -> str:
    """Render the verdict in one language (header + 3 titled sections)."""
    parts = []
    for head, lines in section_texts(v, lang):
        block = ([f"━━ {head} ━━"] if head else []) + lines
        parts.append("\n".join(block))
    return "\n\n".join(parts)


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
    data["display_name"] = display_name(v.token)
    data["sections"] = {lang: [{"title": head, "lines": lines}
                               for head, lines in section_texts(v, lang)]
                        for lang in ("en", "ar")}
    data["disclaimer"] = {"en": DISCLAIMER["en"], "ar": DISCLAIMER["ar"]}
    data["version"] = __version__
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)
