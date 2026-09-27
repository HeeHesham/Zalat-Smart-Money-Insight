"""The HTML verdict card: "The Face-off" (smart money vs the market mood).

``python -m zalat LINK --period 7d --html`` writes one self-contained HTML file
(inline CSS + SVG + a little JS; no external fonts, scripts or CDNs, so it opens
offline). ``python -m zalat.card --from-json verdict.json`` rebuilds one from
saved ``--json`` output.

Design goals:

* **The verdict in 5 seconds.** A top bar (token identity + price), one bold
  hero sentence with a verdict badge, an AGREE/DISAGREE stamp and confidence
  pips, then the face-off: smart money (Nansen) on one side, the market mood
  (Fear & Greed) on the other, a "VS" node in between. Everything else lives in
  a collapsed ``<details>``. Fits one 1280x720 screen.
* **Charts carry the story, missing data is hidden** (never a fake zero bar).
* **Full English and Arabic.** Both are in the file; a toggle (or ``#ar`` /
  ``#en`` in the URL, or the "L" key) switches the whole card, mirrored for
  right-to-left. Latin runs inside Arabic are wrapped in ``<bdi dir="ltr">``.
* **Dataviz rules:** one axis per chart; buy/sell and inflow/outflow use a
  validated cool/warm diverging pair (dark: #2f96c8/#e45f57, light:
  #1f7fc0/#d4483b, both pass ``validate_palette.js``); the Fear & Greed gauge
  uses its own neutral->amber track; text wears ink colours; every chart has a
  visually hidden data table and hover tooltips; animations respect
  ``prefers-reduced-motion``.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import re
import sys
from html import escape
from pathlib import Path
from typing import Any

from zalat.fng import CrowdSignal
from zalat.i18n import fmt_pct, fmt_price, fmt_usd, fmt_wallets, kind_text, label
from zalat.lunarcrush import SocialSignal
from zalat.nansen_mcp import TokenRef
from zalat.parsing import BuySellSide, SmFlow
from zalat.render import section_texts, short_address
from zalat.verdict import DISAGREEMENT_KINDS, PriceContext, SmartMoneySignal, Verdict, crowd_side

LANGS = ("en", "ar")

# --------------------------------------------------------------------------- #
# Card copy (EN / AR). Terminal strings live in zalat.i18n; these are the
# short, card-only phrasings.
# --------------------------------------------------------------------------- #
CARD_TEXT: dict[str, dict[str, str]] = {
    "en": {
        "price": "Price",
        "win_prev_close": "vs prev. close",
        "win_24h": "24h",
        "sm_title": "Smart money",
        "sm_sub": "on-chain · Nansen",
        "mood_title": "Market mood",
        "mood_sub": "whole market · Fear & Greed",
        "mood_tag": "whole market, not {sym}",
        "social_title": "Token social",
        "social_sub": "LunarCrush · % positive",
        "dir_buy": "Buying",
        "dir_sell": "Selling",
        "dir_flat": "Flat",
        "bought": "Bought",
        "sold": "Sold",
        "split_title": "Smart buyers vs sellers",
        "net_title": "Net flow",
        "sm_sentence": "{wallets} · {period} window",
        "vs": "VS",
        "no_crowd": "no crowd signal",
        "no_sm": "no smart-money signal",
        "stamp_disagree": "Disagree",
        "stamp_agree": "Agree",
        "stamp_neutral": "No clash",
        "confidence": "Confidence",
        "details": "Details",
        "sources": "Sources: Nansen (on-chain smart money), alternative.me Fear & Greed (market mood){lc}.",
        "sources_lc": ", LunarCrush (token social)",
        "footer": "Zalat Smart Money Insight. Data: Nansen, alternative.me. Not financial advice.",
        "table_item": "Item",
        "table_value": "Value",
        "switch": "Language",
        # hero sentences: hero_<crowd source>_<kind>
        "hero_market_mood_CONTRARIAN_BULLISH": "Smart money is buying into market fear.",
        "hero_market_mood_WARNING_BEARISH": "Smart money is selling into market greed.",
        "hero_market_mood_CONFIRMED_BULLISH": "Smart money and the market are both bullish.",
        "hero_market_mood_CONFIRMED_BEARISH": "Smart money and the market are both bearish.",
        "hero_market_mood_NEUTRAL": "No clear clash between smart money and the market.",
        "hero_token_social_CONTRARIAN_BULLISH": "Smart money is buying while this token's crowd is bearish.",
        "hero_token_social_WARNING_BEARISH": "Smart money is selling while this token's crowd is bullish.",
        "hero_token_social_CONFIRMED_BULLISH": "Smart money and this token's crowd are both bullish.",
        "hero_token_social_CONFIRMED_BEARISH": "Smart money and this token's crowd are both bearish.",
        "hero_token_social_NEUTRAL": "No clear clash between smart money and this token's crowd.",
        "hero_INSUFFICIENT_DATA": "Not enough smart-money data for a verdict.",
        "hero_SM_ONLY": "Smart money only: no crowd signal to compare.",
    },
    "ar": {
        "price": "السعر",
        "win_prev_close": "عن الإغلاق السابق",
        "win_24h": "24 ساعة",
        "sm_title": "الأموال الذكية",
        "sm_sub": "على السلسلة · Nansen",
        "mood_title": "مزاج السوق",
        "mood_sub": "السوق كله · الخوف والطمع",
        "mood_tag": "السوق كله، ليس {sym}",
        "social_title": "مشاعر العملة",
        "social_sub": "LunarCrush · % إيجابية",
        "dir_buy": "شراء",
        "dir_sell": "بيع",
        "dir_flat": "مستقر",
        "bought": "شراء",
        "sold": "بيع",
        "split_title": "المشترون مقابل البائعين الأذكياء",
        "net_title": "صافي التدفق",
        "sm_sentence": "{wallets} · فترة {period}",
        "vs": "ضد",
        "no_crowd": "لا توجد إشارة للجمهور",
        "no_sm": "لا توجد إشارة للأموال الذكية",
        "stamp_disagree": "تباين",
        "stamp_agree": "اتفاق",
        "stamp_neutral": "لا صدام",
        "confidence": "الثقة",
        "details": "التفاصيل",
        "sources": "المصادر: Nansen (الأموال الذكية على السلسلة)، مؤشر الخوف والطمع من alternative.me (مزاج السوق){lc}.",
        "sources_lc": "، LunarCrush (مشاعر العملة)",
        "footer": "زلط لرؤى الأموال الذكية. البيانات: Nansen و alternative.me. ليست نصيحة مالية.",
        "table_item": "البند",
        "table_value": "القيمة",
        "switch": "اللغة",
        "hero_market_mood_CONTRARIAN_BULLISH": "الأموال الذكية تشتري وسط خوف السوق.",
        "hero_market_mood_WARNING_BEARISH": "الأموال الذكية تبيع وسط طمع السوق.",
        "hero_market_mood_CONFIRMED_BULLISH": "الأموال الذكية والسوق متفائلان معاً.",
        "hero_market_mood_CONFIRMED_BEARISH": "الأموال الذكية والسوق متشائمان معاً.",
        "hero_market_mood_NEUTRAL": "لا صدام واضح بين الأموال الذكية والسوق.",
        "hero_token_social_CONTRARIAN_BULLISH": "الأموال الذكية تشتري بينما جمهور العملة متشائم.",
        "hero_token_social_WARNING_BEARISH": "الأموال الذكية تبيع بينما جمهور العملة متفائل.",
        "hero_token_social_CONFIRMED_BULLISH": "الأموال الذكية وجمهور العملة متفائلان معاً.",
        "hero_token_social_CONFIRMED_BEARISH": "الأموال الذكية وجمهور العملة متشائمان معاً.",
        "hero_token_social_NEUTRAL": "لا صدام واضح بين الأموال الذكية وجمهور العملة.",
        "hero_INSUFFICIENT_DATA": "لا توجد بيانات كافية عن الأموال الذكية لإصدار حكم.",
        "hero_SM_ONLY": "الأموال الذكية فقط: لا توجد إشارة للجمهور للمقارنة.",
    },
}


def ct(key: str, lang: str, **kw: Any) -> str:
    return CARD_TEXT[lang][key].format(**kw) if kw else CARD_TEXT[lang][key]


# --------------------------------------------------------------------------- #
# Escaping and right-to-left isolation
# --------------------------------------------------------------------------- #
def _e(x: Any) -> str:
    return escape(str(x), quote=True)


#: A run of left-to-right material inside Arabic text (numbers, $ amounts,
#: dates, Latin names), ASCII only so Arabic letters are never swallowed.
# A run never ends in "." / "," / ":" so sentence punctuation stays with the
# Arabic text ("... alternative.me." keeps its final period in the RTL flow).
_LTR_TOKEN = r"[+\-−]?\$?[0-9A-Za-z_](?:[0-9A-Za-z_.,:%/$…\-]*[0-9A-Za-z_%$…])?"
_LTR_PAREN = r"(?:\s*\([0-9A-Za-z_$][0-9A-Za-z_ .,:%/$…\-]*\))?"   # "ChainLink (LINK)"
_LTR_RUN = re.compile(rf"{_LTR_TOKEN}{_LTR_PAREN}(?:\s+{_LTR_TOKEN}{_LTR_PAREN})*")


def _isolate_ltr(text: str) -> str:
    """Escape ``text`` and wrap LTR runs in ``<bdi dir="ltr">`` so numbers,
    signs and names keep their order inside right-to-left Arabic."""
    out, pos = [], 0
    for m in _LTR_RUN.finditer(text):
        out.append(_e(text[pos:m.start()]))
        run = m.group(0)
        # Short runs must not break across a line wrap (that scrambles brackets).
        cls = ' class="nw"' if len(run) <= 32 else ""
        out.append(f'<bdi dir="ltr"{cls}>{_e(run)}</bdi>')
        pos = m.end()
    out.append(_e(text[pos:]))
    return "".join(out)


def _tx(text: str, lang: str) -> str:
    """Escape for the given language (bidi-isolated in Arabic)."""
    return _isolate_ltr(text) if lang == "ar" else _e(text)


def nice_max(x: float) -> float:
    """Round up to 1, 2, 2.5 or 5 x 10^k so scales end on clean numbers."""
    if x <= 0:
        return 1.0
    exp = math.floor(math.log10(x))
    for m in (1, 2, 2.5, 5, 10):
        if m * 10 ** exp >= x:
            return m * 10 ** exp
    return 10 ** (exp + 1)  # pragma: no cover


# --------------------------------------------------------------------------- #
# Small view-model helpers
# --------------------------------------------------------------------------- #
def token_parts(tok: TokenRef) -> tuple[str, str]:
    """(big display name, symbol chip). "ChainLink Token" -> ("ChainLink", "LINK")."""
    if not tok.symbol:
        return short_address(tok.address), ""
    name = (tok.name or "").strip()
    if name.lower().endswith(" token"):
        name = name[:-6].strip()
    return (name or tok.symbol), tok.symbol


def monogram(tok: TokenRef) -> tuple[str, int]:
    """Two letters and a hue seeded from the symbol (stable per token)."""
    base = tok.symbol or tok.address[2:] or "?"
    letters = re.sub(r"[^A-Za-z0-9]", "", base)[:2].upper() or "?"
    hue = int(hashlib.sha1(base.encode()).hexdigest()[:4], 16) % 360
    return letters, hue


def tone(v: Verdict) -> str:
    if v.kind in ("WARNING_BEARISH", "CONFIRMED_BEARISH"):
        return "bear"
    if v.kind in ("CONTRARIAN_BULLISH", "CONFIRMED_BULLISH"):
        return "bull"
    return "neutral"


def stamp_key(v: Verdict) -> str | None:
    if v.kind in DISAGREEMENT_KINDS:
        return "stamp_disagree"
    if v.kind in ("CONFIRMED_BULLISH", "CONFIRMED_BEARISH"):
        return "stamp_agree"
    if v.kind == "NEUTRAL":
        return "stamp_neutral"
    return None


def _arrow(side: int) -> str:
    return "↑" if side > 0 else "↓" if side < 0 else "→"


def _sm_side(sm: SmartMoneySignal) -> int:
    return {"Accumulating": 1, "Distributing": -1}.get(sm.label, 0)


def _num_attrs(text: str) -> str:
    """data-* attributes so JS can count a formatted value up from zero."""
    m = re.fullmatch(r"([^0-9]*?)([0-9][0-9,]*(?:\.[0-9]+)?)(.*)", text)
    if not m:
        return ""
    pre, num, suf = m.groups()
    dec = len(num.split(".")[1]) if "." in num else 0
    # dir="ltr": the JS count-up replaces the text (and any <bdi>), so the
    # element itself must keep "-$117.7k" in order inside Arabic.
    return (f' dir="ltr" data-num="{_e(num.replace(",", ""))}" data-dec="{dec}" data-pre="{_e(pre)}"'
            f' data-suf="{_e(suf)}" data-comma="{1 if "," in num else 0}"')


def _table(caption: str, rows: list[tuple[str, str]], lang: str) -> str:
    body = "".join(f"<tr><td>{_tx(a, lang)}</td><td>{_tx(b, lang)}</td></tr>" for a, b in rows)
    return (f'<div class="sr-only"><table><caption>{_tx(caption, lang)}</caption>'
            f'<tr><th>{_e(ct("table_item", lang))}</th><th>{_e(ct("table_value", lang))}</th></tr>'
            f"{body}</table></div>")


# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #
def split_bar(sm: SmartMoneySignal, lang: str) -> str:
    """100% split bar: share of smart USD volume bought vs sold (hidden if none)."""
    if sm.buy is None or sm.sell is None or sm.buy.volume_usd is None or sm.sell.volume_usd is None:
        return ""
    b, s = sm.buy.volume_usd, sm.sell.volume_usd
    if b + s <= 0:
        return ""
    pb = b / (b + s)
    W, H, gap = 400.0, 12.0, 2.0
    wb = max(0.0, W * pb - gap / 2) if 0 < pb < 1 else W * pb
    ws = max(0.0, W - wb - (gap if 0 < pb < 1 else 0))
    # tiny segments stay visible (>= 3 units) without changing the labels
    if 0 < pb < 1:
        wb, ws = max(wb, 3.0), max(ws, 3.0)
    tip_b = f'{ct("bought", lang)}: {pb:.0%} · {fmt_usd(b)}'
    tip_s = f'{ct("sold", lang)}: {1 - pb:.0%} · {fmt_usd(s)}'
    svg = (f'<svg class="bar split" viewBox="0 0 {W:.0f} {H:.0f}" preserveAspectRatio="none" '
           f'aria-hidden="true">')
    if b > 0:
        svg += (f'<rect class="grow gl mark" data-tip="{_e(tip_b)}" x="0" y="0" width="{wb:.1f}" '
                f'height="{H}" rx="4" fill="var(--buy)"/>')
    if s > 0:
        svg += (f'<rect class="grow gr mark" data-tip="{_e(tip_s)}" x="{W - ws:.1f}" y="0" '
                f'width="{ws:.1f}" height="{H}" rx="4" fill="var(--sell)"/>')
    svg += "</svg>"
    return (
        f'<div class="chart" data-k="split">'
        f'<div class="chart-h"><span class="lbl">{_tx(ct("split_title", lang), lang)}</span></div>'
        f'<div class="ends"><span><i class="sw buy"></i>{_e(ct("bought", lang))} '
        f'<b class="num">{_tx(f"{pb:.0%}", lang)}</b></span><span>{_e(ct("sold", lang))} '
        f'<b class="num">{_tx(f"{1 - pb:.0%}", lang)}</b><i class="sw sell"></i></span></div>'
        f'<div class="mirror">{svg}</div>'
        f'<div class="ends sub"><span>{_tx(fmt_usd(b), lang)}</span><span>{_tx(fmt_usd(s), lang)}</span></div>'
        + _table(ct("split_title", lang), [(ct("bought", lang), fmt_usd(b)),
                                           (ct("sold", lang), fmt_usd(s))], lang)
        + "</div>")


def net_bar(sm: SmartMoneySignal, lang: str) -> str:
    """Diverging bar from a centred zero (hidden when there is no flow)."""
    f = sm.flow
    if f is None or f.net_usd is None or f.is_empty:
        return ""
    net = f.net_usd
    gross = None
    if sm.buy is not None and sm.sell is not None and sm.buy.volume_usd is not None \
            and sm.sell.volume_usd is not None:
        gross = sm.buy.volume_usd + sm.sell.volume_usd
    dom = nice_max(max(abs(net), gross or 0.0))
    W, H = 400.0, 12.0
    half = W / 2
    w = half * abs(net) / dom
    value = ("+" if net > 0 else "") + fmt_usd(net)
    x = half if net > 0 else half - w
    cls = "gl" if net > 0 else "gr"
    color = "var(--buy)" if net > 0 else "var(--sell)"
    svg = (f'<svg class="bar net" viewBox="0 0 {W:.0f} {H + 8:.0f}" preserveAspectRatio="none" '
           f'aria-hidden="true"><rect x="0" y="{H / 2 + 3:.1f}" width="{W:.0f}" height="1" '
           f'fill="var(--grid)"/>')
    if w > 0:
        svg += (f'<rect class="grow {cls} mark" data-tip="{_e(ct("net_title", lang) + ": " + value)}" '
                f'x="{x:.1f}" y="4" width="{w:.1f}" height="{H}" rx="4" fill="{color}"/>')
    svg += f'<rect x="{half - 1:.1f}" y="0" width="2" height="{H + 8:.0f}" fill="var(--axis)"/></svg>'
    ticks = ("-" + fmt_usd(dom), "0", "+" + fmt_usd(dom))
    return (
        f'<div class="chart" data-k="net">'
        f'<div class="chart-h"><span class="lbl">{_tx(ct("net_title", lang), lang)}</span>'
        f'<b class="val num"{_num_attrs(value)}>{_tx(value, lang)}</b></div>'
        # A number line: always left-to-right (negative left, positive right),
        # also in Arabic; only the split bar mirrors.
        f'<div class="axis-ltr" dir="ltr">{svg}'
        f'<div class="ends sub ticks">' + "".join(f"<span>{_e(t_)}</span>" for t_ in ticks)
        + "</div></div>" + _table(ct("net_title", lang), [(ct("net_title", lang), value)], lang) + "</div>")


def gauge(value: float, size: str, kind: str, caption: str, lang: str) -> str:
    """Semicircle gauge 0-100 with a sweeping needle (never mirrored)."""
    angle = 180.0 * max(0.0, min(100.0, value)) / 100.0
    bounds = (25, 45, 56, 76) if kind == "fng" else (20, 40, 60, 80)
    ticks = ""
    for bnd in bounds:
        a = math.radians(180 - 180 * bnd / 100)
        x1, y1 = 100 + 72 * math.cos(a), 100 - 72 * math.sin(a)
        x2, y2 = 100 + 88 * math.cos(a), 100 - 88 * math.sin(a)
        ticks += (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                  f'stroke="var(--card)" stroke-width="2"/>')
    return (
        f'<svg class="gauge {size}" viewBox="0 0 200 112" dir="ltr" role="img" '
        f'aria-label="{_e(caption)}">'
        f'<path d="M20,100 A80,80 0 0 1 180,100" fill="none" stroke="url(#mood-{kind})" '
        f'stroke-width="14" stroke-linecap="round"/>{ticks}'
        f'<g class="needle mark" data-tip="{_e(caption)}" style="--a:{angle:.1f}deg">'
        f'<line x1="100" y1="100" x2="34" y2="100" stroke="var(--ink)" stroke-width="3" '
        f'stroke-linecap="round"/><circle cx="100" cy="100" r="7" fill="var(--ink)" '
        f'stroke="var(--card)" stroke-width="2"/></g></svg>')


# --------------------------------------------------------------------------- #
# Card sections (one full copy per language)
# --------------------------------------------------------------------------- #
def _top(v: Verdict, lang: str) -> str:
    name, sym = token_parts(v.token)
    letters, hue = monogram(v.token)
    chips = (f'<span class="chip">{_e(sym)}</span>' if sym else "") + \
        (f'<span class="chip">{_e(v.token.chain)}</span>' if v.token.chain else "")
    price_html = ""
    p = v.price
    if p is not None and p.price_usd is not None:
        pill = ""
        if p.change_pct is not None:
            arrow = "▲" if p.change_pct > 0 else "▼" if p.change_pct < 0 else "•"
            win = ct("win_prev_close" if p.window == "prev_close" else "win_24h", lang)
            pill = (f'<span class="pill" data-k="change"><span aria-hidden="true">{arrow}</span> '
                    f'{_tx(fmt_pct(p.change_pct), lang)} · {_e(win)}</span>')
        price = fmt_price(p.price_usd)
        price_html = (f'<div class="price" data-k="price"><span class="lbl">{_e(ct("price", lang))}</span>'
                      f'<span class="big num"{_num_attrs(price)}>{_tx(price, lang)}</span>{pill}</div>')
    toggle = ('<div class="toggle" role="group" aria-label="' + _e(ct("switch", lang)) + '">'
              + "".join(f'<button type="button" data-set="{lg}" aria-pressed="{str(lg == lang).lower()}">'
                        f'{"EN" if lg == "en" else "عربي"}</button>' for lg in LANGS) + "</div>")
    return (f'<header class="top"><div class="ident" data-k="ident">'
            f'<div class="mono" style="--h:{hue}" aria-hidden="true">{_e(letters)}</div>'
            f'<div><div class="name" dir="ltr">{_e(name)}</div><div class="chips" dir="ltr">{chips}</div></div>'
            f'</div>{price_html}{toggle}</header>')


def _hero(v: Verdict, lang: str) -> str:
    if v.kind in ("INSUFFICIENT_DATA", "SM_ONLY"):
        hero = ct(f"hero_{v.kind}", lang)
    else:
        hero = ct(f"hero_{v.crowd_source or 'market_mood'}_{v.kind}", lang)
    badge = kind_text(v.kind, lang, v.crowd_source)[0]
    sk = stamp_key(v)
    stamp = ""
    if sk:
        icon = "⇄" if sk == "stamp_disagree" else "✓" if sk == "stamp_agree" else "="
        stamp = (f'<span class="stamp {sk[6:]}" data-k="stamp"><span aria-hidden="true">{icon}</span> '
                 f'{_e(ct(sk, lang))}</span>')
    lvl = {"High": 3, "Medium": 2, "Low": 1}.get(v.confidence, 1)
    pips = "".join(f'<i class="{"on" if i < lvl else ""}"></i>' for i in range(3))
    conf = (f'<span class="conf" data-k="conf"><span class="pips" aria-hidden="true">{pips}</span>'
            f'{_e(ct("confidence", lang))}: <b>{_e(label(v.confidence, lang))}</b></span>')
    return (f'<section class="hero"><h1 class="hero-line" data-k="hero">{_tx(hero, lang)}</h1>'
            f'<div class="hero-meta"><span class="badge" data-k="badge">{_e(badge)}</span>{stamp}{conf}</div>'
            f"</section>")


def _sm_card(v: Verdict, lang: str) -> str:
    sm = v.sm
    if sm.label == "Unavailable":
        return ""
    side = _sm_side(sm)
    word = ct({1: "dir_buy", -1: "dir_sell", 0: "dir_flat"}[side], lang)
    period = v.period
    sentence = ""
    if sm.wallets:
        sentence = (f'<p class="line" data-k="sm-line">'
                    f'{_tx(ct("sm_sentence", lang, wallets=fmt_wallets(sm.wallets, lang), period=period), lang)}</p>')
    charts = split_bar(sm, lang) + net_bar(sm, lang)
    return (f'<article class="side sm" data-k="sm-card"><div class="side-h"><span class="lbl">'
            f'{_e(ct("sm_title", lang))}</span><span class="sub">{_tx(ct("sm_sub", lang), lang)}</span></div>'
            f'<div class="side-body"><div><div class="dir {("up" if side > 0 else "down" if side < 0 else "flat")}" '
            f'data-k="sm-dir"><span class="arrow" aria-hidden="true">{_arrow(side)}</span>{_e(word)}</div>'
            f"{sentence}</div>{charts}</div></article>")


def _mood_card(v: Verdict, lang: str) -> str:
    m, s = v.market_mood, v.social
    parts = []
    sym = v.token.symbol or short_address(v.token.address)
    if m.available and m.value is not None:
        bucket = label(m.label, lang)
        cap = f"{bucket} {m.value}/100"
        parts.append(
            f'<div class="g-wrap" data-k="fng">{gauge(m.value, "lg", "fng", cap, lang)}'
            f'<div class="g-read"><span class="big num" dir="ltr" data-num="{m.value}" data-dec="0" '
            f'data-pre="" data-suf="" data-comma="0">{m.value}</span><span class="bucket">{_e(bucket)}</span></div>'
            f'<span class="tag">{_tx(ct("mood_tag", lang, sym=sym), lang)}</span>'
            + _table(ct("mood_title", lang), [(ct("mood_title", lang), f"{m.value}/100"),
                                              (ct("mood_title", lang), bucket)], lang) + "</div>")
    if s is not None and s.available and s.sentiment is not None:
        bucket = label(s.label, lang)
        cap = f"{bucket} {s.sentiment:.0f}%"
        parts.append(
            f'<div class="g-wrap small" data-k="social"><div class="g-title"><span class="lbl">'
            f'{_e(ct("social_title", lang))}</span><span class="sub">{_tx(ct("social_sub", lang), lang)}</span></div>'
            f'{gauge(s.sentiment, "sm", "soc", cap, lang)}'
            f'<div class="g-read"><span class="mid num">{s.sentiment:.0f}%</span>'
            f'<span class="bucket">{_e(bucket)}</span></div>'
            + _table(ct("social_title", lang), [(ct("social_title", lang), f"{s.sentiment:.0f}%")], lang)
            + "</div>")
    if not parts:
        return ""
    return (f'<article class="side mood" data-k="mood-card"><div class="side-h"><span class="lbl">'
            f'{_e(ct("mood_title", lang))}</span><span class="sub">{_tx(ct("mood_sub", lang), lang)}</span></div>'
            f'<div class="gauges">{"".join(parts)}</div></article>')


def _vs(v: Verdict, lang: str, has_sm: bool, has_mood: bool) -> str:
    if not has_sm:
        return f'<div class="vs solo" data-k="vs"><span class="vs-note">{_e(ct("no_sm", lang))}</span></div>'
    if not has_mood:
        return f'<div class="vs solo" data-k="vs"><span class="vs-note">{_e(ct("no_crowd", lang))}</span></div>'
    if v.crowd_source == "token_social" and v.social is not None:
        crowd = crowd_side(v.social.label)
    else:
        crowd = crowd_side(v.market_mood.label)
    return (f'<div class="vs" data-k="vs"><span class="va" aria-hidden="true">{_arrow(_sm_side(v.sm))}</span>'
            f'<span class="vs-dot">{_e(ct("vs", lang))}</span>'
            f'<span class="va" aria-hidden="true">{_arrow(crowd)}</span></div>')


def _details(v: Verdict, lang: str) -> str:
    blocks = []
    for head, lines in section_texts(v, lang):
        items = "".join(f"<li>{_tx(ln.strip(), lang)}</li>" for ln in lines
                        if ln.strip() and not ln.startswith(">>>"))
        h = f"<h3>{_tx(head, lang)}</h3>" if head else ""
        blocks.append(f'<div class="dblock">{h}<ul>{items}</ul></div>')
    lc = v.social is not None and v.social.available
    src = ct("sources", lang, lc=ct("sources_lc", lang) if lc else "")
    blocks.append(f'<div class="dblock"><ul><li>{_tx(src, lang)}</li></ul></div>')
    return (f'<details class="details" data-k="details"><summary>{_e(ct("details", lang))}</summary>'
            f'<div class="dgrid">{"".join(blocks)}</div></details>')


def _root(v: Verdict, lang: str, active: bool) -> str:
    sm_card, mood_card = _sm_card(v, lang), _mood_card(v, lang)
    has_sm, has_mood = bool(sm_card), bool(mood_card)
    clash = " clash" if v.kind in DISAGREEMENT_KINDS else ""
    solo = "" if (has_sm and has_mood) else " solo"
    face = (f'<section class="faceoff{clash}{solo}" data-k="faceoff">{sm_card}'
            f'{_vs(v, lang, has_sm, has_mood)}{mood_card}</section>')
    attrs = f'lang="{lang}" dir="{"rtl" if lang == "ar" else "ltr"}" data-lang="{lang}"'
    hidden = "" if active else " hidden"
    return (f'<div class="root" {attrs}{hidden}>{_top(v, lang)}{_hero(v, lang)}{face}'
            f'{_details(v, lang)}<footer class="foot" data-k="footer">{_tx(ct("footer", lang), lang)}</footer></div>')


CSS = """
:root{color-scheme:dark;
 --bg:#0b0e13;--card:#121821;--card-2:#161e29;--ink:#f3f5f8;--ink-2:#b7c0cc;--muted:#8792a2;
 --line:rgba(255,255,255,.09);--grid:#263040;--axis:#4b5768;
 --buy:#2f96c8;--sell:#e45f57;--m0:#3b4556;--m1:#f0a93b;
 --t-bear:#e45f57;--t-bull:#2fb8c8;--t-neutral:#7c8aa0;}
@media (prefers-color-scheme: light){:root:where(:not([data-theme="dark"])){color-scheme:light;
 --bg:#f4f5f7;--card:#ffffff;--card-2:#f7f8fa;--ink:#0d1117;--ink-2:#3d4652;--muted:#626c79;
 --line:rgba(13,17,23,.10);--grid:#e3e6ea;--axis:#9aa3ae;
 --buy:#1f7fc0;--sell:#d4483b;--m0:#cfd5dd;--m1:#c77d0a;
 --t-bear:#d4483b;--t-bull:#138a99;--t-neutral:#6b778a;}}
:root[data-theme="light"]{color-scheme:light;
 --bg:#f4f5f7;--card:#ffffff;--card-2:#f7f8fa;--ink:#0d1117;--ink-2:#3d4652;--muted:#626c79;
 --line:rgba(13,17,23,.10);--grid:#e3e6ea;--axis:#9aa3ae;
 --buy:#1f7fc0;--sell:#d4483b;--m0:#cfd5dd;--m1:#c77d0a;
 --t-bear:#d4483b;--t-bull:#138a99;--t-neutral:#6b778a;}
*{box-sizing:border-box}
html,body{margin:0;min-height:100%}
body{background:var(--bg);color:var(--ink);
 font:15px/1.4 "Inter","SF Pro Display","Segoe UI",system-ui,-apple-system,sans-serif;
 font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
 background:radial-gradient(60% 55% at 50% 38%,color-mix(in srgb,var(--tone) 22%,transparent),transparent 70%),
 radial-gradient(40% 40% at 90% 0%,color-mix(in srgb,var(--tone) 10%,transparent),transparent 70%)}
body::after{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;opacity:.035;
 background-image:linear-gradient(45deg,var(--ink) 25%,transparent 25%,transparent 75%,var(--ink) 75%),
 linear-gradient(45deg,var(--ink) 25%,transparent 25%,transparent 75%,var(--ink) 75%);
 background-size:3px 3px;background-position:0 0,1.5px 1.5px}
body.bear{--tone:var(--t-bear)} body.bull{--tone:var(--t-bull)} body.neutral{--tone:var(--t-neutral)}
.root{position:relative;z-index:1;max-width:1200px;margin:0 auto;padding:18px 28px 10px;
 min-height:100vh;display:flex;flex-direction:column;gap:14px}
.root[hidden],#tip[hidden]{display:none!important}
.root[dir="rtl"]{font-family:"SF Arabic","Noto Kufi Arabic","Noto Sans Arabic","Segoe UI",Tahoma,sans-serif}
.root.fade{animation:fade .35s ease-out}
@keyframes fade{from{opacity:0}to{opacity:1}}
.lbl{font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}
[dir="rtl"] .lbl{text-transform:none;letter-spacing:0;font-size:13px}
.sub{font-size:12px;color:var(--muted)}
.num{font-variant-numeric:tabular-nums}
/* top bar */
.top{display:flex;align-items:center;gap:24px}
.ident{display:flex;align-items:center;gap:14px;flex:1;min-width:0}
.mono{width:48px;height:48px;border-radius:50%;display:grid;place-items:center;font-weight:800;
 font-size:17px;color:#fff;letter-spacing:.02em;flex:none;
 background:linear-gradient(135deg,hsl(var(--h) 70% 52%),hsl(calc(var(--h) + 50) 70% 38%));
 box-shadow:0 0 0 1px var(--line),0 6px 18px hsl(var(--h) 60% 30% / .35)}
.name{font-size:28px;font-weight:750;line-height:1.1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chips{display:flex;gap:6px;margin-top:4px}
.chip{font-size:11px;font-weight:650;padding:2px 8px;border-radius:999px;border:1px solid var(--line);
 color:var(--ink-2);background:var(--card);letter-spacing:.04em}
.price{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;justify-content:flex-end}
.price .big{font-size:40px;font-weight:700;letter-spacing:-.01em}
.pill{font-size:13px;font-weight:600;padding:3px 10px;border-radius:999px;border:1px solid var(--line);
 background:var(--card);color:var(--ink-2)}
.toggle{display:flex;border:1px solid var(--line);border-radius:999px;padding:3px;background:var(--card);flex:none}
.toggle button{font:inherit;font-size:13px;font-weight:650;border:0;background:transparent;color:var(--ink-2);
 padding:5px 12px;border-radius:999px;cursor:pointer}
.toggle button[aria-pressed="true"]{background:var(--ink);color:var(--bg)}
.toggle button:focus-visible{outline:2px solid var(--tone);outline-offset:2px}
/* hero */
.hero{display:flex;align-items:center;gap:22px;flex-wrap:wrap;padding:6px 0 2px}
.hero-line{margin:0;font-size:34px;line-height:1.15;font-weight:780;letter-spacing:-.015em;flex:1 1 560px}
[dir="rtl"] .hero-line{letter-spacing:0}
.hero-meta{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.badge{font-size:14px;font-weight:700;padding:7px 14px;border-radius:12px;
 background:color-mix(in srgb,var(--tone) 18%,var(--card));border:1px solid color-mix(in srgb,var(--tone) 45%,transparent)}
.stamp{font-size:14px;font-weight:800;text-transform:uppercase;letter-spacing:.12em;padding:6px 14px;border-radius:10px;
 animation:pop .5s cubic-bezier(.2,1.6,.4,1) .95s both}
[dir="rtl"] .stamp{letter-spacing:0}
.stamp.disagree{border:2px solid var(--tone);color:var(--ink);transform:rotate(-3deg);
 box-shadow:0 0 22px color-mix(in srgb,var(--tone) 35%,transparent)}
.stamp.agree,.stamp.neutral{border:1px solid var(--line);color:var(--ink-2)}
@keyframes pop{from{opacity:0;transform:scale(1.5) rotate(-3deg)}to{opacity:1}}
.conf{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--ink-2)}
.pips{display:flex;gap:4px}.pips i{width:9px;height:9px;border-radius:50%;border:1.5px solid var(--ink-2)}
.pips i.on{background:var(--ink);border-color:var(--ink)}
/* face-off */
.faceoff{position:relative;display:grid;grid-template-columns:minmax(0,1fr) 124px minmax(0,1fr);align-items:stretch;gap:0;
 flex:1 1 auto;min-height:0;max-height:400px;margin:auto 0}
.faceoff::before{content:"";position:absolute;inset-inline:18%;top:50%;height:2px;background:var(--line);z-index:0}
.faceoff.clash::before{background:linear-gradient(90deg,transparent,var(--tone),transparent);
 box-shadow:0 0 16px var(--tone);animation:glow 2.4s ease-in-out infinite alternate}
@keyframes glow{from{opacity:.55}to{opacity:1}}
.faceoff.solo{grid-template-columns:minmax(0,560px);justify-content:center}
.faceoff.solo::before{display:none}
.side{position:relative;z-index:1;background:color-mix(in srgb,var(--card) 88%,transparent);
 border:1px solid var(--line);border-radius:20px;padding:18px 22px;display:flex;flex-direction:column;gap:12px;
 backdrop-filter:blur(8px);min-width:0}
.side-body{flex:1;display:flex;flex-direction:column;justify-content:center;gap:16px}
.side-h{display:flex;align-items:baseline;justify-content:space-between;gap:8px}
.dir{font-size:44px;font-weight:800;line-height:1;display:flex;align-items:center;gap:10px}
.dir .arrow{font-size:34px;color:var(--ink-2)}
.line{margin:6px 0 0;color:var(--ink-2);font-size:14px}
.chart{display:flex;flex-direction:column;gap:6px}
.chart-h{display:flex;justify-content:space-between;align-items:baseline}
.chart-h .val{font-size:22px;font-weight:750}
.ends{display:flex;justify-content:space-between;font-size:13px;color:var(--ink-2);gap:10px}
.ends b{color:var(--ink);font-size:15px}
.ends.sub{font-size:12px;color:var(--muted)}
.axis-ltr{direction:ltr;unicode-bidi:isolate}
.sw{display:inline-block;width:10px;height:10px;border-radius:3px;margin-inline:6px;vertical-align:-1px}
.sw.buy{background:var(--buy)} .sw.sell{background:var(--sell)}
svg{display:block}
svg.bar{width:100%;height:14px;overflow:visible}
svg.bar.net{height:20px}
[dir="rtl"] .mirror svg{transform:scaleX(-1)}
.grow{transform-box:fill-box;animation:grow .9s cubic-bezier(.2,.8,.2,1) both}
.grow.gl{transform-origin:left center}.grow.gr{transform-origin:right center}
@keyframes grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.mark{cursor:default}.mark:hover{filter:brightness(1.12)}
.vs{position:relative;z-index:2;display:flex;flex-direction:row;align-items:center;justify-content:center;gap:4px}
.vs-dot{width:58px;height:58px;border-radius:50%;display:grid;place-items:center;font-weight:850;font-size:15px;
 letter-spacing:.08em;background:var(--card-2);border:1px solid var(--line);
 box-shadow:0 0 0 6px var(--bg)}
.clash .vs-dot{border-color:var(--tone);box-shadow:0 0 0 6px var(--bg),0 0 24px color-mix(in srgb,var(--tone) 45%,transparent)}
.va{font-size:22px;color:var(--ink-2);line-height:1}
.vs.solo{padding:4px 0}.vs-note{font-size:13px;color:var(--muted);border:1px dashed var(--line);padding:4px 12px;border-radius:999px}
.faceoff.solo .vs{order:-1}
.gauges{display:flex;flex-wrap:wrap;gap:26px;align-items:center;justify-content:center;flex:1}
.g-wrap{display:flex;flex-direction:column;align-items:center;gap:4px;position:relative}
.g-wrap.small{opacity:.95}
.g-title{display:flex;flex-direction:column;align-items:center}
svg.gauge.lg{width:250px;height:auto}
svg.gauge.sm{width:150px;height:auto}
.needle{transform-box:view-box;transform-origin:100px 100px;transform:rotate(var(--a));
 animation:sweep 1.1s cubic-bezier(.2,.8,.2,1) both}
@keyframes sweep{from{transform:rotate(0deg)}to{transform:rotate(var(--a))}}
.g-read{display:flex;align-items:baseline;gap:10px;margin-top:-10px}
.g-read .big{font-size:48px;font-weight:800;line-height:1}
.g-read .mid{font-size:28px;font-weight:750}
.bucket{font-size:18px;font-weight:700;color:var(--ink-2)}
.tag{font-size:12px;color:var(--ink-2);border:1px solid var(--line);border-radius:999px;padding:2px 10px}
/* details + footer */
.details{margin-top:auto;border:1px solid var(--line);border-radius:14px;background:color-mix(in srgb,var(--card) 70%,transparent)}
.details summary{cursor:pointer;padding:8px 16px;font-size:13px;font-weight:650;color:var(--ink-2)}
.dgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:4px 26px;padding:4px 16px 14px}
.dblock h3{font-size:12px;margin:8px 0 4px;color:var(--muted);font-weight:700}
.dblock ul{margin:0;padding:0;list-style:none;font-size:12.5px;color:var(--ink-2)}
.dblock li{margin:0 0 3px;overflow-wrap:anywhere}
.foot{font-size:12px;color:var(--muted);text-align:center;padding-bottom:4px}
bdi.nw{white-space:nowrap}
#tip{position:absolute;z-index:20;pointer-events:none;background:var(--card-2);color:var(--ink);
 border:1px solid var(--line);border-radius:8px;padding:5px 9px;font-size:13px;font-weight:650;
 box-shadow:0 6px 20px rgba(0,0,0,.35)}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}
@media (max-width:860px){
 .root{padding:14px 14px 8px}
 .top{flex-wrap:wrap;gap:12px}.price{justify-content:flex-start}.price .big{font-size:30px}
 .hero-line{font-size:24px;flex-basis:100%}
 .faceoff,.faceoff.solo{grid-template-columns:1fr;gap:10px}
 .faceoff::before{display:none}.vs{flex-direction:row}
 .dir{font-size:34px}.name{font-size:22px}
 svg.gauge.lg{width:220px}
}
@media (prefers-reduced-motion: reduce){
 .grow,.needle,.stamp,.root.fade,.faceoff.clash::before{animation:none!important}
}
"""

JS = """
(function(){
  var roots=[].slice.call(document.querySelectorAll('.root'));
  function setLang(lg,fade){
    roots.forEach(function(r){var on=r.getAttribute('data-lang')===lg;r.hidden=!on;
      if(on&&fade){r.classList.remove('fade');void r.offsetWidth;r.classList.add('fade');}});
    document.documentElement.lang=lg;document.documentElement.dir=(lg==='ar'?'rtl':'ltr');
    document.querySelectorAll('.toggle button').forEach(function(b){b.setAttribute('aria-pressed',String(b.getAttribute('data-set')===lg));});
  }
  function cur(){var r=roots.filter(function(x){return !x.hidden;})[0];return r?r.getAttribute('data-lang'):'en';}
  document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('.toggle button');
    if(b){setLang(b.getAttribute('data-set'),true);history.replaceState(null,'','#'+b.getAttribute('data-set'));}});
  document.addEventListener('keydown',function(e){if((e.key==='l'||e.key==='L')&&!e.metaKey&&!e.ctrlKey&&!e.altKey){
    var n=cur()==='en'?'ar':'en';setLang(n,true);history.replaceState(null,'','#'+n);}});
  window.addEventListener('hashchange',function(){var h=location.hash.slice(1);if(h==='ar'||h==='en')setLang(h,true);});
  var h=location.hash.slice(1);if(h==='ar'||h==='en')setLang(h,false);else setLang(cur(),false);
  // count-up (skipped with reduced motion)
  var reduce=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if(!reduce){document.querySelectorAll('[data-num]').forEach(function(el){
    var end=parseFloat(el.getAttribute('data-num')),dec=+el.getAttribute('data-dec'),pre=el.getAttribute('data-pre')||'',
        suf=el.getAttribute('data-suf')||'',comma=el.getAttribute('data-comma')==='1',final=el.textContent,t0=null;
    if(!isFinite(end))return;
    function fmt(x){var s=x.toFixed(dec);if(comma){var p=s.split('.');p[0]=p[0].replace(/\\B(?=(\\d{3})+(?!\\d))/g,',');s=p.join('.');}return pre+s+suf;}
    function step(ts){if(!t0)t0=ts;var k=Math.min(1,(ts-t0)/900),e=1-Math.pow(1-k,3);
      el.textContent=k<1?fmt(end*e):final;if(k<1)requestAnimationFrame(step);}
    requestAnimationFrame(step);});}
  // tooltips
  var tip=document.getElementById('tip');
  function show(e){var el=e.currentTarget;tip.textContent=el.getAttribute('data-tip');tip.hidden=false;
    var r=el.getBoundingClientRect(),x=r.left+scrollX+r.width/2-tip.offsetWidth/2;
    x=Math.max(scrollX+8,Math.min(x,scrollX+document.documentElement.clientWidth-tip.offsetWidth-8));
    tip.style.left=x+'px';tip.style.top=(r.top+scrollY-tip.offsetHeight-8)+'px';}
  function hide(){tip.hidden=true;}
  document.querySelectorAll('.mark').forEach(function(m){m.setAttribute('tabindex','0');
    m.addEventListener('pointerenter',show);m.addEventListener('pointerleave',hide);
    m.addEventListener('focus',show);m.addEventListener('blur',hide);});
})();
"""


def _defs() -> str:
    """Shared SVG gradients: the mood track (never the buy/sell hues)."""
    return ('<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>'
            '<linearGradient id="mood-fng" x1="0" x2="1" y1="0" y2="0">'
            '<stop offset="0" stop-color="var(--m0)"/><stop offset="1" stop-color="var(--m1)"/></linearGradient>'
            '<linearGradient id="mood-soc" x1="0" x2="1" y1="0" y2="0">'
            '<stop offset="0" stop-color="var(--m0)"/><stop offset="1" stop-color="var(--m1)"/></linearGradient>'
            "</defs></svg>")


def render_card(v: Verdict, lang: str = "en") -> str:
    """The full, self-contained HTML document (both languages, ``lang`` shown first)."""
    lang = lang if lang in LANGS else "en"
    name, sym = token_parts(v.token)
    title = f"Zalat · {name}{f' ({sym})' if sym and sym != name else ''} · {v.period}"
    roots = "".join(_root(v, lg, lg == lang) for lg in LANGS)
    return (
        f'<!doctype html>\n<html lang="{lang}" dir="{"rtl" if lang == "ar" else "ltr"}"><head>'
        '<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_e(title)}</title><style>{CSS}</style></head>"
        f'<body class="{tone(v)}">{_defs()}{roots}<div id="tip" role="status" hidden></div>'
        f"<script>{JS}</script></body></html>\n")


def default_card_path(v: Verdict, root: str | Path = "cards") -> Path:
    """``cards/zalat_<SYMBOL>_<period>_<YYYYMMDD-HHMM>.html``."""
    sym = v.token.symbol or short_address(v.token.address)
    sym = re.sub(r"[^A-Za-z0-9]+", "", sym) or "token"
    stamp = re.sub(r"[^0-9]", "", (v.generated_at or "")[:16])
    stamp = f"{stamp[:8]}-{stamp[8:12]}" if len(stamp) >= 12 else "undated"
    return Path(root) / f"zalat_{sym}_{v.period}_{stamp}.html"


def write_card(v: Verdict, path: str | Path | None = None, lang: str = "en") -> Path:
    """Write the card (creating folders) and return its path."""
    out = Path(path) if path else default_card_path(v)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_card(v, lang), encoding="utf-8")
    return out


# --------------------------------------------------------------------------- #
# --json output -> Verdict (for ``python -m zalat.card --from-json``)
# --------------------------------------------------------------------------- #
def _build(cls: Any, d: dict | None) -> Any:
    if d is None:
        return None
    names = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in d.items() if k in names})


def _pairs(items: list | None) -> list[tuple[str, dict]]:
    return [(i["key"], i.get("params") or {}) for i in (items or [])]


def verdict_from_dict(d: dict) -> Verdict:
    """Rebuild a :class:`Verdict` from ``render_json`` output."""
    smd = dict(d["sm"])
    for k in ("flow", "top_pnl"):
        if smd.get(k):
            smd[k] = _build(SmFlow, {**smd[k], "source_row": {}})
    for k in ("buy", "sell"):
        smd[k] = _build(BuySellSide, smd.get(k))
    smd["unavailable_reasons"] = _pairs(smd.get("unavailable_reasons"))
    return Verdict(
        token=_build(TokenRef, d["token"]), period=d["period"], sm=_build(SmartMoneySignal, smd),
        market_mood=_build(CrowdSignal, d["market_mood"]), kind=d["kind"],
        divergence=d.get("divergence"), disagreement=d.get("disagreement", False),
        confidence=d["confidence"], reasons=_pairs(d.get("reasons")), notes=_pairs(d.get("notes")),
        generated_at=d.get("generated_at", ""), social=_build(SocialSignal, d.get("social")),
        price=_build(PriceContext, d.get("price")), crowd_source=d.get("crowd_source"),
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m zalat.card",
                                description="Build the bilingual HTML card from saved --json output.")
    p.add_argument("--from-json", required=True, help="file written by `python -m zalat ... --json`")
    p.add_argument("--out", help="output path (default: cards/zalat_<SYMBOL>_<period>_<time>.html)")
    p.add_argument("--lang", choices=LANGS, default="en", help="language shown first (default: en)")
    args = p.parse_args(argv)
    try:
        data = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        path = write_card(verdict_from_dict(data), args.out, args.lang)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Error: cannot build the card: {exc}", file=sys.stderr)
        return 2
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
