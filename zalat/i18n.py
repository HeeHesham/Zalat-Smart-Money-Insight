"""English and Arabic strings.

All user-facing text lives here, keyed by a short id. ``t(key, lang, **kw)``
looks up and formats a string. Numbers are always formatted with Western
digits by :func:`fmt_usd` / :func:`fmt_score` so they read the same (and stay
left-to-right) inside Arabic text.
"""

from __future__ import annotations

from typing import Literal

from zalat import DISCLAIMER_AR, DISCLAIMER_EN

Lang = Literal["en", "ar"]

# Verdict kind -> (short name, headline, explanation)
KIND_TEXT: dict[str, dict[str, tuple[str, str, str]]] = {
    "en": {
        "CONTRARIAN_BULLISH": ("Contrarian Bullish", "Smart money is buying into fear",
                               "The crowd is fearful while smart-money wallets accumulate. "
                               "This is the kind of disagreement worth a closer look."),
        "WARNING_BEARISH": ("Warning (Bearish)", "Smart money is selling into greed",
                            "The crowd is greedy while smart-money wallets distribute. "
                            "Smart money may be taking profit from late buyers."),
        "CONFIRMED_BULLISH": ("Confirmed Bullish", "Smart money and the crowd are both bullish",
                              "Both sides agree. Agreement is less informative than disagreement."),
        "CONFIRMED_BEARISH": ("Confirmed Bearish", "Smart money and the crowd are both bearish",
                              "Both sides agree on the downside."),
        "NEUTRAL": ("Neutral", "No clear divergence",
                    "Either smart money or the crowd has no strong direction."),
        "INSUFFICIENT_DATA": ("Insufficient Data", "Not enough smart-money data for a verdict",
                              "Nansen data was unavailable or could not be read. "
                              "The crowd mood is still shown below."),
        "SM_ONLY": ("Smart Money Only", "Smart-money reading only (crowd mood unavailable)",
                    "The Fear & Greed index could not be fetched, so no contrast is possible."),
    },
    "ar": {
        "CONTRARIAN_BULLISH": ("صعود عكس الجمهور", "الأموال الذكية تشتري وسط الخوف",
                               "الجمهور خائف بينما محافظ الأموال الذكية تُجمِّع. "
                               "هذا النوع من التباين يستحق نظرة أعمق."),
        "WARNING_BEARISH": ("تحذير (هبوطي)", "الأموال الذكية تبيع وسط الطمع",
                            "يسيطر الطمع على الجمهور بينما محافظ الأموال الذكية تُصرِّف. "
                            "قد تكون الأموال الذكية تجني الأرباح من المشترين المتأخرين."),
        "CONFIRMED_BULLISH": ("صعود مؤكَّد", "الأموال الذكية والجمهور متفائلون معاً",
                              "الطرفان متفقان. الاتفاق أقل دلالة من الاختلاف."),
        "CONFIRMED_BEARISH": ("هبوط مؤكَّد", "الأموال الذكية والجمهور متشائمون معاً",
                              "الطرفان متفقان على الهبوط."),
        "NEUTRAL": ("محايد", "لا يوجد تباين واضح",
                    "لا يوجد اتجاه قوي لدى الأموال الذكية أو لدى الجمهور."),
        "INSUFFICIENT_DATA": ("بيانات غير كافية", "لا توجد بيانات كافية عن الأموال الذكية لإصدار حكم",
                              "بيانات Nansen غير متاحة أو تعذّرت قراءتها. "
                              "مزاج الجمهور معروض أدناه."),
        "SM_ONLY": ("الأموال الذكية فقط", "قراءة الأموال الذكية فقط (مزاج الجمهور غير متاح)",
                    "تعذّر جلب مؤشر الخوف والطمع، لذا لا يمكن إجراء المقارنة."),
    },
}

LABELS: dict[str, dict[str, str]] = {
    "en": {
        "Accumulating": "Accumulating", "Distributing": "Distributing", "Neutral": "Neutral",
        "Unavailable": "Unavailable", "Extreme Fear": "Extreme Fear", "Fear": "Fear",
        "Greed": "Greed", "Extreme Greed": "Extreme Greed",
        "strong": "strong", "moderate": "moderate", "weak": "weak",
        "High": "High", "Medium": "Medium", "Low": "Low",
    },
    "ar": {
        "Accumulating": "تجميع", "Distributing": "تصريف", "Neutral": "محايد",
        "Unavailable": "غير متاح", "Extreme Fear": "خوف شديد", "Fear": "خوف",
        "Greed": "طمع", "Extreme Greed": "طمع شديد",
        "strong": "قوي", "moderate": "متوسط", "weak": "ضعيف",
        "High": "مرتفعة", "Medium": "متوسطة", "Low": "منخفضة",
    },
}

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "title": "Zalat Smart Money Verdict",
        "token_line": "Token: {token} on {chain}, lookback {period}",
        "banner": ">>> DISAGREEMENT: SMART MONEY vs CROWD <<<",
        "address": "Address: {address}",
        "verdict": "VERDICT: {headline}  [{kind}]",
        "disagree_yes": "Disagreement: YES - smart money and the crowd point in opposite directions.",
        "disagree_no": "Disagreement: no",
        "sm_line": "Smart money: {label}{strength}, score {score}",
        "sm_unavailable": "Smart money: Unavailable",
        "flow_line": "  - Net flow: {net} (in {inflow} / out {outflow}{wallets})",
        "flow_na": "  - Net flow: unavailable",
        "wallets_part": ", {wallets}",
        "bs_line": "  - Smart buyers vs sellers: {buy} bought / {sell} sold (score {score})",
        "bs_na": "  - Smart buyers vs sellers: unavailable",
        "crowd_line": "Crowd mood: {label} ({value}/100) - market-wide Fear & Greed Index (BTC-centric), not token-specific",
        "crowd_na": "Crowd mood: Unavailable (Fear & Greed Index could not be fetched)",
        "divergence": "Divergence score: {d} (positive = smart money leans against the crowd)",
        "confidence": "Confidence: {level}",
        "why": "Why:",
        # confidence reasons
        "flow_unavailable": "smart-money flow data unavailable",
        "bs_unavailable": "smart buyer/seller data unavailable",
        "no_sm_trades": "no smart-money buys or sells in this period",
        "crowd_unavailable": "crowd mood (Fear & Greed) unavailable",
        "one_sm_part": "only one of the two smart-money signals was available",
        "weak_signal": "smart-money signal is weak (strength {s}, below 0.40)",
        "parts_disagree": "net flow and buyer/seller balance point in different directions",
        "low_wallets": "only {n} smart wallets involved",
        "crowd_neutral": "crowd mood is close to neutral (45-55)",
        # notes
        "crowded_trade": "Note: Extreme Greed - this may be a crowded trade.",
        "capitulation": "Note: both sides bearish - can indicate capitulation.",
        "lean_positive": "Mild lean: smart money slightly positive.",
        "lean_negative": "Mild lean: smart money slightly negative.",
        "sm_only": "Note: verdict is based on smart money alone.",
    },
    "ar": {
        "title": "حكم زلط للأموال الذكية",
        "token_line": "العملة: {token} على شبكة {chain}، الفترة {period}",
        "banner": ">>> تباين: الأموال الذكية عكس الجمهور <<<",
        "address": "العنوان: {address}",
        "verdict": "الحكم: {headline}  [{kind}]",
        "disagree_yes": "تباين: نعم - الأموال الذكية والجمهور في اتجاهين متعاكسين.",
        "disagree_no": "تباين: لا",
        "sm_line": "الأموال الذكية: {label}{strength}، الدرجة {score}",
        "sm_unavailable": "الأموال الذكية: غير متاح",
        "flow_line": "  - صافي التدفق: {net} (وارد {inflow} / صادر {outflow}{wallets})",
        "flow_na": "  - صافي التدفق: غير متاح",
        "wallets_part": "، {wallets}",
        "bs_line": "  - المشترون مقابل البائعين الأذكياء: شراء {buy} / بيع {sell} (الدرجة {score})",
        "bs_na": "  - المشترون مقابل البائعين الأذكياء: غير متاح",
        "crowd_line": "مزاج الجمهور: {label} ({value}/100) - مؤشر الخوف والطمع للسوق كله (يتمحور حول البيتكوين)، وليس خاصاً بهذه العملة",
        "crowd_na": "مزاج الجمهور: غير متاح (تعذّر جلب مؤشر الخوف والطمع)",
        "divergence": "درجة التباين: {d} (موجبة = الأموال الذكية عكس الجمهور)",
        "confidence": "الثقة: {level}",
        "why": "الأسباب:",
        "flow_unavailable": "بيانات تدفق الأموال الذكية غير متاحة",
        "bs_unavailable": "بيانات المشترين/البائعين الأذكياء غير متاحة",
        "no_sm_trades": "لا توجد عمليات شراء أو بيع من الأموال الذكية في هذه الفترة",
        "crowd_unavailable": "مزاج الجمهور (الخوف والطمع) غير متاح",
        "one_sm_part": "توفرت إشارة واحدة فقط من إشارتي الأموال الذكية",
        "weak_signal": "إشارة الأموال الذكية ضعيفة (قوتها {s}، أقل من 0.40)",
        "parts_disagree": "صافي التدفق وتوازن الشراء/البيع في اتجاهين مختلفين",
        "low_wallets": "عدد المحافظ الذكية المشاركة {n} فقط",
        "crowd_neutral": "مزاج الجمهور قريب من المحايد (45-55)",
        "crowded_trade": "ملاحظة: طمع شديد - قد تكون صفقة مزدحمة.",
        "capitulation": "ملاحظة: الطرفان متشائمان - قد يدل ذلك على استسلام البائعين.",
        "lean_positive": "ميل طفيف: الأموال الذكية إيجابية قليلاً.",
        "lean_negative": "ميل طفيف: الأموال الذكية سلبية قليلاً.",
        "sm_only": "ملاحظة: الحكم مبني على الأموال الذكية وحدها.",
    },
}

DISCLAIMER = {"en": DISCLAIMER_EN, "ar": DISCLAIMER_AR}


def fmt_usd(x: float | None) -> str:
    """Compact signed USD: 1_234_567 -> "$1.2M", -3400 -> "-$3.4k"; None -> "n/a"."""
    if x is None:
        return "n/a"
    sign = "-" if x < 0 else ""
    a = abs(x)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "k")):
        if a >= div:
            return f"{sign}${a / div:.1f}{suf}"
    return f"{sign}${a:,.0f}" if a >= 1 else f"{sign}${a:.2f}"


def fmt_wallets(n: int, lang: Lang) -> str:
    """Wallet count with the right plural form.

    English: "1 wallet" / "5 wallets". Arabic follows the number rules:
    1 محفظة, 2 محفظتان, 3-10 محافظ (plural), 11+ محفظة (singular again).
    """
    if lang == "en":
        return f"{n} wallet" if n == 1 else f"{n} wallets"
    if n == 2:
        return "2 محفظتان"
    if 3 <= n <= 10:
        return f"{n} محافظ"
    return f"{n} محفظة"


def fmt_score(x: float | None) -> str:
    """Signed score with two decimals, e.g. "+0.42"; None -> "n/a"."""
    return "n/a" if x is None else f"{x:+.2f}"


def label(key: str | None, lang: Lang) -> str:
    """Translate a label (smart-money label, crowd bucket, strength, confidence)."""
    if key is None:
        return ""
    return LABELS[lang].get(key, key)


def kind_text(kind: str, lang: Lang) -> tuple[str, str, str]:
    """(short name, headline, explanation) for a verdict kind."""
    return KIND_TEXT[lang][kind]


def t(key: str, lang: Lang, **kw: object) -> str:
    """Look up ``key`` in ``lang`` and format it with ``kw``.

    Float parameters named ``s`` are shown as absolute two-decimal values.
    Unknown keys fall back to English, then to the key itself.
    """
    template = STRINGS[lang].get(key) or STRINGS["en"].get(key) or key
    if "s" in kw and isinstance(kw["s"], float):
        kw["s"] = f"{abs(kw['s']):.2f}"
    try:
        return template.format(**kw)
    except (KeyError, IndexError):
        return template
