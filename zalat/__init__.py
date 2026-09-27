"""Zalat Smart Money Verdict.

A small CLI that contrasts what Nansen "smart money" wallets are doing with a
token against the crowd's mood (the alternative.me Fear & Greed Index) and
prints a bilingual (English / Arabic) verdict. Its main job is to highlight
*disagreement*: smart money buying into fear, or selling into greed.
"""

__version__ = "0.1.0"

#: Appended to every output, in both languages.
DISCLAIMER_EN = "Not financial advice. For research and education only."
DISCLAIMER_AR = "ليست نصيحة مالية. للبحث والتعليم فقط."
