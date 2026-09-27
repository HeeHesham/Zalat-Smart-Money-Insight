# Zalat Smart Money Verdict

A small command-line tool that asks one question about a crypto token:

> **Is "smart money" doing the same thing as the crowd, or the opposite?**

It compares **what smart money is doing with the token** (the primary signal) with **crowd sentiment**, adds **price
context**, and prints a **verdict in English and Arabic**.

### Data sources

| Source | What it gives | Role | Needs |
|---|---|---|---|
| **Nansen** (REST API, default; MCP server optional) | Smart-money flows, who bought or sold (wallets labelled Smart Trader or Fund), top-PnL traders' flow, price, daily candles (24h change), market cap / liquidity / holders | **Primary.** Only smart money sets the verdict's direction | A Nansen API key (optional for REST when your environment injects it; required for MCP) |
| **LunarCrush** (API v4) | **Token-specific** social sentiment (% of posts that are positive), Galaxy Score, 24h price change | **Preferred crowd signal** when available | `LUNARCRUSH_API_KEY` on a **paid** LunarCrush plan (**optional**) |
| **alternative.me Fear & Greed** | Mood of the **whole crypto market** (mostly driven by BTC) | Crowd signal when LunarCrush is not available; otherwise secondary context | Nothing (free) |

**Nansen endpoints used (REST, default backend, `https://api.nansen.ai/api/v1`, all `POST`):**

| Purpose | Endpoint | Used for |
|---|---|---|
| Find the token | `search/general` | contract address, live price, 24h volume |
| Smart-money flow | `tgm/flow-intelligence` | `smart_trader_*` net flow, average flow per wallet, wallet count (scored); `top_pnl_*` (context only) |
| Who bought / sold | `tgm/who-bought-sold` (BUY and SELL) | USD bought and sold by Smart Trader / Fund wallets |
| Price change | `tgm/token-ohlcv` | 24h change = last daily close vs previous close |
| Market context | `tgm/token-information` | market cap, liquidity, holders (display only) |

Set `ZALAT_NANSEN_BACKEND=mcp` to use Nansen's **MCP server** (`https://mcp.nansen.ai/ra/mcp/`) instead. MCP needs a real
`NANSEN_API_KEY`, because the MCP server forwards your key to the same REST API.

> **Important:** the Fear & Greed Index is **market-wide**. It is **not** sentiment about your token. Every line that
> shows it says so, and a verdict based only on it is capped at **Medium** confidence.
>
> **LunarCrush is optional, and is future work unless you have a paid key.** The free "Hobby" tier has **no social
> sentiment**, so without a paid key (or with no key) the tool skips LunarCrush entirely, makes **no** request to it, and
> compares smart money with the market-wide mood instead. The output then includes this note:
> *"Token social sentiment: not configured - needs a paid LunarCrush API plan (set LUNARCRUSH_API_KEY). Future work;
> this verdict compares smart money with market-wide mood instead."*

### Why the contrast matters

When smart money and the crowd agree, you rarely learn anything new: everyone is already on the same side of the trade.
The interesting moments are when they **disagree**:

- **Smart money buying while the crowd is bearish or fearful.** Experienced traders may be buying from sellers who
  are panicking.
- **Smart money selling while the crowd is bullish or greedy.** Experienced traders may be taking profit from late
  buyers.

This tool puts that disagreement in the headline, and it always tells you **which** crowd it means: this token's own
social crowd, or the overall market mood.

---

## Verdict types

The verdict code is the same whichever crowd was used, but the headline names that crowd. In Arabic, the short name
also changes on the market-wide path: `CONTRARIAN_BULLISH` becomes "صعود عكس مزاج السوق" and `WARNING_BEARISH` becomes
"تحذير: بيع وسط طمع السوق". For example: "Smart money is
buying while this token's social crowd is bearish", or "Smart money is buying while the overall crypto market is
fearful (market-wide mood, not this token)".

| Verdict (code)       | English name           | الاسم بالعربية       | When                                                         |
|----------------------|------------------------|----------------------|--------------------------------------------------------------|
| `CONTRARIAN_BULLISH` | Contrarian Bullish     | صعود عكس الجمهور     | Smart money **accumulating** while the crowd is **bearish / fearful**. Headline disagreement. |
| `WARNING_BEARISH`    | Warning (Bearish)      | تحذير (هبوطي)        | Smart money **distributing** while the crowd is **bullish / greedy**. Headline disagreement. |
| `CONFIRMED_BULLISH`  | Confirmed Bullish      | صعود مؤكَّد           | Both bullish. If the crowd is extremely optimistic, the tool adds a crowded-trade note. |
| `CONFIRMED_BEARISH`  | Confirmed Bearish      | هبوط مؤكَّد           | Both bearish. The tool adds a possible-capitulation note. |
| `NEUTRAL`            | Neutral                | محايد                | Smart money or the crowd has no clear direction. The tool also reports a mild lean if there is one. |
| `INSUFFICIENT_DATA`  | Insufficient Data      | بيانات غير كافية     | Nansen data was unavailable or unreadable. The other signals are still shown. |
| `SM_ONLY`            | Smart Money Only       | الأموال الذكية فقط   | Neither crowd signal could be fetched, so the tool shows the smart-money reading alone. |

Every verdict comes with a **confidence** level (High / Medium / Low, مرتفعة / متوسطة / منخفضة) and a list of the
reasons it was lowered.

---

## Prerequisites

- **Python 3.11 or newer.** Check with `python --version` (on macOS/Linux you may need `python3`).
- **Git**, to clone the repository.
- **A Nansen API key.** You create it in your Nansen account (see below).
- Internet access to `mcp.nansen.ai` and `api.alternative.me`.

---

## Installation (step by step)

### 1. Clone the repository

```bash
git clone https://github.com/<your-user>/Zalat-Smart-Money-Insight.git
cd Zalat-Smart-Money-Insight
```

### 2. Create and activate a virtual environment

A virtual environment keeps this project's packages separate from the rest of your system.

**Windows (PowerShell):**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell refuses to run the script, run this once and try again:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

**Windows (cmd.exe):**

```bat
python -m venv .venv
.venv\Scripts\activate.bat
```

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

When it is active, your prompt starts with `(.venv)`.

### 3. Install the dependencies

```bash
pip install -r requirements.txt
```

> `requirements.txt` pins the MCP SDK to `mcp>=1.30,<2`. Version 2.x of the SDK is a breaking rewrite, so please don't
> upgrade it by hand.

---

## Your Nansen API key

**REST backend (default): the key is optional.** If `NANSEN_API_KEY` is not set, the tool sends **no** key header at
all. This supports setups where a proxy or gateway injects the credential for `api.nansen.ai`. If Nansen then answers
HTTP 401/403, the tool stops with exit code 4 and the message *"Nansen rejected the request: set NANSEN_API_KEY in
.env"*. **MCP backend: the key is required.**

To use your own key:

1. Log in to Nansen and create an API key in your account/API settings.
2. Copy the example settings file:

   - macOS / Linux: `cp .env.example .env`
   - Windows: `copy .env.example .env`

3. Open `.env` in a text editor and replace `your_key_here` with your key:

   ```
   NANSEN_API_KEY=paste-your-key-here
   ```

The REST backend sends the key in the `apiKey` header, and the MCP backend sends it in `NANSEN-API-KEY`. You can
override the header name with `NANSEN_API_KEY_HEADER`.

**Never commit `.env` or share your key.** `.env` is already listed in `.gitignore`. The tool only sends the key in
an HTTP header to Nansen. It never prints the key, and it removes it from logs, `--raw` output, JSON and stress-test
reports.

You can also set the key as an environment variable instead of using `.env`. If both are set, the environment
variable wins:

- macOS / Linux: `export NANSEN_API_KEY=...`
- Windows PowerShell: `$env:NANSEN_API_KEY="..."`

### Request IDs (for Nansen support)

Every REST call records Nansen's `X-Request-Id` (or the `request_id` from an error body), the HTTP status, the credits
used and remaining, and the remaining rate limit. You can see them in two places:

- with `--raw`: `=== token_ohlcv ok=True http=200 request_id=17660b… credits_cost=1 credits_remaining=28080 ===`
- with `-v`: one log line per call

The stress report lists them for every call. On HTTP 429 the tool waits as told by `Retry-After` / `Ratelimit-Reset`
and retries up to 3 times.

---

## Optional: LunarCrush key (token social sentiment)

Skip this section if you don't have a **paid** LunarCrush plan. The free "Hobby" tier does not include social
sentiment. Everything works without it: the verdict falls back to the market-wide Fear & Greed mood and says so.

If you do have a paid key, add it to `.env`:

```
LUNARCRUSH_API_KEY=paste-your-lunarcrush-key-here
```

The key is sent only in an `Authorization: Bearer` header to LunarCrush, and it is removed from all output, just like
the Nansen key. If LunarCrush rejects the key or your plan has no social data (HTTP 401/402/403), rate-limits you, or
returns no sentiment, the verdict still renders. It uses the market-wide mood and adds a note explaining why.

---

## Usage

```bash
# Basic: token symbol, English + Arabic output, last 1 day
python -m zalat PEPE

# Choose chain and lookback period (5m, 1h, 6h, 12h, 1d, 7d)
python -m zalat UNI --chain ethereum --period 7d

# Skip the symbol search by giving the contract address directly.
# Give the matching symbol too (here PEPE for the PEPE contract): it is used for the
# display name and for LunarCrush. Without a symbol, LunarCrush is skipped.
python -m zalat PEPE --address 0x6982508145454ce325ddbe47a25d4ec3d2311933

# Only one language
python -m zalat PEPE --lang en
python -m zalat PEPE --lang ar

# Machine-readable JSON (for scripts / dashboards)
python -m zalat PEPE --json

# Debug: also print the raw text of every Nansen tool call (and the LunarCrush status) to stderr
python -m zalat PEPE --raw

# Save raw output to a file you can share (the key is never in it)
python -m zalat PEPE --raw 2> raw_output.txt
```

Other options: `--timeout 60` (network timeout in seconds), `-v` (debug log, key redacted), `--version`, `--help`.

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Verdict printed (even a partial one, e.g. `INSUFFICIENT_DATA`) |
| 1 | Unexpected error |
| 2 | Bad arguments, or `NANSEN_API_KEY` missing |
| 3 | The search worked but found no token with that symbol on that chain (try `--address`) |
| 4 | Nansen rejected the API key (HTTP 401/403) |
| 5 | Nansen unreachable, or the token search call itself failed (with `--address`, an unreachable server gives a sentiment-only verdict and exit 0) |

LunarCrush, Fear & Greed and `token_info` problems never change the exit code. They only mark that signal as unavailable.

---

## Sample output

**Real output** from a live run on 2026-09-27: `python -m zalat PEPE` with the REST backend, no LunarCrush key, English
part only. Real Nansen and Fear & Greed data at that moment, not a prediction:

```text
Zalat Smart Money Verdict
Token: PEPE (Pepe) on ethereum, lookback 1d
Address: 0x6982508145454ce325ddbe47a25d4ec3d2311933
------------------------------------------------------------
VERDICT: No clear divergence between smart money and the overall market mood  [Neutral]
Either smart money or the market-wide mood has no strong direction.
Disagreement: no

Smart money: Neutral (weak), score -0.02
  - Net flow: -$1.5k (12 wallets, avg $6.8k per wallet, estimated gross $82.1k)
  - Smart buyers vs sellers: $0.00 bought / $0.00 sold (score n/a)
  - Top PnL traders net flow (context, not scored): -$165.3k (17 wallets)
Price: $0.000004417 (-0.1% over 24h, source Nansen OHLCV)
Market context: market cap $1.8B, liquidity $17.1M, holders 409,320
Market-wide mood (whole crypto market, BTC-centric; NOT specific to PEPE (Pepe)): Greed (70/100) - alternative.me Fear & Greed
Divergence score: +0.01 (positive = smart money leans against the overall market mood)

Confidence: Low
Why:
  - no smart-money buys or sells in this period
  - only one of the two smart-money signals was available
  - only the market-wide mood was available, not this token's own crowd (capped at Medium)
  - smart-money signal is weak (strength 0.02, below 0.40)

Mild lean: smart money slightly negative.
Token social sentiment: not configured - needs a paid LunarCrush API plan (set LUNARCRUSH_API_KEY). Future work; this verdict compares smart money with market-wide mood instead.

Not financial advice. For research and education only.
```

On that day no labelled smart-money wallet traded PEPE in the last 24h (both BUY and SELL lists were empty), so only
the flow signal was available and confidence is Low. The two samples below are **illustrative only**. Their numbers
are made up to show the other verdict formats, and are not real market data.

**(a) Default: no LunarCrush key.** The crowd is the market-wide mood, and the output says so:

```text
Zalat Smart Money Verdict
>>> DISAGREEMENT: SMART MONEY vs OVERALL MARKET MOOD <<<
Token: PEPE (Pepe) on ethereum, lookback 1d
Address: 0x6982508145454ce325ddbe47a25d4ec3d2311933
------------------------------------------------------------
VERDICT: Smart money is buying while the overall crypto market is fearful (market-wide mood, not this token)  [Contrarian Bullish]
The whole crypto market is fearful while smart-money wallets accumulate this token. Worth a closer look, but the mood describes the market, not this token's own crowd.
Disagreement: YES - smart money and the overall market mood point in opposite directions.

Smart money: Accumulating (strong), score +0.64
  - Net flow: +$1.2M (in $1.5M / out $300.0k, 12 wallets)
  - Smart buyers vs sellers: $800.0k bought / $200.0k sold (score +0.60)
Price: $0.000004 (-5.2% over 24h, source Nansen token_info)
Market-wide mood (whole crypto market, BTC-centric; NOT specific to PEPE (Pepe)): Extreme Fear (22/100) - alternative.me Fear & Greed
Divergence score: +0.36 (positive = smart money leans against the overall market mood)

Confidence: Medium
Why:
  - only the market-wide mood was available, not this token's own crowd (capped at Medium)

Price context: price falling while smart money buys (accumulation on a dip).
Token social sentiment: not configured - needs a paid LunarCrush API plan (set LUNARCRUSH_API_KEY). Future work; this verdict compares smart money with market-wide mood instead.

Not financial advice. For research and education only.

============================================================

حكم زلط للأموال الذكية
>>> تباين: الأموال الذكية عكس مزاج السوق العام <<<
العملة: PEPE (Pepe) على شبكة ethereum، الفترة 1d
العنوان: 0x6982508145454ce325ddbe47a25d4ec3d2311933
------------------------------------------------------------
الحكم: الأموال الذكية تشتري بينما يسود الخوف سوق الكريبتو بأكمله (مزاج السوق العام، وليس هذه العملة)  [صعود عكس مزاج السوق]
سوق الكريبتو بأكمله خائف بينما محافظ الأموال الذكية تُجمِّع هذه العملة. يستحق نظرة أعمق، لكن المزاج يصف السوق وليس جمهور هذه العملة.
تباين: نعم - الأموال الذكية ومزاج السوق العام في اتجاهين متعاكسين.

الأموال الذكية: تجميع (قوي)، الدرجة +0.64
  - صافي التدفق: +$1.2M (وارد $1.5M / صادر $300.0k، 12 محفظة)
  - المشترون مقابل البائعين الأذكياء: شراء $800.0k / بيع $200.0k (الدرجة +0.60)
السعر: $0.000004 (-5.2% خلال 24 ساعة، المصدر Nansen token_info)
مزاج السوق العام (سوق الكريبتو بأكمله، يتمحور حول البيتكوين؛ ليس خاصاً بـ PEPE (Pepe)): خوف شديد (22/100) - مؤشر الخوف والطمع alternative.me
درجة التباين: +0.36 (موجبة = الأموال الذكية عكس مزاج السوق العام)

الثقة: متوسطة
الأسباب:
  - توفر مزاج السوق العام فقط وليس جمهور هذه العملة (الحد الأقصى: متوسطة)

سياق السعر: السعر يهبط بينما الأموال الذكية تشتري (تجميع عند الانخفاض).
المشاعر الاجتماعية الخاصة بالعملة: غير مُفعَّلة - تتطلب اشتراكاً مدفوعاً في LunarCrush (عيّن LUNARCRUSH_API_KEY). عمل مستقبلي؛ هذا الحكم يقارن الأموال الذكية بمزاج السوق العام بدلاً منها.

ليست نصيحة مالية. للبحث والتعليم فقط.
```

**(b) With a paid LunarCrush key:** the token's own social crowd is the primary crowd, and the market-wide mood is
shown as secondary context (English part only):

```text
Zalat Smart Money Verdict
>>> DISAGREEMENT: SMART MONEY vs TOKEN'S SOCIAL CROWD <<<
Token: PEPE (Pepe) on ethereum, lookback 1d
Address: 0x6982508145454ce325ddbe47a25d4ec3d2311933
------------------------------------------------------------
VERDICT: Smart money is buying while this token's social crowd is bearish  [Contrarian Bullish]
Social sentiment about this token is negative while smart-money wallets accumulate it. This is the kind of disagreement worth a closer look.
Disagreement: YES - smart money and the token's social crowd point in opposite directions.

Smart money: Accumulating (strong), score +0.64
  - Net flow: +$1.2M (in $1.5M / out $300.0k, 12 wallets)
  - Smart buyers vs sellers: $800.0k bought / $200.0k sold (score +0.60)
Price: $0.000004 (-5.2% over 24h, source Nansen token_info)
Token social sentiment (PEPE, LunarCrush): Bearish - 25% positive, Galaxy Score 65
Secondary context - Market-wide mood (whole crypto market, BTC-centric; NOT specific to PEPE (Pepe)): Greed (72/100) - alternative.me Fear & Greed
Divergence score: +0.32 (positive = smart money leans against the token's social crowd)

Confidence: High

Price context: price falling while smart money buys (accumulation on a dip).
Note: this token's crowd diverges from the overall market mood.

Not financial advice. For research and education only.
```

> Arabic in the terminal: most modern terminals (Windows Terminal, macOS Terminal, iTerm2, GNOME Terminal) display it
> fine. The old Windows console (`cmd.exe` window) may show the letters disconnected, so use **Windows Terminal**.

---

## How the verdict is computed

The tool makes these Nansen calls. With the default REST backend they go to the endpoints listed in
[Data sources](#data-sources); with MCP they are the matching MCP tools, all in one session:

1. `general_search`: finds the token's contract address from its symbol. It needs an exact symbol match on your
   chain, and if there are several it takes the one with the highest 24h volume. Perp markets (e.g. Hyperliquid
   `kPEPE`) are skipped. It also records the live **price**. `--address` skips this step.
2. `token_recent_flows_summary` (flow-intelligence): net flow of the **Smart Trader** cohort over `--period`. The
   **top-PnL traders** cohort is shown as a context line and is not scored.
3. `token_who_bought_sold` (BUY and SELL): wallets labelled *30D / 90D / 180D Smart Trader*, *Smart Trader* and *Fund*
   that traded at least $10. The two lists are **merged by wallet address**, because each row carries both bought and
   sold USD. Any period up to `1d` uses the last 24 hours, and `7d` uses the last 7 days.
4. `token_ohlcv`: daily candles; 24h change = last close vs previous close.
5. `token_info`: market cap, liquidity and holders, shown for context. If this or `token_ohlcv` fails, nothing else is
   affected.

While these run, the tool fetches the Fear & Greed Index and, only if `LUNARCRUSH_API_KEY` is set, the token's
LunarCrush data. Both run at the same time as the Nansen calls.

### 1. Smart-money score `s` (-1 to +1). This alone sets the direction

- `flow_score = net_flow / gross_flow`, clamped to -1…+1: the share of smart-money volume that was net buying.
  - Gross flow is inflow + outflow when Nansen reports them (MCP tables).
  - The REST API only gives net flow, **average flow per wallet** and **wallet count**. So gross is **estimated** as
    `avg_flow × wallet_count`, and the output says "estimated gross".
  - If neither is available, the tool uses `tanh(net_flow / $100k)`.
- `buy_sell_score = (bought - sold) / (bought + sold)`, using **USD** volume only, summed once per unique wallet across
  the BUY and SELL lists. Columns in native token units are
  never added up as dollars. If there is no USD column, this part is marked unavailable.
- **Minimum size:** both parts are multiplied by `min(1, gross / $10,000)`. For flows, gross is inflow + outflow (or
  the estimate above); for buy/sell, it is bought + sold. So $40 of one-sided "dust" scores about 0.004, not +1.00. You can change the threshold
  with `ZALAT_MIN_GROSS_USD` (`0` turns the damping off).
- `s = 0.6 × flow_score + 0.4 × buy_sell_score`. If only one part is available, `s` is that part alone.
- `s ≥ +0.2` means **Accumulating** and `s ≤ -0.2` means **Distributing**. Anything in between is **Neutral**.
  Strength is *strong* when `|s| ≥ 0.6`, *moderate* when `|s| ≥ 0.2`, and *weak* below that.

### 2. Crowd signal: the primary one is picked in this order

| Priority | Source | Crowd score `c` | Buckets |
|---|---|---|---|
| 1 | LunarCrush token social sentiment `x` (% positive), when the status is OK | `(x - 50) / 50` | ≤20 Very Bearish, 21–40 Bearish, **41–60 Mixed (neutral)**, 61–79 Bullish, ≥80 Very Bullish |
| 2 | Fear & Greed value `v` (**market-wide**) | `(v - 50) / 50` | 0–24 Extreme Fear, 25–44 Fear, **45–55 Neutral**, 56–75 Greed, 76–100 Extreme Greed |
| – | neither available | – | verdict `SM_ONLY` |

- "Bearish" and "Fear" count as the **bearish side**, and "Bullish" and "Greed" as the **bullish side**.
- LunarCrush is not used if its price is more than 2× away from Nansen's search price. That usually means the same
  ticker belongs to another coin, and the status is shown as `mismatch`.
- When LunarCrush is the primary crowd, Fear & Greed is still shown as **secondary context**. If the two point in
  opposite directions, the tool adds a note that this token's crowd diverges from the overall market mood.
- The Fear & Greed buckets are this tool's own, so the label shown can differ slightly from the
  `value_classification` text on alternative.me's site. The JSON output includes both.

### 3. The verdict matrix (thresholds)

| Smart money \ Crowd | Bearish side | Neutral / Mixed | Bullish side |
|---|---|---|---|
| **Accumulating** (`s ≥ 0.2`) | `CONTRARIAN_BULLISH` (disagreement) | `NEUTRAL` | `CONFIRMED_BULLISH` |
| **Neutral** | `NEUTRAL` | `NEUTRAL` | `NEUTRAL` |
| **Distributing** (`s ≤ -0.2`) | `CONFIRMED_BEARISH` | `NEUTRAL` | `WARNING_BEARISH` (disagreement) |

**Divergence** `= s × (−c)`, using the primary crowd. A positive value means smart money is leaning against the crowd.

### 4. Price context (notes and confidence only, never the verdict)

The tool takes the price from the Nansen search, then from `token_info`, then from the last OHLCV close, then from
LunarCrush. The 24h change comes from **Nansen OHLCV** (last daily close vs the previous close), then `token_info`,
then LunarCrush. The last daily candle is usually the current, still-open day. A change of +3% or more is **Rising**, -3% or less is **Falling**, and anything
else is Flat. The tool then adds one of these notes:

| Smart money | Price Falling | Price Rising |
|---|---|---|
| Accumulating | accumulation on a dip | buying into momentum |
| Distributing | exiting weakness | distribution into strength |

### 5. Confidence

Confidence starts at High when both smart-money parts are available, and at Medium when only one is. It drops one
level for each of these:

- a weak signal (`|s| < 0.4`)
- net flow and buy/sell pointing in different directions
- fewer than 3 smart wallets
- smart-money volume under the minimum size
- a crowd in its neutral band (F&G 45–55 or social 41–60)
- a price move of 20% or more in 24h

The wallet count comes from the flows summary. If that is missing, the tool uses the larger of the buyer and seller
counts, which is a lower bound.

When the only crowd signal is the **market-wide** mood, confidence **starts at Medium at most**, because that mood does
not describe this token's own crowd. The reason "only the market-wide mood was available" is always listed. The ceiling
applies **before** the penalties, so a market-only verdict with any penalty above ends up **Low**. Confidence is Low when Nansen data or every crowd signal is unavailable. The reasons
are printed under **Why:**.

If one call fails or returns something the tool cannot read, you still get a verdict. That signal is marked
*unavailable* and confidence drops.

---

## Running the tests

The tests are fully offline. They use a fake Nansen client and fake Fear & Greed and LunarCrush sources, and any real network call
fails the test.

```bash
python -m pytest -q
```

---

## Stress test (100+ real Nansen calls)

This script makes at least 100 real calls to Nansen over a list of tokens. It uses the REST backend by default, or
`--backend mcp`, with one client and a short delay between calls. It keeps going when a call fails and records every
result.

```bash
python scripts/stress_test.py
# or customise:
python scripts/stress_test.py --tokens PEPE,UNI,LINK,AAVE --chain ethereum --min-calls 100 --delay 0.5
```

Options:

| Option | Default | Meaning |
|---|---|---|
| `--backend` | `ZALAT_NANSEN_BACKEND` or `rest` | `rest` or `mcp` |
| `--tokens` | `PEPE,UNI,LINK,AAVE,SHIB,LDO,MKR,ARB,ONDO,ENA` | Comma-separated symbols (at least one) |
| `--chain` | `ethereum` | Chain to search on |
| `--periods` | `1d,7d` | Flow lookback periods per token (each must be one of `5m,1h,6h,12h,1d,7d`) |
| `--min-calls` | `100` | Stop once this many calls were made |
| `--max-calls` | min-calls + 20 | Hard cap on calls, including retries |
| `--delay` | `0.3` | Seconds between calls |
| `--timeout` | 30 or `ZALAT_TIMEOUT` | Network timeout in seconds |
| `--out` | `reports` | Output folder |

The script exits with 0 when the target is reached, 1 when it is not, 2 for bad options or a missing key (MCP only),
4 when the key is rejected and 5 when Nansen is unreachable.

For each token, in rounds, it runs:

1. `general_search`
2. flow-intelligence for each period (`1d`, `7d`)
3. who-bought-sold BUY and SELL
4. `token_ohlcv`
5. `token_info`

It stops once it reaches `--min-calls`. It counts **only Nansen calls**, and it never calls LunarCrush or the Fear &
Greed API. Network errors and rate limits (429) are retried up to 3 times, and each retry counts as a call. The REST
client also honours `Retry-After` / `Ratelimit-Reset`. A rejected API key stops the run immediately.

**Output** (the `reports/` folder is git-ignored):

- `reports/stress_report.json`:
  - totals, successes and failures
  - per-tool counts and latency (avg/p95), and failure reasons per tool
  - parse statistics
  - `credits_used` and `credits_remaining`
  - `calls`: **every call**, with tool, token, variant, ok, `http_status`, `request_id`, latency, credits and error
    reason
  - `failed_calls`: every failed call with its `request_id`, ready to send to Nansen support
- `reports/raw/<tool>_<token>[_<variant>].txt`: the raw response of the latest call of each kind. The first line
  holds the HTTP status and request id.
- A summary printed to the terminal, for example:

```text
Nansen stress test (rest) - completed
  total calls : 100  (target 100)
  successes   : 98
  failures    : 2
  - general_search: 15 calls, 15 ok, 0 failed, avg 650.2 ms, p95 900.0 ms
  ...
  credits     : used 85.0, remaining 27995
  failed calls (request ids; full list in the report):
    #42 token_info LINK  http=500 request_id=… reason=http_500
```

(Illustrative numbers.) API keys are never written to these files, and the script checks that before it exits.

---

## Troubleshooting

| Problem | What to do |
|---|---|
| `NANSEN_API_KEY is not set` (exit 2) | Create `.env` from `.env.example` and paste your key, or export `NANSEN_API_KEY`. |
| `Nansen rejected the request: set NANSEN_API_KEY in .env` (exit 4, REST) | No key was sent (or it was wrong) and Nansen answered 401/403. Put your key in `.env`. The message includes the `request_id`. |
| `Nansen rejected the API key` (exit 4, MCP) | Check the key for typos and extra spaces, and confirm it is active and has API/MCP access in your Nansen account. If Nansen changed the header name, set `NANSEN_API_KEY_HEADER` in `.env`. |
| MCP data tools fail with "401 Invalid API key" | The MCP server forwards your key to the REST API. Use a real key, or switch back to the default REST backend. |
| `Nansen unreachable` (exit 5) | Check your internet connection, VPN, proxy or firewall. If Nansen moved the endpoint, set `NANSEN_API_URL` (REST) or `NANSEN_MCP_URL` (MCP) in `.env`. Try `--timeout 60`. |
| Rate limited (429) | The tool already waits and retries 3 times. For the stress test, raise `--delay`. |
| `Token search failed (tool_error: ...)` (exit 5) | The `general_search` call failed on Nansen's side. Try again later, pass `--address <contract>`, or send the `--raw` output. |
| `Could not find token` (exit 3) | Check the symbol and `--chain`, or pass `--address <contract>`. |
| "no smart-money buys or sells in this period" | Real result: no labelled smart wallet traded the token in that window. Try `--period 7d`. |
| Verdict says `INSUFFICIENT_DATA`, or a signal is "unavailable" | A Nansen call returned an error (e.g. `NANSEN_TOOL_ERROR ... unclassified_failure`, or an HTTP error) or an unexpected format. Run with `--raw` and **send the `--raw` output, including the request_id lines** (e.g. `python -m zalat PEPE --raw 2> raw_output.txt`) so the parsers can be tuned. The key is never included. |
| "Token social sentiment: not configured" | Expected without `LUNARCRUSH_API_KEY`. The verdict uses the market-wide mood instead. Social sentiment needs a paid LunarCrush plan. |
| "Token social sentiment: unavailable - key rejected or plan lacks social data (HTTP 402)" | Your LunarCrush key is wrong, or your plan (e.g. the free Hobby tier) has no social data. Remove the key or upgrade. |
| "LunarCrush price does not match this token" | The ticker probably belongs to a different coin on LunarCrush, so the tool ignores it on purpose. |
| Arabic looks broken | Use Windows Terminal (not the old console window), or a UTF-8 terminal on macOS/Linux. |

Settings you can put in `.env` (or the environment):

```
NANSEN_API_KEY=...                              # optional for REST (default), required for MCP
ZALAT_NANSEN_BACKEND=rest                       # rest (default) or mcp
NANSEN_API_URL=https://api.nansen.ai/api/v1     # REST base URL (default shown)
NANSEN_MCP_URL=https://mcp.nansen.ai/ra/mcp/    # MCP endpoint (default shown)
NANSEN_API_KEY_HEADER=...                       # key header; default apiKey (REST) / NANSEN-API-KEY (MCP)
ZALAT_TIMEOUT=30                                # seconds
ZALAT_FNG_URL=https://api.alternative.me/fng/?limit=2   # Fear & Greed endpoint (default shown)
ZALAT_MIN_GROSS_USD=10000                       # smart-money volume below this (USD) is scaled down; 0 = off
LUNARCRUSH_API_KEY=...                          # optional, PAID plan only; unset = LunarCrush skipped
LUNARCRUSH_URL=https://lunarcrush.com/api4      # LunarCrush API base (default shown)
```

---

## Limitations and future work

- **Fear & Greed is market-wide.** It measures the mood of the whole crypto market and leans heavily on Bitcoin. It is
  **not** sentiment about your token. The output says so on every line where it appears, and verdicts based only on
  it are capped at Medium confidence.
- **Token-specific social sentiment (LunarCrush) is future work unless you have a paid key.** The free Hobby tier has
  no social sentiment. The LunarCrush field names **and formats** come from its public docs and have **not been
  verified against live responses**, so they are parsed defensively:
  - `sentiment` is expected as 0–100 (% positive). A value between 0 and 1 is treated as a fraction and multiplied by
    100 (0.78 becomes 78%).
  - `percent_change_24h` is assumed to already be a percent and is **not** rescaled. If LunarCrush returned it as a
    fraction, the price notes would under-state the move. LunarCrush sentiment also tends to run high (often 60–85%), so its
  buckets may need tuning.
- Price change is always the **24h** window, whatever `--period` you choose for smart money. Other windows reported
  by Nansen (1h, 7d, 30d...) are ignored on purpose.
- The exact response formats of Nansen's data tools are not publicly documented, so the parsers are deliberately
  forgiving. If a format is not recognised, that signal shows as *unavailable* rather than a wrong number. Please
  share `--raw` output if this happens.
- **Flow gross is estimated on REST.** `tgm/flow-intelligence` has no inflow/outflow split, so the flow score uses
  gross ≈ average flow per wallet × wallet count.
- **Who-bought-sold is the top 25 wallets per side** (one page, trades of at least $10). Very active tokens may have
  more smart wallets than that.
- It analyses one token per run. There is no caching, history, backtesting, alerts or charts.
- The thresholds and weights are simple heuristics, not a validated trading model.

**ملاحظة بالعربية:** مؤشر الخوف والطمع يقيس مزاج سوق الكريبتو بأكمله (ويتمحور حول البيتكوين)، وليس خاصاً بعملتك.
المشاعر الاجتماعية الخاصة بكل عملة عبر LunarCrush اختيارية وتتطلب اشتراكاً مدفوعاً؛ بدونها تعمل الأداة وتقارن
الأموال الذكية بمزاج السوق العام، وهذا مُدرج كعمل مستقبلي.

---

## Disclaimer

**English:** This tool is for research and education only. It is **not financial advice**. On-chain labels and
sentiment indices can be wrong or late. Do your own research, and never invest more than you can afford to lose.

**العربية:** هذه الأداة للبحث والتعليم فقط، وهي **ليست نصيحة مالية**. قد تكون تصنيفات المحافظ ومؤشرات المزاج
خاطئة أو متأخرة. قم ببحثك الخاص، ولا تستثمر أبداً أكثر مما تستطيع تحمّل خسارته.

---

## License

MIT © HeeHesham. See [LICENSE](LICENSE).
