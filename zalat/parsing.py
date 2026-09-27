"""Defensive parsing of Nansen MCP tool output.

Nansen's MCP tools return text. ``general_search`` is known to return JSON
``{"result": "<markdown>"}`` where the markdown holds a pipe table, but the
shapes of the data tools (flows, who bought/sold) are not documented, so every
function here is deliberately forgiving:

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


def extract_sm_flow(text: str) -> SmFlow | None:
    """Extract the Smart Money cohort's flow from a flows-summary payload."""
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
# Buy / sell side volume (token_who_bought_sold)
# --------------------------------------------------------------------------- #
@dataclass
class BuySellSide:
    """Total USD volume and wallet count for one side (BUY or SELL)."""

    volume_usd: float | None
    wallets: int


_NO_RESULTS = re.compile(r"\bno (results|data|trades|transactions)\b|\b0 results\b|total results\**:?\**\s*0\b", re.I)


def extract_side_volume(text: str) -> BuySellSide | None:
    """Sum the USD volume of all labelled wallets on one side.

    Returns ``BuySellSide(0, 0)`` when the tool clearly says there were no
    results, and ``None`` when the payload cannot be understood.
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
    # Prefer explicit USD columns over token-amount columns.
    vol_c = find_col(
        cols,
        [["volume", "usd"], ["bought", "usd"], ["sold", "usd"], ["value", "usd"],
         ["trade", "usd"], ["usd"], ["volume"], ["amount"]],
        exclude=["price", "count", "pct", "percent", "balance", "pnl"],
    )
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
