"""Defensive parsing of Nansen output (REST JSON and MCP text).

Two kinds of input:

* **REST** (default backend): plain JSON, with shapes captured live in
  ``tests/fixtures/real_*.json``. Dedicated extractors handle them:
  :func:`extract_cohort_flow` (flat ``smart_trader_*`` keys),
  :func:`extract_buy_sell` (BUY/SELL union by wallet), :func:`extract_ohlcv_change`
  and :func:`extract_token_market`.
* **MCP** text. ``general_search`` returns JSON ``{"result": "<markdown>"}`` with a
  pipe table, and the data tools' shapes are not documented.

So the generic helpers are deliberately forgiving:

* the payload may be JSON, JSON-inside-a-string, or plain markdown;
* rows may come from a JSON list of objects or from any markdown pipe table;
* column names are matched fuzzily (``netFlowUsd`` == ``Net Flow (USD)``);
* numbers may be human formatted (``1.2M``, ``-$3.4M``, ``(1,234)``, ``4e-06``).

Nothing in this module raises on bad input: it returns ``None`` instead, and
the verdict engine marks that signal as unavailable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

# Keys that commonly wrap the "real" payload.
_WRAPPER_KEYS = ("result", "text", "content")
# Keys that commonly hold the list of rows, in order of preference.
_LIST_KEYS = ("data", "rows", "result", "items", "flows", "results")

_SEPARATOR_CELL = re.compile(r"^:?-+:?$")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_SUFFIX = {"k": 1e3, "m": 1e6, "mn": 1e6, "b": 1e9, "bn": 1e9, "t": 1e12}
_NUM_RE = re.compile(r"^([-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?)(k|mn|m|bn|b|t)?$", re.I)
_NULLS = {"", "-", "--", "—", "–", "n/a", "na", "none", "null", "nan"}


# --------------------------------------------------------------------------- #
# Generic helpers
# --------------------------------------------------------------------------- #
def unwrap_payload(text: Any) -> Any:
    """Decode a tool payload as far as possible.

    JSON is decoded; a dict whose main value is a string under
    ``result``/``text``/``content`` is unwrapped (and that string decoded as
    JSON once more if it is JSON). Non-JSON text is returned unchanged.
    """
    if isinstance(text, (dict, list)):
        data: Any = text
    elif isinstance(text, str):
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return text
    else:
        return text

    if isinstance(data, dict):
        for key in _WRAPPER_KEYS:
            inner = data.get(key)
            if isinstance(inner, str):
                try:
                    return json.loads(inner)
                except (ValueError, TypeError):
                    return inner
            if isinstance(inner, (dict, list)) and len(data) == 1:
                return unwrap_payload(inner)
    return data


def _clean_cell(cell: str) -> str:
    cell = _LINK.sub(r"\1", cell.strip())
    return cell.replace("**", "").replace("`", "").strip()


def _split_row(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [_clean_cell(c) for c in body.split("|")]


def parse_markdown_tables(md: str) -> list[list[dict[str, str]]]:
    """Parse every pipe table in ``md`` into a list of row dicts.

    The first row of a table is its header; ``|:---|---:|`` separator rows
    are skipped; duplicate headers get ``_2``, ``_3`` suffixes; short rows are
    padded with ``""`` and long rows truncated.
    """
    if not isinstance(md, str):
        return []
    tables: list[list[dict[str, str]]] = []
    header: list[str] | None = None
    rows: list[dict[str, str]] = []

    def flush() -> None:
        nonlocal header, rows
        if header is not None:
            tables.append(rows)
        header, rows = None, []

    for line in md.splitlines():
        if not line.strip().startswith("|"):
            flush()
            continue
        cells = _split_row(line)
        if (header is not None and not rows and any(cells)
                and all(_SEPARATOR_CELL.match(c.replace(" ", "")) for c in cells if c)):
            continue  # the |:----|----:| row right under the header
        if header is None:
            seen: dict[str, int] = {}
            header = []
            for c in cells:
                name = c or "col"
                seen[name] = seen.get(name, 0) + 1
                header.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
            continue
        cells = (cells + [""] * len(header))[: len(header)]
        rows.append(dict(zip(header, cells)))
    flush()
    return tables


def records_from(payload: Any) -> list[dict[str, Any]]:
    """Turn any decoded payload into a flat list of row dicts."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in _LIST_KEYS:
            val = payload.get(key)
            if isinstance(val, list) and any(isinstance(r, dict) for r in val):
                return [r for r in val if isinstance(r, dict)]
            if isinstance(val, dict):
                inner = records_from(val)
                if inner:
                    return inner
        for val in payload.values():
            if isinstance(val, list) and any(isinstance(r, dict) for r in val):
                return [r for r in val if isinstance(r, dict)]
        # A single flat record (all scalar values).
        if payload and all(not isinstance(v, (dict, list)) for v in payload.values()):
            return [payload]
        return []
    if isinstance(payload, str):
        return [row for table in parse_markdown_tables(payload) for row in table]
    return []


def parse_number(s: Any) -> float | None:
    """Parse a human-formatted number; return ``None`` if it is not one.

    Handles ``$``, commas, ``USD``, ``+``, unicode minus, accounting
    parentheses (``(1,234)`` -> -1234), trailing ``%`` and k/m/b/t suffixes.
    """
    if s is None or isinstance(s, bool):
        return None
    if isinstance(s, (int, float)):
        return float(s)
    if not isinstance(s, str):
        return None
    t = s.strip().replace("−", "-").replace(" ", " ")
    if t.lower() in _NULLS:
        return None
    negative = False
    if t.startswith("(") and t.endswith(")"):
        negative, t = True, t[1:-1]
    t = re.sub(r"(?i)usd", "", t)
    t = t.replace("$", "").replace(",", "").replace(" ", "").rstrip("%")
    if t.startswith("+"):
        t = t[1:]
    # "-$3.4M" becomes "-3.4M"; "$-12.5K" becomes "-12.5K" — both fine now.
    m = _NUM_RE.match(t)
    if not m:
        return None
    try:
        value = float(m.group(1))
    except ValueError:  # pragma: no cover - regex guarantees a float
        return None
    if m.group(2):
        value *= _SUFFIX[m.group(2).lower()]
    return -value if negative else value


def norm(s: str) -> str:
    """Normalise a column name: split camelCase, lowercase, non-alnum -> space."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(s))
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return s.strip()


def find_col(
    cols: Iterable[str], include: list[list[str]], exclude: Iterable[str] = ()
) -> str | None:
    """Find the first column matching ``include``.

    ``include`` is an OR of AND-groups of word fragments: ``[["net", "flow"],
    ["netflow"]]`` matches "Net Flow (USD)" and "netflow". Groups are tried in
    order, so put the most specific first. Columns whose normalised name
    contains any ``exclude`` fragment are skipped.
    """
    cols = list(cols)
    normed = [(c, norm(c)) for c in cols]
    excl = [e.lower() for e in exclude]
    for group in include:
        for original, n in normed:
            if any(e in n for e in excl):
                continue
            if all(frag in n for frag in group):
                return original
    return None


# --------------------------------------------------------------------------- #
# Smart-money flow extraction (token_recent_flows_summary)
# --------------------------------------------------------------------------- #
@dataclass
class SmFlow:
    """Smart-money flow numbers pulled from the flows summary."""

    net_usd: float | None
    inflow_usd: float | None
    outflow_usd: float | None
    wallets: int | None
    source_row: dict = field(default_factory=dict)
    #: Average absolute flow per wallet (Nansen REST flow-intelligence). With
    #: ``wallets`` it gives an ESTIMATED gross flow when in/out are unknown.
    avg_usd: float | None = None

    @property
    def estimated_gross_usd(self) -> float | None:
        """avg flow per wallet x wallet count (only when both are > 0)."""
        if self.avg_usd and self.wallets and self.avg_usd > 0 and self.wallets > 0:
            return self.avg_usd * self.wallets
        return None


_COHORT_INCLUDE = [["segment"], ["cohort"], ["label"], ["category"], ["group"], ["type"],
                   ["holder"], ["name"]]


def _is_sm_text(v: Any) -> bool:
    t = str(v).lower().replace("_", " ").replace("-", " ")
    return "smart money" in t or ("smart" in t and "trader" in t)


def _find_sm_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the Smart Money row: exact cohort match first, then fuzzy."""
    if not rows:
        return None
    cohort_col = find_col(rows[0].keys(), _COHORT_INCLUDE, exclude=["usd", "flow", "volume"])
    if cohort_col:
        for r in rows:
            if norm(str(r.get(cohort_col, ""))) == "smart money":
                return r
        for r in rows:
            if _is_sm_text(r.get(cohort_col, "")):
                return r
    # No cohort column (or no hit there): scan every string cell.
    for r in rows:
        if any(isinstance(v, str) and _is_sm_text(v) for v in r.values()):
            return r
    return None


def _flow_from_dict(d: dict[str, Any]) -> SmFlow | None:
    """Extract flow numbers from one row / object."""
    cols = list(d.keys())
    net_c = find_col(cols, [["net", "flow"], ["net", "usd"], ["netflow"], ["net"]],
                     exclude=["count", "wallet", "pct", "percent", "change", "network"])
    in_c = find_col(cols, [["inflow"], ["in", "flow"], ["buy", "volume"], ["bought"]],
                    exclude=["count", "wallet", "net", "pct", "percent"])
    out_c = find_col(cols, [["outflow"], ["out", "flow"], ["sell", "volume"], ["sold"]],
                     exclude=["count", "wallet", "net", "pct", "percent"])
    w_c = find_col(cols, [["wallet"], ["holders"], ["traders"], ["count"]])

    net = parse_number(d.get(net_c)) if net_c else None
    inflow = parse_number(d.get(in_c)) if in_c else None
    outflow = parse_number(d.get(out_c)) if out_c else None
    if outflow is not None:
        outflow = abs(outflow)  # some APIs report outflows as negatives
    if net is None and inflow is not None and outflow is not None:
        net = inflow - outflow
    wallets_f = parse_number(d.get(w_c)) if w_c else None
    if net is None and inflow is None and outflow is None:
        return None
    return SmFlow(net, inflow, outflow, int(wallets_f) if wallets_f is not None else None, dict(d))


def _sm_subobject(payload: Any) -> dict | None:
    """Find a nested object keyed like ``smart_money`` / ``smartMoney``."""
    if isinstance(payload, dict):
        for k, v in payload.items():
            if isinstance(v, dict) and norm(k) == "smart money":
                return v
        for v in payload.values():
            found = _sm_subobject(v)
            if found is not None:
                return found
    return None


def _cohort_rows(payload: Any) -> list[dict[str, Any]]:
    """Rows of a REST flow-intelligence payload: ``{"data": [{...}]}`` or a dict."""
    if isinstance(payload, dict):
        data = payload.get("data", payload)
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    return []


def extract_cohort_flow(text: str, prefix: str) -> SmFlow | None:
    """Flow of one cohort from Nansen REST ``tgm/flow-intelligence``.

    That endpoint returns flat keys per cohort, e.g. ``smart_trader_net_flow_usd``,
    ``smart_trader_avg_flow_usd``, ``smart_trader_wallet_count`` (no inflow /
    outflow split). ``prefix`` is the cohort, e.g. "smart_trader" or "top_pnl".
    """
    for row in _cohort_rows(unwrap_payload(text)):
        net = parse_number(row.get(f"{prefix}_net_flow_usd"))
        if net is None:
            continue
        avg = parse_number(row.get(f"{prefix}_avg_flow_usd"))
        w = parse_number(row.get(f"{prefix}_wallet_count"))
        return SmFlow(net, None, None, int(w) if w is not None else None,
                      {k: v for k, v in row.items() if k.startswith(prefix)}, avg)
    return None


def extract_top_pnl_flow(text: str) -> SmFlow | None:
    """Top-PnL traders' net flow (REST): shown as secondary context only."""
    return extract_cohort_flow(text, "top_pnl")


def extract_sm_flow(text: str) -> SmFlow | None:
    """Extract the Smart Money cohort's flow from a flows-summary payload.

    Handles the REST shape (``smart_trader_*`` keys) first, then the MCP /
    markdown / JSON cohort-table shapes.
    """
    rest = extract_cohort_flow(text, "smart_trader")
    if rest is not None:
        return rest
    payload = unwrap_payload(text)
    row = _find_sm_row(records_from(payload))
    if row is not None:
        flow = _flow_from_dict(row)
        if flow is not None:
            return flow
    sub = _sm_subobject(payload)
    if sub is not None:
        return _flow_from_dict(sub)
    # Markdown text with the SM table below other tables: try every table.
    if isinstance(payload, str):
        for table in parse_markdown_tables(payload):
            row = _find_sm_row(table)
            if row is not None and (flow := _flow_from_dict(row)) is not None:
                return flow
    return None


# --------------------------------------------------------------------------- #
# Price context (token_info)
# --------------------------------------------------------------------------- #
_PRICE_INCLUDE = [["price", "usd"], ["current", "price"], ["price"]]
_PRICE_EXCLUDE = ["change", "pct", "percent", "volume", "high", "low", "ath", "atl", "open", "close"]
_CHANGE_EXCLUDE = ["volume", "holder", "liquidity", "market cap", "mcap", "flow"]
# Words that make a column a price-change column.
_CHANGE_WORDS = ("change", "chg")
# Windows we want (24h / 1d) and windows we must NOT use (1h, 7d...).
_WANTED_WINDOW = re.compile(r"\b(24 ?h|1 ?d|24 ?hours?|day|daily)\b")
_OTHER_WINDOW = re.compile(r"\b(\d+ ?(m|min|h|d|w|y)|\d+ ?(hours?|days?|weeks?)|week|month|year|ytd)\b")


def _norm_window(n: str) -> str:
    """"price change24h" -> "price change 24h" so window tokens are separate words."""
    return re.sub(r"([a-z])(\d)", r"\1 \2", n)


def pick_change_col(cols: Iterable[str]) -> str | None:
    """Choose the 24h price-change column.

    Prefer a column that names a 24h / 1d window. Columns naming any other
    window (1h, 5m, 6h, 12h, 7d, 30d...) are never used. As a fallback, accept
    a change column with no window at all (e.g. "Price Change").
    """
    windowless: str | None = None
    for col in cols:
        n = _norm_window(norm(col))
        if not any(w in n for w in _CHANGE_WORDS) or any(e in n for e in _CHANGE_EXCLUDE):
            continue
        if _WANTED_WINDOW.search(n):
            return col
        if _OTHER_WINDOW.search(n):
            continue
        if windowless is None:
            windowless = col
    return windowless


def _price_from_dict(d: dict[str, Any]) -> tuple[float | None, float | None]:
    cols = [k for k, v in d.items() if not isinstance(v, (dict, list))]
    price_c = find_col(cols, _PRICE_INCLUDE, exclude=_PRICE_EXCLUDE)
    change_c = pick_change_col(cols)
    price = parse_number(d.get(price_c)) if price_c else None
    change = parse_number(d.get(change_c)) if change_c else None
    return (price if price is not None and price > 0 else None), change


def _metric_value_table(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Turn a two-column "| Metric | Value |" table into one flat dict."""
    if not rows or len(rows[0]) != 2:
        return None
    k_col, v_col = list(rows[0].keys())
    return {str(r.get(k_col, "")): r.get(v_col) for r in rows}


def extract_price_info(text: str) -> tuple[float | None, float | None]:
    """Return ``(price_usd, change_pct)`` from a ``token_info`` payload.

    Accepts a JSON object (possibly nested under ``data``), a list of rows,
    a normal markdown table or a two-column "Metric | Value" table. Never
    raises; anything unreadable gives ``(None, None)``.
    """
    try:
        payload = unwrap_payload(text)
        candidates: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            candidates.append(payload)
            for v in payload.values():
                if isinstance(v, dict):
                    candidates.append(v)
        rows = records_from(payload)
        candidates.extend(rows[:1])
        if isinstance(payload, str):
            for table in parse_markdown_tables(payload):
                kv = _metric_value_table(table)
                if kv:
                    candidates.append(kv)
        price = change = None
        for c in candidates:
            p, ch = _price_from_dict(c)
            price = price if price is not None else p
            change = change if change is not None else ch
        return price, change
    except Exception:  # noqa: BLE001 - context data must never break a verdict
        return None, None


# --------------------------------------------------------------------------- #
# Buy / sell side volume (token_who_bought_sold)
# --------------------------------------------------------------------------- #
@dataclass
class BuySellSide:
    """Total USD volume and wallet count for one side (BUY or SELL)."""

    volume_usd: float | None
    wallets: int


_NO_RESULTS = re.compile(r"\bno (results|data|trades|transactions)\b|\b0 results\b|total results\**:?\**\s*0\b", re.I)


_SIDE_WORDS = {"BUY": ("buy", "bought"), "SELL": ("sell", "sold")}
_VOL_EXCLUDE = ("price", "count", "pct", "percent", "balance", "pnl", "holding")


def _is_usd_col(n: str) -> bool:
    """True if a normalised column name is explicitly denominated in USD.

    Only ``usd`` or ``value`` count as a USD marker. Plain "volume" /
    "amount" columns are often in native token units (Nansen may disable
    USD fields), and adding those up as dollars would be badly wrong.
    """
    words = n.split()
    return "usd" in n or "value" in words


def pick_side_volume_col(cols: Iterable[str], side: str | None = None) -> str | None:
    """Choose the USD volume column for ``side`` ("BUY"/"SELL"/None).

    Columns naming the opposite side (e.g. ``sold_volume_usd`` when asking
    for BUY) are excluded. Among the rest, prefer ones naming this side,
    then ones mentioning volume/trade, then any other USD column.
    """
    side = side.upper() if side else None
    mine = _SIDE_WORDS.get(side, ()) if side else ()
    other = _SIDE_WORDS["SELL" if side == "BUY" else "BUY"] if side in _SIDE_WORDS else ()
    best: tuple[int, int, str] | None = None
    for i, col in enumerate(cols):
        n = norm(col)
        if not _is_usd_col(n) or any(x in n for x in _VOL_EXCLUDE):
            continue
        if any(w in n for w in other):
            continue
        rank = 0 if any(w in n for w in mine) else 1 if ("volume" in n or "trade" in n) else 2
        if best is None or (rank, i) < best[:2]:
            best = (rank, i, col)
    return best[2] if best else None


def extract_side_volume(text: str, side: str | None = None) -> BuySellSide | None:
    """Sum the USD volume of all labelled wallets on one side ("BUY"/"SELL").

    Returns ``BuySellSide(0, 0)`` when the tool clearly says there were no
    results, and ``None`` when the payload cannot be understood or has no
    USD-denominated volume column (the signal is then "unavailable").
    """
    payload = unwrap_payload(text)
    rows = records_from(payload)
    if not rows:
        blob = payload if isinstance(payload, str) else json.dumps(payload, default=str)
        # An empty list (or {"data": []}) is a clear "nobody traded".
        if isinstance(payload, list) and not payload:
            return BuySellSide(0.0, 0)
        if isinstance(payload, dict) and any(
                isinstance(payload.get(k), list) and not payload[k] for k in _LIST_KEYS):
            return BuySellSide(0.0, 0)
        return BuySellSide(0.0, 0) if _NO_RESULTS.search(blob or "") else None

    cols: list[str] = []
    for r in rows:  # union of keys, preserving order
        cols.extend(k for k in r.keys() if k not in cols)
    vol_c = pick_side_volume_col(cols, side)
    if vol_c is None:
        return None
    total, wallets = 0.0, 0
    for r in rows:
        v = parse_number(r.get(vol_c))
        if v is not None:
            total += abs(v)
            wallets += 1
    if wallets == 0:
        return None
    return BuySellSide(total, wallets)


def extract_buy_sell(buy_text: str | None, sell_text: str | None
                     ) -> tuple[BuySellSide | None, BuySellSide | None]:
    """Buy and sell USD volume of smart wallets from the BUY and SELL lists.

    Nansen REST rows carry BOTH ``bought_volume_usd`` and ``sold_volume_usd``,
    and the BUY and SELL lists overlap. So we take the union of both lists by
    wallet address and sum each column once per wallet (token-unit volumes
    are ignored). ``wallets`` = number of unique addresses on both sides.

    For payloads without those columns (MCP / markdown) each side is parsed on
    its own with :func:`extract_side_volume`. Both texts are required.
    """
    if buy_text is None or sell_text is None:
        return None, None
    rows = [r for t in (buy_text, sell_text) for r in records_from(unwrap_payload(t))]
    rest_shape = bool(rows) and all(
        isinstance(r.get("address"), str) and r["address"]
        and "bought_volume_usd" in r and "sold_volume_usd" in r
        for r in rows
    )
    if rest_shape:
        union: dict[str, dict[str, Any]] = {}
        for r in rows:
            union.setdefault(r["address"].lower(), r)  # same wallet in both lists: count once
        bought = sum(abs(parse_number(r.get("bought_volume_usd")) or 0.0) for r in union.values())
        sold = sum(abs(parse_number(r.get("sold_volume_usd")) or 0.0) for r in union.values())
        return BuySellSide(bought, len(union)), BuySellSide(sold, len(union))
    return extract_side_volume(buy_text, "BUY"), extract_side_volume(sell_text, "SELL")


# --------------------------------------------------------------------------- #
# Price change from OHLCV candles, and market context (REST)
# --------------------------------------------------------------------------- #
def extract_ohlcv_change(text: str) -> tuple[float | None, float | None]:
    """``(last_close, change_pct)`` from daily candles (``tgm/token-ohlcv``).

    Change = last close vs the previous candle's close, in percent. The last
    daily candle is usually the current (partial) day. Never raises.
    """
    try:
        rows = records_from(unwrap_payload(text))
        candles = []
        for r in rows:
            close = parse_number(r.get("close"))
            if close is not None and close > 0:
                candles.append((str(r.get("interval_start", "")), close))
        if not candles:
            return None, None
        candles.sort(key=lambda c: c[0])  # ISO timestamps sort chronologically
        last = candles[-1][1]
        if len(candles) < 2:
            return last, None
        prev = candles[-2][1]
        return last, (last / prev - 1.0) * 100.0
    except Exception:  # noqa: BLE001 - context data must never break a verdict
        return None, None


def extract_token_market(text: str) -> dict[str, float] | None:
    """Market context from ``tgm/token-information``: market cap, liquidity, holders."""
    try:
        payload = unwrap_payload(text)
        data = payload.get("data", payload) if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return None
        details = data.get("token_details") if isinstance(data.get("token_details"), dict) else {}
        spot = data.get("spot_metrics") if isinstance(data.get("spot_metrics"), dict) else {}
        out = {
            "market_cap_usd": parse_number(details.get("market_cap_usd")),
            "liquidity_usd": parse_number(spot.get("liquidity_usd")),
            "holders": parse_number(spot.get("total_holders")),
        }
        out = {k: v for k, v in out.items() if v is not None}
        return out or None
    except Exception:  # noqa: BLE001
        return None
