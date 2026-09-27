"""Turn a :class:`~zalat.verdict.Verdict` into text (EN / AR / both) or JSON."""

from __future__ import annotations

import dataclasses
import json
from typing import Literal

from zalat import __version__
from zalat.i18n import DISCLAIMER, Lang, fmt_score, fmt_usd, kind_text, label, t
from zalat.verdict import Verdict

DIVIDER = "=" * 60


def _block(v: Verdict, lang: Lang) -> str:
    """Render the verdict in one language."""
    tok, sm, crowd = v.token, v.sm, v.crowd
    short, headline, explanation = kind_text(v.kind, lang)
    lines = [
        t("title", lang),
        t("token_line", lang, symbol=tok.symbol, name=tok.name or tok.symbol,
          chain=tok.chain, period=v.period),
        t("address", lang, address=tok.address),
        "-" * 60,
        t("verdict", lang, headline=headline, kind=short),
        explanation,
        t("disagree_yes" if v.disagreement else "disagree_no", lang),
        "",
    ]

    if sm.label == "Unavailable":
        lines.append(t("sm_unavailable", lang))
    else:
        strength = f" ({label(sm.strength, lang)})" if sm.strength else ""
        lines.append(t("sm_line", lang, label=label(sm.label, lang), strength=strength,
                       score=fmt_score(sm.score)))
    f = sm.flow
    if f is not None and f.net_usd is not None:
        wallets = t("wallets_part", lang, n=f.wallets) if f.wallets is not None else ""
        lines.append(t("flow_line", lang, net=("+" if f.net_usd > 0 else "") + fmt_usd(f.net_usd),
                       inflow=fmt_usd(f.inflow_usd), outflow=fmt_usd(f.outflow_usd),
                       wallets=wallets))
    else:
        lines.append(t("flow_na", lang))
    if sm.buy is not None and sm.sell is not None:
        lines.append(t("bs_line", lang, buy=fmt_usd(sm.buy.volume_usd),
                       sell=fmt_usd(sm.sell.volume_usd), score=fmt_score(sm.bs_score)))
    else:
        lines.append(t("bs_na", lang))

    if crowd.available:
        lines.append(t("crowd_line", lang, label=label(crowd.label, lang), value=crowd.value))
    else:
        lines.append(t("crowd_na", lang))
    if v.divergence is not None:
        lines.append(t("divergence", lang, d=fmt_score(v.divergence)))

    lines.append("")
    lines.append(t("confidence", lang, level=label(v.confidence, lang)))
    if v.reasons:
        lines.append(t("why", lang))
        lines.extend(f"  - {t(key, lang, **params)}" for key, params in v.reasons)
    if v.notes:
        lines.append("")
        lines.extend(t(key, lang, **params) for key, params in v.notes)
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
    data["headline"] = {"en": kind_text(v.kind, "en")[1], "ar": kind_text(v.kind, "ar")[1]}
    data["crowd"]["scope"] = "market-wide (BTC-centric), not token-specific"
    data["disclaimer"] = {"en": DISCLAIMER["en"], "ar": DISCLAIMER["ar"]}
    data["version"] = __version__
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)
