"""English and Arabic strings.

All user-facing text lives here, keyed by a short id. ``t(key, lang, **kw)``
looks up and formats a string. Numbers are always formatted with Western
digits by :func:`fmt_usd` / :func:`fmt_score` / :func:`fmt_price` so they read
the same (and stay left-to-right) inside Arabic text.

Honesty rule: the Fear & Greed Index describes the WHOLE crypto market. Every
line that shows its value also says it is not specific to the token, and
headlines based on it say "market-wide mood, not this token".
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from zalat import DISCLAIMER_AR, DISCLAIMER_EN

Lang = Literal["en", "ar"]
SOURCES = ("token_social", "market_mood")

# KIND_TEXT[lang][crowd_source][kind] -> (short name, headline, explanation).
# INSUFFICIENT_DATA and SM_ONLY do not depend on the crowd source.
_SHARED = {
    "en": {
        "INSUFFICIENT_DATA": ("Insufficient Data", "Not enough smart-money data for a verdict",
                              "Nansen data was unavailable or could not be read. "
                              "The other signals are still shown below."),
        "SM_ONLY": ("Smart Money Only", "Smart-money reading only (no crowd signal available)",
                    "Neither token social sentiment nor the market-wide Fear & Greed mood "
                    "could be fetched, so no contrast is possible."),
    },
    "ar": {
        "INSUFFICIENT_DATA": ("بيانات غير كافية", "لا توجد بيانات كافية عن الأموال الذكية لإصدار حكم",
                              "بيانات Nansen غير متاحة أو تعذّرت قراءتها. "
                              "بقية الإشارات معروضة أدناه."),
        "SM_ONLY": ("الأموال الذكية فقط", "قراءة الأموال الذكية فقط (لا توجد إشارة للجمهور)",
                    "تعذّر جلب المشاعر الاجتماعية الخاصة بالعملة ومزاج السوق العام (الخوف والطمع)، "
                    "لذا لا يمكن إجراء المقارنة."),
    },
}

KIND_TEXT: dict[str, dict[str, dict[str, tuple[str, str, str]]]] = {
    "en": {
        "token_social": {
            "CONTRARIAN_BULLISH": ("Contrarian Bullish",
                                   "Smart money is buying while this token's social crowd is bearish",
                                   "Social sentiment about this token is negative while smart-money "
                                   "wallets accumulate it. This is the kind of disagreement worth a "
                                   "closer look."),
            "WARNING_BEARISH": ("Warning (Bearish)",
                                "Smart money is selling while this token's social crowd is bullish",
                                "Social sentiment about this token is positive while smart-money "
                                "wallets distribute it. Smart money may be selling to late buyers."),
            "CONFIRMED_BULLISH": ("Confirmed Bullish",
                                  "Smart money and this token's social crowd are both bullish",
                                  "Both sides agree. Agreement is less informative than disagreement."),
            "CONFIRMED_BEARISH": ("Confirmed Bearish",
                                  "Smart money and this token's social crowd are both bearish",
                                  "Both sides agree on the downside."),
            "NEUTRAL": ("Neutral", "No clear divergence between smart money and this token's social crowd",
                        "Either smart money or the token's social crowd has no strong direction."),
            **_SHARED["en"],
        },
        "market_mood": {
            "CONTRARIAN_BULLISH": ("Contrarian Bullish",
                                   "Smart money is buying while the overall crypto market is fearful "
                                   "(market-wide mood, not this token)",
                                   "The whole crypto market is fearful while smart-money wallets "
                                   "accumulate this token. Worth a closer look, but the mood describes "
                                   "the market, not this token's own crowd."),
            "WARNING_BEARISH": ("Warning (Bearish)",
                                "Smart money is selling while the overall crypto market is greedy "
                                "(market-wide mood, not this token)",
                                "The whole crypto market is greedy while smart-money wallets "
                                "distribute this token. The mood describes the market, not this "
                                "token's own crowd."),
            "CONFIRMED_BULLISH": ("Confirmed Bullish",
                                  "Smart money is buying and the overall crypto market is greedy "
                                  "(market-wide mood, not this token)",
                                  "Both point up. Agreement is less informative than disagreement."),
            "CONFIRMED_BEARISH": ("Confirmed Bearish",
                                  "Smart money is selling and the overall crypto market is fearful "
                                  "(market-wide mood, not this token)",
                                  "Both point down."),
            "NEUTRAL": ("Neutral",
                        "No clear divergence between smart money and the overall market mood",
                        "Either smart money or the market-wide mood has no strong direction."),
            **_SHARED["en"],
        },
    },
    "ar": {
        "token_social": {
            "CONTRARIAN_BULLISH": ("صعود عكس الجمهور",
                                   "الأموال الذكية تشتري بينما جمهور العملة على وسائل التواصل متشائم",
                                   "المشاعر الاجتماعية تجاه هذه العملة سلبية بينما محافظ الأموال "
                                   "الذكية تُجمِّعها. هذا النوع من التباين يستحق نظرة أعمق."),
            "WARNING_BEARISH": ("تحذير (هبوطي)",
                                "الأموال الذكية تبيع بينما جمهور العملة على وسائل التواصل متفائل",
                                "المشاعر الاجتماعية تجاه هذه العملة إيجابية بينما محافظ الأموال "
                                "الذكية تُصرِّفها. قد تكون الأموال الذكية تبيع للمشترين المتأخرين."),
            "CONFIRMED_BULLISH": ("صعود مؤكَّد",
                                  "الأموال الذكية وجمهور العملة على وسائل التواصل متفائلون معاً",
                                  "الطرفان متفقان. الاتفاق أقل دلالة من الاختلاف."),
            "CONFIRMED_BEARISH": ("هبوط مؤكَّد",
                                  "الأموال الذكية وجمهور العملة على وسائل التواصل متشائمون معاً",
                                  "الطرفان متفقان على الهبوط."),
            "NEUTRAL": ("محايد", "لا يوجد تباين واضح بين الأموال الذكية وجمهور العملة على وسائل التواصل",
                        "لا يوجد اتجاه قوي لدى الأموال الذكية أو لدى جمهور العملة."),
            **_SHARED["ar"],
        },
        "market_mood": {
            "CONTRARIAN_BULLISH": ("صعود عكس مزاج السوق",
                                   "الأموال الذكية تشتري بينما يسود الخوف سوق الكريبتو بأكمله "
                                   "(مزاج السوق العام، وليس هذه العملة)",
                                   "سوق الكريبتو بأكمله خائف بينما محافظ الأموال الذكية تُجمِّع هذه "
                                   "العملة. يستحق نظرة أعمق، لكن المزاج يصف السوق وليس جمهور هذه العملة."),
            "WARNING_BEARISH": ("تحذير: بيع وسط طمع السوق",
                                "الأموال الذكية تبيع بينما يسيطر الطمع على سوق الكريبتو بأكمله "
                                "(مزاج السوق العام، وليس هذه العملة)",
                                "يسيطر الطمع على سوق الكريبتو بأكمله بينما محافظ الأموال الذكية "
                                "تُصرِّف هذه العملة. المزاج يصف السوق وليس جمهور هذه العملة."),
            "CONFIRMED_BULLISH": ("صعود مؤكَّد",
                                  "الأموال الذكية تشتري ويسيطر الطمع على سوق الكريبتو بأكمله "
                                  "(مزاج السوق العام، وليس هذه العملة)",
                                  "الاتجاهان صاعدان. الاتفاق أقل دلالة من الاختلاف."),
            "CONFIRMED_BEARISH": ("هبوط مؤكَّد",
                                  "الأموال الذكية تبيع ويسود الخوف سوق الكريبتو بأكمله "
                                  "(مزاج السوق العام، وليس هذه العملة)",
                                  "الاتجاهان هابطان."),
            "NEUTRAL": ("محايد", "لا يوجد تباين واضح بين الأموال الذكية ومزاج السوق العام",
                        "لا يوجد اتجاه قوي لدى الأموال الذكية أو في مزاج السوق العام."),
            **_SHARED["ar"],
        },
    },
}

LABELS: dict[str, dict[str, str]] = {
    "en": {
        "Accumulating": "Accumulating", "Distributing": "Distributing", "Neutral": "Neutral",
        "Unavailable": "Unavailable", "Extreme Fear": "Extreme Fear", "Fear": "Fear",
        "Greed": "Greed", "Extreme Greed": "Extreme Greed",
        "Very Bearish": "Very Bearish", "Bearish": "Bearish", "Mixed": "Mixed",
        "Bullish": "Bullish", "Very Bullish": "Very Bullish",
        "Rising": "Rising", "Falling": "Falling", "Flat": "Flat",
        "strong": "strong", "moderate": "moderate", "weak": "weak",
        "High": "High", "Medium": "Medium", "Low": "Low",
    },
    "ar": {
        "Accumulating": "تجميع", "Distributing": "تصريف", "Neutral": "محايد",
        "Unavailable": "غير متاح", "Extreme Fear": "خوف شديد", "Fear": "خوف",
        "Greed": "طمع", "Extreme Greed": "طمع شديد",
        "Very Bearish": "هبوطي جداً", "Bearish": "هبوطي", "Mixed": "متباين",
        "Bullish": "صعودي", "Very Bullish": "صعودي جداً",
        "Rising": "صاعد", "Falling": "هابط", "Flat": "مستقر",
        "strong": "قوي", "moderate": "متوسط", "weak": "ضعيف",
        "High": "مرتفعة", "Medium": "متوسطة", "Low": "منخفضة",
    },
}

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "title": "Zalat Smart Money Verdict",
        "token_line": "Token: {token} on {chain}, lookback {period}",
        "banner": ">>> DISAGREEMENT: SMART MONEY vs {crowd_name} <<<",
        "crowd_name_social": "token's social crowd",
        "crowd_name_market": "overall market mood",
        "address": "Address: {address}",
        "verdict": "VERDICT: {headline}  [{kind}]",
        "disagree_yes": "Disagreement: YES - smart money and the {crowd_name} point in opposite directions.",
        "disagree_no": "Disagreement: no",
        "sm_line": "Smart money: {label}{strength}, score {score}",
        "sm_unavailable": "Smart money: Unavailable",
        "flow_line": "  - Net flow: {net} (in {inflow} / out {outflow}{wallets})",
        "flow_na": "  - Net flow: unavailable",
        "flow_line_est": "  - Net flow: {net} ({wallets}, avg {avg} per wallet, estimated gross {gross})",
        "flow_line_net": "  - Net flow: {net}{wallets}",
        "wallets_paren": " ({wallets})",
        "top_pnl_line": "  - Top PnL traders net flow (context, not scored): {net}{wallets}",
        "market_ctx_line": "Market context: market cap {mcap}, liquidity {liq}, holders {holders}",
        "wallets_part": ", {wallets}",
        "bs_line": "  - Smart buyers vs sellers: {buy} bought / {sell} sold (score {score})",
        "bs_na": "  - Smart buyers vs sellers: unavailable",
        "price_line": "Price: {price} ({change} over {window}, source {source})",
        "price_line_no_change": "Price: {price} (24h change unavailable)",
        "source_nansen_token_info": "Nansen token_info",
        "source_lunarcrush": "LunarCrush",
        "source_nansen_ohlcv": "Nansen OHLCV",
        "social_line": "Token social sentiment ({symbol}, LunarCrush): {label} - {sentiment}% positive, Galaxy Score {galaxy}",
        "market_line": "Market-wide mood (whole crypto market, BTC-centric; NOT specific to {token}): {label} ({value}/100) - alternative.me Fear & Greed",
        "market_na": "Market-wide mood (whole crypto market): unavailable - Fear & Greed could not be fetched",
        "secondary_market": "Secondary context -",
        "divergence": "Divergence score: {d} (positive = smart money leans against the {crowd_name})",
        "confidence": "Confidence: {level}",
        "why": "Why:",
        # confidence reasons
        "flow_unavailable": "smart-money flow data unavailable",
        "bs_unavailable": "smart buyer/seller data unavailable",
        "no_sm_trades": "no smart-money buys or sells in this period",
        "crowd_unavailable": "no crowd signal: token social and market-wide mood both unavailable",
        "one_sm_part": "only one of the two smart-money signals was available",
        "weak_signal": "smart-money signal is weak (strength {s}, below 0.40)",
        "parts_disagree": "net flow and buyer/seller balance point in different directions",
        "low_wallets": "few smart-money wallets involved (only {wallets})",
        "small_volume": "small smart-money volume (under the minimum size, signal scaled down)",
        "crowd_neutral": "market-wide mood is near neutral (45-55)",
        "social_neutral": "token social sentiment is mixed (41-60% positive)",
        "crowd_market_wide": "only the market-wide mood was available, not this token's own crowd (capped at Medium)",
        "price_volatile": "price moved 20% or more in 24h (volatile)",
        # notes
        "crowded_trade": "Note: extreme optimism about this token - this may be a crowded trade.",
        "crowded_trade_market": "Note: the whole crypto market is in Extreme Greed (market-wide) - trades may be crowded.",
        "window_24h": "24h",
        "capitulation": "Note: both sides bearish - can indicate capitulation.",
        "lean_positive": "Mild lean: smart money slightly positive.",
        "lean_negative": "Mild lean: smart money slightly negative.",
        "sm_only": "Note: verdict is based on smart money alone.",
        "accumulation_on_dip": "Price context: price falling while smart money buys (accumulation on a dip).",
        "buying_momentum": "Price context: price rising while smart money buys (buying into momentum).",
        "distribution_into_strength": "Price context: price rising while smart money sells (distribution into strength).",
        "exiting_weakness": "Price context: price falling while smart money sells (exiting weakness).",
        "token_vs_market": "Note: this token's crowd diverges from the overall market mood.",
        "market_unavailable": "Note: market-wide mood (Fear & Greed) could not be fetched.",
        "fallback_clause": "; this verdict compares smart money with market-wide mood instead.",
        "social_status_not_configured": "Token social sentiment: not configured - needs a paid LunarCrush API plan (set LUNARCRUSH_API_KEY). Future work{fallback}",
        "social_status_not_authorized": "Token social sentiment: unavailable - key rejected or plan lacks social data (HTTP {code}){fallback}",
        "social_status_rate_limited": "Token social sentiment: unavailable - LunarCrush rate limit reached{fallback}",
        "social_status_no_sentiment": "Token social sentiment: unavailable - LunarCrush returned no sentiment for this token (a paid plan may be needed){fallback}",
        "social_status_no_symbol": "Token social sentiment: skipped - no token symbol (pass a symbol with --address){fallback}",
        "social_status_mismatch": "Token social sentiment: ignored - LunarCrush price does not match this token (probably a different coin with the same symbol){fallback}",
        "social_status_error": "Token social sentiment: unavailable - LunarCrush request failed{fallback}",
    },
    "ar": {
        "title": "حكم زلط للأموال الذكية",
        "token_line": "العملة: {token} على شبكة {chain}، الفترة {period}",
        "banner": ">>> تباين: الأموال الذكية عكس {crowd_name} <<<",
        "crowd_name_social": "جمهور العملة على وسائل التواصل",
        "crowd_name_market": "مزاج السوق العام",
        "address": "العنوان: {address}",
        "verdict": "الحكم: {headline}  [{kind}]",
        "disagree_yes": "تباين: نعم - الأموال الذكية و{crowd_name} في اتجاهين متعاكسين.",
        "disagree_no": "تباين: لا",
        "sm_line": "الأموال الذكية: {label}{strength}، الدرجة {score}",
        "sm_unavailable": "الأموال الذكية: غير متاح",
        "flow_line": "  - صافي التدفق: {net} (وارد {inflow} / صادر {outflow}{wallets})",
        "flow_na": "  - صافي التدفق: غير متاح",
        "flow_line_est": "  - صافي التدفق: {net} ({wallets}، متوسط {avg} لكل محفظة، إجمالي تقديري {gross})",
        "flow_line_net": "  - صافي التدفق: {net}{wallets}",
        "wallets_paren": " ({wallets})",
        "top_pnl_line": "  - صافي تدفق أعلى المتداولين ربحاً (للسياق، غير محتسب): {net}{wallets}",
        "market_ctx_line": "سياق السوق: القيمة السوقية {mcap}، السيولة {liq}، عدد الحاملين {holders}",
        "wallets_part": "، {wallets}",
        "bs_line": "  - المشترون مقابل البائعين الأذكياء: شراء {buy} / بيع {sell} (الدرجة {score})",
        "bs_na": "  - المشترون مقابل البائعين الأذكياء: غير متاح",
        "price_line": "السعر: {price} ({change} خلال {window}، المصدر {source})",
        "price_line_no_change": "السعر: {price} (تغيّر 24 ساعة غير متاح)",
        "source_nansen_token_info": "Nansen token_info",
        "source_lunarcrush": "LunarCrush",
        "source_nansen_ohlcv": "Nansen OHLCV",
        "social_line": "المشاعر الاجتماعية الخاصة بالعملة ({symbol}، LunarCrush): {label} - {sentiment}% إيجابية، Galaxy Score {galaxy}",
        "market_line": "مزاج السوق العام (سوق الكريبتو بأكمله، يتمحور حول البيتكوين؛ ليس خاصاً بـ {token}): {label} ({value}/100) - مؤشر الخوف والطمع alternative.me",
        "market_na": "مزاج السوق العام (سوق الكريبتو بأكمله): غير متاح - تعذّر جلب مؤشر الخوف والطمع",
        "secondary_market": "سياق ثانوي -",
        "divergence": "درجة التباين: {d} (موجبة = الأموال الذكية عكس {crowd_name})",
        "confidence": "الثقة: {level}",
        "why": "الأسباب:",
        "flow_unavailable": "بيانات تدفق الأموال الذكية غير متاحة",
        "bs_unavailable": "بيانات المشترين/البائعين الأذكياء غير متاحة",
        "no_sm_trades": "لا توجد عمليات شراء أو بيع من الأموال الذكية في هذه الفترة",
        "crowd_unavailable": "لا توجد إشارة للجمهور: المشاعر الاجتماعية للعملة ومزاج السوق العام غير متاحين",
        "one_sm_part": "توفرت إشارة واحدة فقط من إشارتي الأموال الذكية",
        "weak_signal": "إشارة الأموال الذكية ضعيفة (قوتها {s}، أقل من 0.40)",
        "parts_disagree": "صافي التدفق وتوازن الشراء/البيع في اتجاهين مختلفين",
        "low_wallets": "عدد قليل من محافظ الأموال الذكية ({wallets} فقط)",
        "small_volume": "حجم تداول الأموال الذكية صغير (أقل من الحد الأدنى، لذا خُفِّضت الإشارة)",
        "crowd_neutral": "مزاج السوق العام قريب من المحايد (45-55)",
        "social_neutral": "المشاعر الاجتماعية تجاه العملة متباينة (41-60% إيجابية)",
        "crowd_market_wide": "توفر مزاج السوق العام فقط وليس جمهور هذه العملة (الحد الأقصى: متوسطة)",
        "price_volatile": "تحرك السعر 20% أو أكثر خلال 24 ساعة (تقلب مرتفع)",
        "crowded_trade": "ملاحظة: تفاؤل مفرط تجاه هذه العملة - قد تكون صفقة مزدحمة.",
        "crowded_trade_market": "ملاحظة: سوق الكريبتو بأكمله في حالة طمع شديد (مزاج السوق العام) - قد تكون الصفقات مزدحمة.",
        "window_24h": "24 ساعة",
        "capitulation": "ملاحظة: الطرفان متشائمان - قد يدل ذلك على استسلام البائعين.",
        "lean_positive": "ميل طفيف: الأموال الذكية إيجابية قليلاً.",
        "lean_negative": "ميل طفيف: الأموال الذكية سلبية قليلاً.",
        "sm_only": "ملاحظة: الحكم مبني على الأموال الذكية وحدها.",
        "accumulation_on_dip": "سياق السعر: السعر يهبط بينما الأموال الذكية تشتري (تجميع عند الانخفاض).",
        "buying_momentum": "سياق السعر: السعر يصعد بينما الأموال الذكية تشتري (شراء مع الزخم).",
        "distribution_into_strength": "سياق السعر: السعر يصعد بينما الأموال الذكية تبيع (تصريف وقت القوة).",
        "exiting_weakness": "سياق السعر: السعر يهبط بينما الأموال الذكية تبيع (خروج مع الضعف).",
        "token_vs_market": "ملاحظة: جمهور هذه العملة يخالف مزاج السوق العام.",
        "market_unavailable": "ملاحظة: تعذّر جلب مزاج السوق العام (الخوف والطمع).",
        "fallback_clause": "؛ هذا الحكم يقارن الأموال الذكية بمزاج السوق العام بدلاً منها.",
        "social_status_not_configured": "المشاعر الاجتماعية الخاصة بالعملة: غير مُفعَّلة - تتطلب اشتراكاً مدفوعاً في LunarCrush (عيّن LUNARCRUSH_API_KEY). عمل مستقبلي{fallback}",
        "social_status_not_authorized": "المشاعر الاجتماعية الخاصة بالعملة: غير متاحة - المفتاح مرفوض أو الاشتراك لا يشمل البيانات الاجتماعية (HTTP {code}){fallback}",
        "social_status_rate_limited": "المشاعر الاجتماعية الخاصة بالعملة: غير متاحة - تم تجاوز حد الطلبات في LunarCrush{fallback}",
        "social_status_no_sentiment": "المشاعر الاجتماعية الخاصة بالعملة: غير متاحة - لم يُرجع LunarCrush أي بيانات مشاعر لهذه العملة (قد يلزم اشتراك مدفوع){fallback}",
        "social_status_no_symbol": "المشاعر الاجتماعية الخاصة بالعملة: تم تخطيها - لا يوجد رمز للعملة (أضف الرمز مع --address){fallback}",
        "social_status_mismatch": "المشاعر الاجتماعية الخاصة بالعملة: تم تجاهلها - سعر LunarCrush لا يطابق هذه العملة (غالباً عملة أخرى بالرمز نفسه){fallback}",
        "social_status_error": "المشاعر الاجتماعية الخاصة بالعملة: غير متاحة - فشل طلب LunarCrush{fallback}",
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


def fmt_price(x: float | None) -> str:
    """Token price with 4 significant digits, never scientific notation.

    4e-06 -> "$0.000004", 0.000358 -> "$0.000358", 1234.5 -> "$1,235".
    """
    if x is None:
        return "n/a"
    d = Decimal(repr(float(x)))
    if d == 0:
        return "$0"
    sign = "-" if d < 0 else ""
    d = abs(d)
    if d >= 1000:
        return f"{sign}${d.quantize(Decimal(1), ROUND_HALF_UP):,.0f}"
    # Round to 4 significant digits, then print as a plain decimal.
    exp = d.adjusted()  # position of the leading digit
    q = Decimal(1).scaleb(exp - 3)
    rounded = d.quantize(q, ROUND_HALF_UP)
    if rounded >= 1000:  # e.g. 999.95 rounds up to 1000
        return f"{sign}${rounded:,.0f}"
    text = format(rounded, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{sign}${text}"


def fmt_pct(x: float | None) -> str:
    """Signed percent with one decimal: "+3.2%", "-12.0%"; None -> "n/a"."""
    return "n/a" if x is None else f"{x:+.1f}%"


def fmt_score(x: float | None) -> str:
    """Signed score with two decimals, e.g. "+0.42"; None -> "n/a"."""
    return "n/a" if x is None else f"{x:+.2f}"


def label(key: str | None, lang: Lang) -> str:
    """Translate a label (smart-money label, crowd bucket, strength, confidence)."""
    if key is None:
        return ""
    return LABELS[lang].get(key, key)


def kind_text(kind: str, lang: Lang, source: str | None = "market_mood") -> tuple[str, str, str]:
    """(short name, headline, explanation) for a verdict kind and crowd source."""
    return KIND_TEXT[lang][source if source in SOURCES else "market_mood"][kind]


def t(key: str, lang: Lang, **kw: object) -> str:
    """Look up ``key`` in ``lang`` and format it with ``kw``.

    Float parameters named ``s`` are shown as absolute two-decimal values; an
    int ``n`` also provides ``{wallets}`` (pluralised wallet count); a bool
    ``fallback`` becomes the "compared with market-wide mood instead" clause.
    Unknown keys fall back to English, then to the key itself.
    """
    template = STRINGS[lang].get(key) or STRINGS["en"].get(key) or key
    if "s" in kw and isinstance(kw["s"], float):
        kw["s"] = f"{abs(kw['s']):.2f}"
    if isinstance(kw.get("n"), int) and "wallets" not in kw:
        kw["wallets"] = fmt_wallets(kw["n"], lang)  # correct plural in both languages
    if isinstance(kw.get("fallback"), bool):
        # Social-status notes end with "we used the market-wide mood instead"
        # only when that is actually what happened.
        kw["fallback"] = STRINGS[lang]["fallback_clause"] if kw["fallback"] else "."
    try:
        return template.format(**kw)
    except (KeyError, IndexError):
        return template
