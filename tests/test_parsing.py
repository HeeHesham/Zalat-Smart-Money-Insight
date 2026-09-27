"""Parsing: numbers, markdown tables, payload unwrapping, SM flow and side volume."""

import json

import pytest

from tests.conftest import fixture_text
from zalat.parsing import (
    extract_side_volume,
    extract_sm_flow,
    find_col,
    norm,
    parse_markdown_tables,
    parse_number,
    records_from,
    unwrap_payload,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1.2M", 1.2e6),
        ("101.7k", 101_700.0),
        ("-$3.4M", -3.4e6),
        ("$-12.5K", -12_500.0),
        ("(1,234)", -1234.0),
        ("4e-06", 4e-06),
        ("−5", -5.0),
        ("+$1.2M", 1.2e6),
        ("1,234,567.89", 1234567.89),
        ("12.5%", 12.5),
        ("2.5B", 2.5e9),
        ("3bn", 3e9),
        ("1.5 USD", 1.5),
        ("0.000358", 0.000358),
        (42, 42.0),
        (1.5, 1.5),
        ("", None),
        ("-", None),
        ("n/a", None),
        ("—", None),
        (None, None),
        (True, None),
        ("abc", None),
        ("0x6982508145454ce325ddbe47a25d4ec3d2311933", None),
    ],
)
def test_parse_number(raw, expected):
    got = parse_number(raw)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)


def test_real_general_search_sample_table():
    payload = unwrap_payload(fixture_text("search_pepe.json"))
    assert isinstance(payload, str) and payload.startswith("# Search Results")
    tables = parse_markdown_tables(payload)
    assert len(tables) == 1
    rows = tables[0]
    assert len(rows) == 3
    assert rows[0]["Symbol"] == "PEPE"
    assert rows[0]["Contract Address"] == "0x6982508145454ce325ddbe47a25d4ec3d2311933"
    assert parse_number(rows[0]["Price USD"]) == pytest.approx(4e-06)
    assert parse_number(rows[1]["Volume 24h USD"]) == pytest.approx(101_700)
    # The "Notes" line with a markdown link is not a table row.
    assert all("Notes" not in r["Name"] for r in rows)


def test_table_parser_links_dup_headers_and_padding():
    md = "| A | A | B |\n|---|:-:|--:|\n| [x](http://y) | **2** | `3` |\n| only |\n\ntext\n| C |\n|--|\n| 9 |"
    tables = parse_markdown_tables(md)
    assert tables[0] == [{"A": "x", "A_2": "2", "B": "3"}, {"A": "only", "A_2": "", "B": ""}]
    assert tables[1] == [{"C": "9"}]


def test_unwrap_payload_variants():
    assert unwrap_payload('{"result": "{\\"a\\": 1}"}') == {"a": 1}
    assert unwrap_payload('{"text": "hello"}') == "hello"
    assert unwrap_payload("plain text") == "plain text"
    assert unwrap_payload('{"result": {"data": [1]}}') == {"data": [1]}
    assert unwrap_payload({"data": []}) == {"data": []}


def test_records_from_shapes():
    assert records_from([{"a": 1}, 2]) == [{"a": 1}]
    assert records_from({"rows": [{"a": 1}]}) == [{"a": 1}]
    assert records_from({"meta": {"x": 1}, "whatever": [{"b": 2}]}) == [{"b": 2}]
    assert records_from({"a": 1, "b": "x"}) == [{"a": 1, "b": "x"}]
    assert records_from("| h |\n|---|\n| v |") == [{"h": "v"}]
    assert records_from(None) == []


def test_norm_and_find_col():
    assert norm("netFlowUsd") == "net flow usd"
    assert norm("Net Flow (USD)") == "net flow usd"
    cols = ["Segment", "Inflow USD", "Net Flow USD", "Wallet Count"]
    assert find_col(cols, [["net", "flow"]]) == "Net Flow USD"
    assert find_col(cols, [["inflow"]]) == "Inflow USD"
    assert find_col(cols, [["net"]], exclude=["wallet"]) == "Net Flow USD"
    assert find_col(cols, [["missing"]]) is None


def test_extract_sm_flow_markdown():
    f = extract_sm_flow(fixture_text("flows_md.txt"))
    assert f is not None
    assert f.net_usd == pytest.approx(1.2e6)
    assert f.inflow_usd == pytest.approx(1.5e6)
    assert f.outflow_usd == pytest.approx(3e5)
    assert f.wallets == 12


def test_extract_sm_flow_json():
    f = extract_sm_flow(fixture_text("flows_json.json"))
    assert f is not None
    assert f.net_usd == pytest.approx(-250_000)
    assert f.inflow_usd == pytest.approx(50_000)
    assert f.outflow_usd == pytest.approx(300_000)
    assert f.wallets == 7


def test_extract_sm_flow_net_from_in_out_and_nested_object():
    md = "| Cohort | Inflow | Outflow |\n|---|---|---|\n| smart money | 10k | 4k |"
    f = extract_sm_flow(md)
    assert f is not None and f.net_usd == pytest.approx(6000)
    nested = json.dumps({"summary": {"smartMoney": {"netFlow": "-1.5M"}}})
    f2 = extract_sm_flow(nested)
    assert f2 is not None and f2.net_usd == pytest.approx(-1.5e6)


@pytest.mark.parametrize("text", [
    fixture_text("nansen_error.txt"),
    "complete garbage",
    "",
    '{"result": "no tables here"}',
    "| Segment | Net Flow |\n|---|---|\n| Whales | 5M |",
])
def test_extract_sm_flow_missing_returns_none(text):
    assert extract_sm_flow(text) is None


def test_extract_side_volume():
    buy = extract_side_volume(fixture_text("wbs_buy_md.txt"), "BUY")
    sell = extract_side_volume(fixture_text("wbs_sell_md.txt"), "SELL")
    assert buy is not None and buy.volume_usd == pytest.approx(800_000) and buy.wallets == 3
    assert sell is not None and sell.volume_usd == pytest.approx(200_000) and sell.wallets == 2


def test_extract_side_volume_json_and_empty():
    js = json.dumps({"data": [{"address": "0x1", "volumeUsd": 1000}, {"address": "0x2", "volumeUsd": "2k"}]})
    s = extract_side_volume(js)
    assert s is not None and s.volume_usd == pytest.approx(3000) and s.wallets == 2
    empty = extract_side_volume("No results found for this token.")
    assert empty is not None and empty.volume_usd == 0 and empty.wallets == 0
    assert extract_side_volume('{"data": []}').wallets == 0
    assert extract_side_volume("garbage") is None
    assert extract_side_volume("| Address | Label |\n|--|--|\n| 0x1 | Fund |") is None


def test_side_volume_respects_side_json():
    js = json.dumps({"data": [{"bought_volume_usd": 20000, "sold_volume_usd": 4000},
                              {"bought_volume_usd": "1k", "sold_volume_usd": "500"}]})
    assert extract_side_volume(js, "BUY").volume_usd == pytest.approx(21_000)
    assert extract_side_volume(js, "SELL").volume_usd == pytest.approx(4_500)


def test_side_volume_respects_side_markdown_fixture():
    md = fixture_text("wbs_both_usd_md.txt")
    assert extract_side_volume(md, "BUY").volume_usd == pytest.approx(300_000)
    assert extract_side_volume(md, "SELL").volume_usd == pytest.approx(60_000)
    assert extract_side_volume(md, "BUY").wallets == 2


def test_side_volume_token_units_only_is_unavailable():
    # Only native token volumes: must NOT be summed as dollars.
    md = fixture_text("wbs_token_volume_only_md.txt")
    assert extract_side_volume(md, "BUY") is None
    assert extract_side_volume(md, "SELL") is None
    assert extract_side_volume(json.dumps({"data": [{"volume": 5, "amount": 7}]}), "BUY") is None


def test_side_volume_prefers_usd_over_token_columns():
    md = ("| Address | Bought Token Volume | Bought Volume USD |\n|--|--|--|\n"
          "| 0x1 | 1000000000 | $1.5k |")
    assert extract_side_volume(md, "BUY").volume_usd == pytest.approx(1500)
    value_col = json.dumps({"data": [{"tradeValue": 250, "tokenAmount": 9e9}]})
    assert extract_side_volume(value_col, "SELL").volume_usd == pytest.approx(250)


# ---- price context --------------------------------------------------------------------
from zalat.parsing import extract_price_info  # noqa: E402


def test_extract_price_info_markdown_metric_table():
    price, change = extract_price_info(fixture_text("token_info_md.txt"))
    assert price == pytest.approx(4e-06) and change == pytest.approx(-5.2)


def test_extract_price_info_json():
    price, change = extract_price_info(fixture_text("token_info.json"))
    assert price == pytest.approx(7.85) and change == pytest.approx(12.5)
    flat = json.dumps({"price_usd": 2.0, "percent_change_24h": -1.5, "volume_24h_usd": 1e6})
    assert extract_price_info(flat) == (2.0, -1.5)


def test_extract_price_info_row_table():
    md = "| Symbol | Price USD | Price Change 24h | Volume 24h USD |\n|--|--|--|--|\n| UNI | $7.85 | +3.1% | 180M |"
    assert extract_price_info(md) == (pytest.approx(7.85), pytest.approx(3.1))


@pytest.mark.parametrize("text", ["", "garbage", fixture_text("nansen_error.txt"), "{}", "[1, 2]",
                                  '{"data": {"price": "n/a"}}'])
def test_extract_price_info_failure(text):
    assert extract_price_info(text) == (None, None)


def test_extract_price_info_prefers_24h_change_over_other_windows():
    js = json.dumps({"price": 1.2, "price_change_1h": 0.5, "price_change_24h": -4})
    assert extract_price_info(js) == (pytest.approx(1.2), pytest.approx(-4))
    p, ch = extract_price_info(fixture_text("token_info_windows.json"))
    assert p == pytest.approx(0.85) and ch == pytest.approx(-7.5)


@pytest.mark.parametrize("payload, change", [
    ({"price": 1, "price_change_1h": 0.5, "price_change_7d": 9}, None),   # no 24h -> None
    ({"price": 1, "priceChange5m": 1, "priceChange": 2.5}, 2.5),          # window-less fallback
    ({"price": 1, "change_1d": -3.3, "change_30d": 40}, -3.3),
    ({"price": 1, "percent_change_24h": 6.1, "volume_change_24h": 99}, 6.1),
])
def test_extract_price_info_window_rules(payload, change):
    got = extract_price_info(json.dumps(payload))[1]
    assert got == (pytest.approx(change) if change is not None else None)


def test_extract_price_info_markdown_with_several_windows():
    md = ("| Metric | Value |\n|--|--|\n| Price USD | $0.85 |\n| Price Change 1h | +0.4% |\n"
          "| Price Change 24h | -7.5% |\n| Price Change 7d | +12% |")
    assert extract_price_info(md) == (pytest.approx(0.85), pytest.approx(-7.5))
