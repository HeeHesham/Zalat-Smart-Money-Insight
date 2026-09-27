"""Bilingual HTML "verdict card": one self-contained file (inline CSS + SVG).

``python -m zalat LINK --period 7d --html`` writes a card next to the terminal
output; ``python -m zalat.card --from-json verdict.json [--out card.html]``
rebuilds one from saved ``--json`` output.

The card has the same structure as the terminal text: a header (token facts),
then 1 · on-chain smart money (Nansen), 2 · market sentiment, 3 · final
verdict. Each section has language-neutral charts on top and the English and
Arabic text side by side (stacked on narrow screens).

Chart rules (see README): one axis per chart, thin bars with a 4px rounded
data end anchored at the baseline, a diverging blue/red pair for buy vs sell and
positive vs negative (validated for colour-vision deficiency in light and dark
mode), text always in ink colours, a hover/focus tooltip per mark, and a
visually hidden data table per chart. Missing data is shown as a muted
placeholder, never as a zero-length bar. No external fonts, scripts or CDNs:
the file opens offline.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import re
import sys
from html import escape
from pathlib import Path
from typing import Any, Iterable

from zalat.fng import CrowdSignal
from zalat.i18n import fmt_pct, fmt_price, fmt_score, fmt_usd, kind_text, label, t
from zalat.lunarcrush import SocialSignal
from zalat.nansen_mcp import TokenRef
from zalat.parsing import BuySellSide, SmFlow
from zalat.render import display_name, section_texts, short_address
from zalat.verdict import DISAGREEMENT_KINDS, PriceContext, SmartMoneySignal, Verdict

# Plot geometry (SVG user units; the SVG scales to its container width).
VB_W = 560
LABEL_W = 132          # left gutter for row labels
PLOT_X0 = LABEL_W
PLOT_X1 = VB_W - 72    # right gutter for the value label at the bar tip
BAR_H = 18             # <= 24px: thin bars
RADIUS = 4             # rounded data end

CSS = """
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #6f6d68;
  --grid: #e1e0d9; --axis: #c3c2b7; --mid: #f0efec; --ring: rgba(11,11,11,0.10);
  --pos: #2a78d6; --neg: #e34948;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7; --muted: #9a988f;
    --grid: #2c2c2a; --axis: #383835; --mid: #383835; --ring: rgba(255,255,255,0.10);
    --pos: #3987e5; --neg: #e66767;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7; --muted: #9a988f;
  --grid: #2c2c2a; --axis: #383835; --mid: #383835; --ring: rgba(255,255,255,0.10);
  --pos: #3987e5; --neg: #e66767;
}
* { box-sizing: border-box; }
html, body { margin: 0; }
body { background: var(--page); color: var(--ink);
  font: 15px/1.45 system-ui, -apple-system, "Segoe UI", "Noto Sans Arabic", Tahoma, sans-serif; }
.card { max-width: 1240px; margin: 0 auto; padding: 16px; }
.panel { background: var(--surface); border: 1px solid var(--ring); border-radius: 12px;
  padding: 16px 18px; margin: 0 0 14px; }
.eyebrow { margin: 0; color: var(--ink-2); font-size: 13px; }
h1 { margin: 2px 0 2px; font-size: 26px; line-height: 1.2; }
.meta { margin: 0; color: var(--ink-2); font-size: 14px; }
.hdr-top { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-start;
  justify-content: space-between; }
.pill { border: 1px solid var(--axis); border-radius: 999px; padding: 6px 14px; font-weight: 600;
  background: var(--mid); white-space: normal; }
.banner { margin: 12px 0 0; padding: 10px 14px; border-radius: 8px; background: var(--mid);
  border-inline-start: 4px solid var(--ink); font-weight: 700; display: grid; gap: 4px; }
h2 { margin: 0 0 10px; font-size: 17px; display: flex; flex-wrap: wrap; gap: 4px 16px;
  justify-content: space-between; border-bottom: 1px solid var(--grid); padding-bottom: 8px; }
.viz { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px;
  margin: 0 0 12px; }
figure { position: relative; margin: 0; padding: 10px 12px; border: 1px solid var(--grid); border-radius: 10px; min-width: 0; }
figcaption { font-size: 13px; color: var(--ink-2); margin: 0 0 6px; display: grid; gap: 1px; }
svg { display: block; width: 100%; height: auto; overflow: visible; }
svg text { fill: var(--ink-2); font-size: 13px; }
svg .val { fill: var(--ink); font-weight: 600; }
svg .tick { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.placeholder { color: var(--muted); font-style: italic; margin: 18px 0; display: grid; gap: 2px; }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 28px; }
.col p { margin: 0 0 4px; overflow-wrap: anywhere; }
.col p.blank { height: 6px; }
.col p.indent { padding-inline-start: 14px; }
.col p.strong { font-weight: 700; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.tile { border: 1px solid var(--grid); border-radius: 10px; padding: 10px 12px; min-width: 0; }
.tile .lbl { font-size: 12px; color: var(--ink-2); display: grid; }
.tile .num { font-size: 24px; font-weight: 650; margin-top: 2px; overflow-wrap: anywhere; }
.mark { cursor: default; outline: none; }
.mark:hover .bar, .mark:focus .bar { opacity: 0.8; }
.mark:focus-visible .hit { stroke: var(--ink); stroke-width: 1; }
#tip { position: absolute; pointer-events: none; background: var(--surface); color: var(--ink);
  border: 1px solid var(--axis); border-radius: 6px; padding: 4px 8px; font-size: 13px;
  font-weight: 600; box-shadow: 0 2px 8px rgba(0,0,0,.15); z-index: 10; max-width: 280px; }
bdi.nw { white-space: nowrap; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden;
  clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
.foot { color: var(--ink-2); font-size: 13px; display: grid; gap: 2px; }
[dir="rtl"] { text-align: right; }
@media (max-width: 760px) {
  /* charts scale down with the screen: enlarge SVG text so it stays ~11px */
  svg text { font-size: 20px; }
  svg .tick { font-size: 17px; }
  .cols { grid-template-columns: 1fr; }
  h1 { font-size: 22px; }
  .card { padding: 10px; }
  .panel { padding: 12px; }
}
"""

JS = """
(function () {
  var tip = document.getElementById('tip');
  function show(e) {
    var el = e.currentTarget;
    tip.textContent = el.getAttribute('data-tip');
    tip.hidden = false;
    var r = el.getBoundingClientRect();
    var x = r.left + window.scrollX + r.width / 2 - tip.offsetWidth / 2;
    x = Math.max(window.scrollX + 8, Math.min(x, window.scrollX + document.documentElement.clientWidth - tip.offsetWidth - 8));
    tip.style.left = x + 'px';
    tip.style.top = (r.top + window.scrollY - tip.offsetHeight - 6) + 'px';
  }
  function hide() { tip.hidden = true; }
  document.querySelectorAll('.mark').forEach(function (m) {
    m.addEventListener('pointerenter', show); m.addEventListener('pointerleave', hide);
    m.addEventListener('focus', show); m.addEventListener('blur', hide);
  });
})();
"""


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _e(x: Any) -> str:
    return escape(str(x), quote=True)


def _bi(key: str, **kw: Any) -> str:
    """Bilingual inline label: English then Arabic (RTL span)."""
    return (f'<span lang="en">{_e(t(key, "en", **kw))}</span>'
            f'<span lang="ar" dir="rtl">{_isolate_ltr(t(key, "ar", **kw))}</span>')


def nice_max(x: float) -> float:
    """Round up to 1, 2, 2.5 or 5 x 10^k so axis ticks are clean numbers."""
    if x <= 0:
        return 1.0
    exp = math.floor(math.log10(x))
    for m in (1, 2, 2.5, 5, 10):
        if m * 10 ** exp >= x:
            return m * 10 ** exp
    return 10 ** (exp + 1)  # pragma: no cover


def _bar_path(x0: float, y: float, w: float, h: float, right: bool = True) -> str:
    """Horizontal bar, square at the baseline ``x0``, rounded at the data end."""
    r = min(RADIUS, abs(w), h / 2)
    if w <= 0:
        return ""
    if right:
        x1 = x0 + w
        return (f"M{x0:.1f},{y:.1f} H{x1 - r:.1f} Q{x1:.1f},{y:.1f} {x1:.1f},{y + r:.1f} "
                f"V{y + h - r:.1f} Q{x1:.1f},{y + h:.1f} {x1 - r:.1f},{y + h:.1f} H{x0:.1f} Z")
    x1 = x0 - w
    return (f"M{x0:.1f},{y:.1f} H{x1 + r:.1f} Q{x1:.1f},{y:.1f} {x1:.1f},{y + r:.1f} "
            f"V{y + h - r:.1f} Q{x1:.1f},{y + h:.1f} {x1 + r:.1f},{y + h:.1f} H{x0:.1f} Z")


def _placeholder(key: str, **kw: Any) -> str:
    return f'<div class="placeholder">{_bi(key, **kw)}</div>'


def _table(caption_key: str, rows: Iterable[tuple[str, str]]) -> str:
    body = "".join(f"<tr><td>{_e(a)}</td><td>{_e(b)}</td></tr>" for a, b in rows)
    # Tables ignore width:1px, so the visually-hidden wrapper is a div.
    return (f'<div class="sr-only"><table><caption>{_e(t(caption_key, "en"))} / '
            f'{_e(t(caption_key, "ar"))}</caption><tr><th>{_e(t("card_table_item", "en"))}</th>'
            f'<th>{_e(t("card_table_value", "en"))}</th></tr>{body}</table></div>')


def _figure(title_key: str, inner: str) -> str:
    return f'<figure><figcaption>{_bi(title_key)}</figcaption>{inner}</figure>'


# --------------------------------------------------------------------------- #
# charts
# --------------------------------------------------------------------------- #
def chart_buy_sell(sm: SmartMoneySignal) -> str:
    """Two horizontal bars on one zero-based USD axis: bought vs sold."""
    if sm.buy is None or sm.sell is None or sm.buy.volume_usd is None or sm.sell.volume_usd is None:
        return _figure("card_bs_title", _placeholder("card_unavailable"))
    b, s = sm.buy.volume_usd, sm.sell.volume_usd
    if b + s <= 0:
        return _figure("card_bs_title", _placeholder("no_sm_trades"))
    top = nice_max(max(b, s))
    span = PLOT_X1 - PLOT_X0
    rows = [("card_bought", b, "var(--pos)"), ("card_sold", s, "var(--neg)")]
    y0, step = 8, 34
    axis_y = y0 + step * len(rows) + 2
    h = axis_y + 22
    parts = [f'<svg viewBox="0 0 {VB_W} {h}" role="img" aria-label="{_e(t("card_bs_title", "en"))}">']
    for frac in (0, 0.5, 1):
        x = PLOT_X0 + span * frac
        parts.append(f'<line x1="{x:.1f}" y1="{y0 - 4}" x2="{x:.1f}" y2="{axis_y}" '
                     f'stroke="var(--grid)" stroke-width="1"/>')
        parts.append(f'<text class="tick" x="{x:.1f}" y="{axis_y + 16}" text-anchor="middle">'
                     f'{_e(fmt_usd(top * frac))}</text>')
    parts.append(f'<line x1="{PLOT_X0}" y1="{y0 - 4}" x2="{PLOT_X0}" y2="{axis_y}" '
                 f'stroke="var(--axis)" stroke-width="1"/>')
    for i, (key, val, color) in enumerate(rows):
        y = y0 + i * step
        w = span * val / top
        tip = f'{t(key, "en")} / {t(key, "ar")}: {fmt_usd(val)}'
        parts.append(f'<g class="mark" tabindex="0" data-tip="{_e(tip)}">'
                     f'<rect class="hit" x="0" y="{y - 6}" width="{VB_W}" height="{BAR_H + 12}" '
                     f'fill="transparent"/>'
                     f'<text x="{PLOT_X0 - 8}" y="{y + BAR_H - 4}" text-anchor="end">'
                     f'{_e(t(key, "en"))} · {_e(t(key, "ar"))}</text>')
        if w > 0:
            parts.append(f'<path class="bar" d="{_bar_path(PLOT_X0, y, w, BAR_H)}" fill="{color}"/>')
        parts.append(f'<text class="val" x="{PLOT_X0 + w + 6:.1f}" y="{y + BAR_H - 4}">'
                     f'{_e(fmt_usd(val))}</text></g>')
    parts.append("</svg>")
    table = _table("card_bs_title", [(t("card_bought", "en"), fmt_usd(b)),
                                     (t("card_sold", "en"), fmt_usd(s))])
    return _figure("card_bs_title", "".join(parts) + table)


def chart_net_flow(sm: SmartMoneySignal) -> str:
    """One diverging bar from a centred zero line: net inflow right, outflow left."""
    f = sm.flow
    if f is None or f.net_usd is None or f.is_empty:
        return _figure("card_flow_title", _placeholder("no_sm_flow" if f is not None and f.is_empty
                                                       else "card_unavailable"))
    net = f.net_usd
    gross = None
    if sm.buy is not None and sm.sell is not None and sm.buy.volume_usd is not None \
            and sm.sell.volume_usd is not None:
        gross = sm.buy.volume_usd + sm.sell.volume_usd
    dom = nice_max(max(abs(net), gross or 0.0))
    x0, x1 = 24, VB_W - 24
    cx = (x0 + x1) / 2
    half = (x1 - x0) / 2
    y, h = 26, 44 + 26
    w = half * abs(net) / dom
    color = "var(--pos)" if net > 0 else "var(--neg)"
    value = ("+" if net > 0 else "") + fmt_usd(net)
    parts = [f'<svg viewBox="0 0 {VB_W} {h + 20}" role="img" aria-label="{_e(t("card_flow_title", "en"))}">']
    for frac in (-1, -0.5, 0.5, 1):
        x = cx + half * frac
        parts.append(f'<line x1="{x:.1f}" y1="{y - 12}" x2="{x:.1f}" y2="{y + BAR_H + 12}" '
                     f'stroke="var(--grid)" stroke-width="1"/>')
    for frac in (-1, 0, 1):
        x = cx + half * frac
        lab = ("+" if frac > 0 else "") + fmt_usd(dom * frac)
        parts.append(f'<text class="tick" x="{x:.1f}" y="{y + BAR_H + 28}" '
                     f'text-anchor="{"start" if frac < 0 else "end" if frac > 0 else "middle"}">'
                     f'{_e(lab)}</text>')
    tip = f'{t("card_flow_title", "en")}: {value}'
    parts.append(f'<g class="mark" tabindex="0" data-tip="{_e(tip)}">'
                 f'<rect class="hit" x="{x0}" y="{y - 8}" width="{x1 - x0}" height="{BAR_H + 16}" '
                 f'fill="transparent"/>')
    if w > 0:
        parts.append(f'<path class="bar" d="{_bar_path(cx, y, w, BAR_H, right=net > 0)}" '
                     f'fill="{color}"/>')
    # value label just beyond the bar end, kept inside the plot
    if net > 0:
        lx, anchor = min(cx + w + 6, x1), "start" if cx + w + 80 < x1 else "end"
        if anchor == "end":
            lx = cx + w - 6 if w > 90 else x1
    else:
        lx, anchor = max(cx - w - 6, x0), "end" if cx - w - 80 > x0 else "start"
        if anchor == "start":
            lx = cx - w + 6 if w > 90 else x0
    label_cls = "val"
    parts.append(f'<text class="{label_cls}" x="{lx:.1f}" y="{y - 6}" text-anchor="{anchor}">'
                 f'{_e(value)}</text></g>')
    parts.append(f'<line x1="{cx:.1f}" y1="{y - 12}" x2="{cx:.1f}" y2="{y + BAR_H + 12}" '
                 f'stroke="var(--axis)" stroke-width="1.5"/>')
    parts.append("</svg>")
    return _figure("card_flow_title", "".join(parts) + _table("card_flow_title",
                                                              [("Net flow", value)]))


def _gauge(value: float, bounds: tuple[float, ...], caption_en: str, caption_ar: str,
           tip: str) -> str:
    x0, x1 = 16, VB_W - 16
    span = x1 - x0
    y = 18
    parts = [f'<svg viewBox="0 0 {VB_W} 58" role="img" aria-label="{_e(caption_en)}">',
             f'<rect x="{x0}" y="{y}" width="{span}" height="8" rx="4" fill="var(--mid)"/>']
    for bnd in bounds:
        x = x0 + span * bnd / 100
        parts.append(f'<line x1="{x:.1f}" y1="{y - 3}" x2="{x:.1f}" y2="{y + 11}" '
                     f'stroke="var(--axis)" stroke-width="1"/>')
    for v in (0,) + bounds + (100,):
        x = x0 + span * v / 100
        anchor = "start" if v == 0 else "end" if v == 100 else "middle"
        parts.append(f'<text class="tick" x="{x:.1f}" y="{y + 28}" text-anchor="{anchor}">{v:g}</text>')
    mx = x0 + span * max(0.0, min(100.0, value)) / 100
    parts.append(f'<g class="mark" tabindex="0" data-tip="{_e(tip)}">'
                 f'<circle class="hit" cx="{mx:.1f}" cy="{y + 4}" r="14" fill="transparent"/>'
                 f'<circle class="bar" cx="{mx:.1f}" cy="{y + 4}" r="7" fill="var(--ink)" '
                 f'stroke="var(--surface)" stroke-width="2"/></g></svg>')
    head = (f'<div class="gauge-head"><strong>{_e(caption_en)}</strong>'
            f' · <span lang="ar" dir="rtl">{_isolate_ltr(caption_ar)}</span></div>')
    return head + "".join(parts)


def chart_market(v: Verdict) -> str:
    m = v.market_mood
    if not m.available or m.value is None:
        return _figure("card_fng_title", _placeholder("market_na"))
    cap_en = f'{label(m.label, "en")} {m.value}/100 · {t("card_market_wide", "en")}'
    cap_ar = f'{label(m.label, "ar")} {m.value}/100 · {t("card_market_wide", "ar")}'
    inner = _gauge(m.value, (25, 45, 56, 76), cap_en, cap_ar, f"{cap_en} / {cap_ar}")
    return _figure("card_fng_title", inner + _table("card_fng_title", [("Fear & Greed", f"{m.value}/100"),
                                                                       ("Bucket", m.label)]))


def chart_social(v: Verdict) -> str:
    s = v.social
    if s is None or not s.available or s.sentiment is None:
        status = s.status if s is not None else "not_configured"
        key = "card_not_configured" if status == "not_configured" else f"social_status_{status}"
        params = {"fallback": False, "code": s.http_status} if s is not None else {}
        return _figure("card_social_title", _placeholder(key, **params))
    cap_en = f'{label(s.label, "en")} {s.sentiment:.0f}%'
    cap_ar = f'{label(s.label, "ar")} {s.sentiment:.0f}%'
    inner = _gauge(s.sentiment, (20, 40, 60, 80), cap_en, cap_ar, f"{cap_en} / {cap_ar}")
    return _figure("card_social_title", inner + _table("card_social_title",
                                                       [("Sentiment", f"{s.sentiment:.0f}%"),
                                                        ("Bucket", s.label)]))


def tiles_verdict(v: Verdict) -> str:
    def tile(key: str, value: str) -> str:
        return (f'<div class="tile"><div class="lbl">{_bi(key)}</div>'
                f'<div class="num">{_e(value)}</div></div>')
    conf = f'{label(v.confidence, "en")} · {label(v.confidence, "ar")}'
    return ('<div class="tiles">' + tile("card_score", fmt_score(v.sm.score))
            + tile("card_confidence", conf)
            + tile("card_divergence", fmt_score(v.divergence)) + "</div>")


def tiles_facts(v: Verdict) -> str:
    p = v.price
    items = []
    if p is not None and p.price_usd is not None:
        items.append(("Price · السعر", fmt_price(p.price_usd)))
    if p is not None and p.change_pct is not None:
        items.append((f'{t("card_change", "en")} · {t("card_change", "ar")}',
                      fmt_pct(p.change_pct)))
    if p is not None and p.market_cap_usd is not None:
        items.append(("Market cap · القيمة السوقية", fmt_usd(p.market_cap_usd)))
    if p is not None and p.liquidity_usd is not None:
        items.append(("Liquidity · السيولة", fmt_usd(p.liquidity_usd)))
    if p is not None and p.holders is not None:
        items.append(("Holders · الحاملون", f"{int(p.holders):,}"))
    if not items:
        return ""
    return '<div class="tiles">' + "".join(
        f'<div class="tile"><div class="lbl">{_e(a)}</div><div class="num">{_e(b)}</div></div>'
        for a, b in items) + "</div>"


# --------------------------------------------------------------------------- #
# page
# --------------------------------------------------------------------------- #
#: A run of left-to-right material inside Arabic text: numbers, $ amounts,
#: dates, addresses, Latin words (Nansen, UTC...), possibly several separated
#: by spaces ("2026-09-27 21:07 UTC").
# ASCII only: \w would also match Arabic letters and swallow them into the LTR run.
_LTR_TOKEN = r"[+\-−]?\$?[0-9A-Za-z_][0-9A-Za-z_.,:%/$…\-]*"
_LTR_PAREN = r"(?:\s*\([0-9A-Za-z_$][0-9A-Za-z_ .,:%/$…\-]*\))?"   # "ChainLink (LINK)"
_LTR_RUN = re.compile(rf"{_LTR_TOKEN}{_LTR_PAREN}(?:\s+{_LTR_TOKEN}{_LTR_PAREN})*")


def _isolate_ltr(text: str) -> str:
    """Escape ``text`` and wrap LTR runs in ``<bdi dir="ltr">`` so numbers,
    signs and dates keep their order inside right-to-left Arabic lines."""
    out, pos = [], 0
    for m in _LTR_RUN.finditer(text):
        out.append(_e(text[pos:m.start()]))
        run = m.group(0)
        # Short runs ("ChainLink (LINK)", "Nansen OHLCV", "alternative.me") must not
        # be split by a line wrap: a broken isolate scrambles the brackets in RTL.
        cls = ' class="nw"' if len(run) <= 32 else ""
        out.append(f'<bdi dir="ltr"{cls}>{_e(run)}</bdi>')
        pos = m.end()
    out.append(_e(text[pos:]))
    return "".join(out)


def _col(lines: list[str], lang: str) -> str:
    attrs = 'lang="en"' if lang == "en" else 'lang="ar" dir="rtl"'
    fmt = _e if lang == "en" else _isolate_ltr
    out = []
    for ln in lines:
        cls = []
        if not ln.strip():
            cls.append("blank")
        if ln.startswith("  "):
            cls.append("indent")
        if ln.startswith(">>>"):
            cls.append("strong")
        c = f' class="{" ".join(cls)}"' if cls else ""
        out.append(f"<p{c}>{fmt(ln.strip())}</p>")
    return f'<div class="col" {attrs}>{"".join(out)}</div>'


def render_card(v: Verdict) -> str:
    """The full, self-contained HTML document."""
    en, ar = section_texts(v, "en"), section_texts(v, "ar")
    name = display_name(v.token)
    short_en = kind_text(v.kind, "en", v.crowd_source)[0]
    short_ar = kind_text(v.kind, "ar", v.crowd_source)[0]
    ts = (v.generated_at or "")[:16].replace("T", " ")
    banner = ""
    if v.kind in DISAGREEMENT_KINDS:
        crowd = "crowd_name_social" if v.crowd_source == "token_social" else "crowd_name_market"
        banner = (f'<div class="banner" role="note">'
                  f'<span lang="en">{_e(t("banner", "en", crowd_name=t(crowd, "en").upper()))}</span>'
                  f'<span lang="ar" dir="rtl">{_isolate_ltr(t("banner", "ar", crowd_name=t(crowd, "ar")))}</span>'
                  f'</div>')
    visuals = {1: chart_buy_sell(v.sm) + chart_net_flow(v.sm),
               2: chart_market(v) + chart_social(v),
               3: tiles_verdict(v)}
    sections = []
    for i in range(1, 4):
        (h_en, l_en), (h_ar, l_ar) = en[i], ar[i]
        if i == 3:  # the disagreement banner is already shown at the top of the card
            l_en = [ln for ln in l_en if not ln.startswith(">>>")]
            l_ar = [ln for ln in l_ar if not ln.startswith(">>>")]
        sections.append(
            f'<section class="panel" aria-label="{_e(h_en)}">'
            f'<h2><span lang="en">{_e(h_en)}</span><span lang="ar" dir="rtl">{_e(h_ar)}</span></h2>'
            f'<div class="viz">{visuals[i]}</div>'
            f'<div class="cols">{_col(l_en, "en")}{_col(l_ar, "ar")}</div></section>')
    head_en, head_ar = en[0][1], ar[0][1]
    header = (
        f'<header class="panel"><div class="hdr-top"><div>'
        f'<p class="eyebrow">{_e(t("title", "en", name="").rstrip(" —"))} · '
        f'<span lang="ar" dir="rtl">{_e(t("title", "ar", name="").rstrip(" —"))}</span></p>'
        f'<h1>{_e(name)}</h1>'
        f'<p class="meta">{_e(v.token.chain)} · {_e(v.period)} · {_e(ts)} UTC · '
        f'{_e(short_address(v.token.address))}</p></div>'
        f'<div class="pill">{_e(short_en)} · <span lang="ar" dir="rtl">{_e(short_ar)}</span></div>'
        f'</div>{banner}<div style="margin-top:12px">{tiles_facts(v)}</div>'
        f'<div class="cols" style="margin-top:12px">{_col(head_en[1:], "en")}'
        f'{_col(head_ar[1:], "ar")}</div></header>')
    title = f"Zalat verdict — {name} ({v.period})"
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{_e(title)}</title><style>{CSS}</style></head>'
        f'<body><main class="card">{header}{"".join(sections)}</main>'
        '<div id="tip" role="status" hidden></div>'
        f'<script>{JS}</script></body></html>\n')


def default_card_path(v: Verdict, root: str | Path = "cards") -> Path:
    """``cards/zalat_<SYMBOL>_<period>_<YYYYMMDD-HHMM>.html``."""
    sym = v.token.symbol or short_address(v.token.address)
    sym = re.sub(r"[^A-Za-z0-9]+", "", sym) or "token"
    stamp = re.sub(r"[^0-9]", "", (v.generated_at or "")[:16])
    stamp = f"{stamp[:8]}-{stamp[8:12]}" if len(stamp) >= 12 else "undated"
    return Path(root) / f"zalat_{sym}_{v.period}_{stamp}.html"


def write_card(v: Verdict, path: str | Path | None = None) -> Path:
    """Write the card (creating folders) and return its path."""
    out = Path(path) if path else default_card_path(v)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_card(v), encoding="utf-8")
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
    args = p.parse_args(argv)
    try:
        data = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        path = write_card(verdict_from_dict(data), args.out)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Error: cannot build the card: {exc}", file=sys.stderr)
        return 2
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
