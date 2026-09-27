# Zalat Smart Money Verdict

A small command-line tool that asks one question about a crypto token:

> **Is "smart money" doing the same thing as the crowd, or the opposite?**

It compares:

1. **Smart money**: what wallets that Nansen labels as smart traders and funds did with the token recently (net
   flows, and who bought vs. who sold). This data comes from **Nansen's MCP server**.
2. **The crowd**: the [Crypto Fear & Greed Index](https://alternative.me/crypto/fear-and-greed-index/) from
   alternative.me.

It then prints a **verdict in English and Arabic**.

### Why the contrast matters

When smart money and the crowd agree, you rarely learn anything new: everyone is already on the same side of the trade.
The interesting moments are when they **disagree**:

- **Smart money buying while the crowd is fearful.** Experienced traders may be accumulating from panicking sellers.
- **Smart money selling while the crowd is greedy.** Experienced traders may be taking profit from late buyers.

This tool puts that disagreement in the headline.

---

## Verdict types

| Verdict (code)       | English name           | الاسم بالعربية       | When                                                         |
|----------------------|------------------------|----------------------|--------------------------------------------------------------|
| `CONTRARIAN_BULLISH` | Contrarian Bullish     | صعود عكس الجمهور     | Smart money **accumulating** while the crowd is in **Fear / Extreme Fear**. Headline disagreement. |
| `WARNING_BEARISH`    | Warning (Bearish)      | تحذير (هبوطي)        | Smart money **distributing** while the crowd is in **Greed / Extreme Greed**. Headline disagreement. |
| `CONFIRMED_BULLISH`  | Confirmed Bullish      | صعود مؤكَّد           | Both bullish (smart money accumulating, crowd greedy). With Extreme Greed the tool adds a crowded-trade note. |
| `CONFIRMED_BEARISH`  | Confirmed Bearish      | هبوط مؤكَّد           | Both bearish (smart money distributing, crowd fearful). The tool adds a possible-capitulation note. |
| `NEUTRAL`            | Neutral                | محايد                | Smart money or the crowd has no clear direction. The tool also reports a mild lean if there is one. |
| `INSUFFICIENT_DATA`  | Insufficient Data      | بيانات غير كافية     | Nansen data was unavailable or unreadable. The crowd mood is still shown. |
| `SM_ONLY`            | Smart Money Only       | الأموال الذكية فقط   | The Fear & Greed Index could not be fetched, so the tool shows the smart-money reading alone. |

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

1. Log in to Nansen and create an API key in your account/API settings.
2. Copy the example settings file:

   - macOS / Linux: `cp .env.example .env`
   - Windows: `copy .env.example .env`

3. Open `.env` in a text editor and replace `your_key_here` with your key:

   ```
   NANSEN_API_KEY=paste-your-key-here
   ```

**Never commit `.env` or share your key.** `.env` is already listed in `.gitignore`. The tool only sends the key in
an HTTP header to Nansen. It never prints the key, and it removes it from logs, `--raw` output, JSON and stress-test
reports.

You can also set the key as an environment variable instead of using `.env`. If both are set, the environment
variable wins:

- macOS / Linux: `export NANSEN_API_KEY=...`
- Windows PowerShell: `$env:NANSEN_API_KEY="..."`

---

## Usage

```bash
# Basic: token symbol, English + Arabic output, last 1 day
python -m zalat PEPE

# Choose chain and lookback period (5m, 1h, 6h, 12h, 1d, 7d)
python -m zalat UNI --chain ethereum --period 7d

# Skip the symbol search by giving the contract address directly
python -m zalat PEPE --address 0x6982508145454ce325ddbe47a25d4ec3d2311933

# Only one language
python -m zalat PEPE --lang en
python -m zalat PEPE --lang ar

# Machine-readable JSON (for scripts / dashboards)
python -m zalat PEPE --json

# Debug: also print the raw text of every Nansen tool call to stderr
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
| 3 | Token symbol not found on that chain (try `--address`) |
| 4 | Nansen rejected the API key (HTTP 401/403) |
| 5 | Nansen MCP server unreachable (with `--address`, the tool shows a crowd-only verdict and exits 0) |

---

## Sample output

> **Illustrative only.** The numbers below are made up to show the format, and are not real market data.

```text
Zalat Smart Money Verdict
Token: PEPE (Pepe) on ethereum, lookback 1d
Address: 0x6982508145454ce325ddbe47a25d4ec3d2311933
------------------------------------------------------------
VERDICT: Smart money is buying into fear  [Contrarian Bullish]
The crowd is fearful while smart-money wallets accumulate. This is the kind of disagreement worth a closer look.
Disagreement: YES - smart money and the crowd point in opposite directions.

Smart money: Accumulating (moderate), score +0.59
  - Net flow: +$1.2M (in $1.5M / out $300.0k, 12 wallets)
  - Smart buyers vs sellers: $800.0k bought / $200.0k sold (score +0.60)
Crowd mood: Extreme Fear (22/100) - market-wide Fear & Greed Index (BTC-centric), not token-specific
Divergence score: +0.33 (positive = smart money leans against the crowd)

Confidence: High

Not financial advice. For research and education only.

============================================================

حكم زلط للأموال الذكية
العملة: PEPE (Pepe) على شبكة ethereum، الفترة 1d
العنوان: 0x6982508145454ce325ddbe47a25d4ec3d2311933
------------------------------------------------------------
الحكم: الأموال الذكية تشتري وسط الخوف  [صعود عكس الجمهور]
الجمهور خائف بينما محافظ الأموال الذكية تُجمِّع. هذا النوع من التباين يستحق نظرة أعمق.
تباين: نعم - الأموال الذكية والجمهور في اتجاهين متعاكسين.

الأموال الذكية: تجميع (متوسط)، الدرجة +0.59
  - صافي التدفق: +$1.2M (داخل $1.5M / خارج $300.0k، 12 محفظة)
  - المشترون مقابل البائعين الأذكياء: شراء $800.0k / بيع $200.0k (الدرجة +0.60)
مزاج الجمهور: خوف شديد (22/100) - مؤشر الخوف والطمع للسوق كله (يتمحور حول البيتكوين)، وليس خاصاً بهذه العملة
درجة التباين: +0.33 (موجبة = الأموال الذكية عكس الجمهور)

الثقة: مرتفعة

ليست نصيحة مالية. للبحث والتعليم فقط.
```

> Arabic in the terminal: most modern terminals (Windows Terminal, macOS Terminal, iTerm2, GNOME Terminal) display it
> fine. The old Windows console (`cmd.exe` window) may show the letters disconnected, so use **Windows Terminal**.

---

## How the verdict is computed

The tool makes these calls, all in **one MCP session**:

1. `general_search`: finds the token's contract address from its symbol. It needs an exact symbol match on your
   chain, and if there are several it takes the one with the highest 24h volume. `--address` skips this step.
2. `token_recent_flows_summary`: net flow of the **Smart Money** cohort over `--period`.
3. `token_who_bought_sold` (BUY and SELL): USD volume bought and sold by wallets labelled *30D / 90D / 180D / All Time
   Smart Trader* and *Fund*. Any period up to `1d` uses the last day, and `7d` uses the last week.

**Smart-money score** `s` (from -1 to +1):

- `flow_score = tanh(net_flow / (inflow + outflow))`. When inflow and outflow are unknown, the tool divides by a fixed
  $100k instead.
- `buy_sell_score = (bought - sold) / (bought + sold)`
- `s = 0.6 × flow_score + 0.4 × buy_sell_score`. If only one part is available, `s` is that part alone.
- `s ≥ +0.2` means **Accumulating** and `s ≤ -0.2` means **Distributing**. Anything in between is **Neutral**.
  Strength is *strong* when `|s| ≥ 0.6`, *moderate* when `|s| ≥ 0.2`, and *weak* below that.

**Crowd mood** comes from the Fear & Greed value `v` (0 to 100): 0–24 Extreme Fear, 25–44 Fear, 45–55 Neutral,
56–75 Greed, 76–100 Extreme Greed. The crowd score is `c = (v - 50) / 50`.

**Divergence** `= s × (−c)`. A positive value means smart money is leaning against the crowd. The tool flags a
**disagreement** when `|s| ≥ 0.2`, the crowd is outside Neutral, and the two have opposite signs.

**Confidence** starts at High when both smart-money signals are available and at Medium when only one is. It drops one
level for each of these: a weak signal (`|s| < 0.4`), net flow and buy/sell pointing in different directions, fewer
than 3 smart wallets, or a crowd value between 45 and 55. It is Low whenever Nansen data or the Fear & Greed Index is
unavailable. The reasons are printed under **Why:**.

If one Nansen call fails or returns something the tool cannot read, you still get a verdict. That signal is marked
*unavailable* and confidence drops.

---

## Running the tests

The tests are fully offline. They use a fake Nansen client and a fake Fear & Greed source, and any real network call
fails the test.

```bash
python -m pytest -q
```

---

## Stress test (100+ real Nansen MCP calls)

This script makes at least 100 real MCP tool calls to Nansen over a list of tokens, in one session with a short delay
between calls. It keeps going when a call fails and counts every result.

```bash
python scripts/stress_test.py
# or customise:
python scripts/stress_test.py --tokens PEPE,UNI,LINK,AAVE --chain ethereum --min-calls 100 --delay 0.5
```

For each token, in rounds, it runs `general_search`, then `token_recent_flows_summary` for the `1h`, `1d` and `7d`
periods, then `token_who_bought_sold` for BUY and SELL. It stops once it reaches `--min-calls`. Network errors are
retried up to 3 times, and each retry counts as a call. A rejected API key stops the run immediately.

**Output** (the `reports/` folder is git-ignored):

- `reports/stress_report.json`: total calls, successes, failures, per-tool counts and latency (avg/p95), failure
  reasons per tool, parse statistics and a log of every call.
- `reports/raw/<tool>_<token>[_<variant>].txt`: the raw text of the latest response for each kind of call.
- A summary printed to the terminal, for example:

```text
Nansen MCP stress test - completed
  total calls : 100  (target 100)
  successes   : 86
  failures    : 14
  - general_search: 30 calls, 30 ok, 0 failed, avg 850.2 ms, p95 1400.0 ms
  ...
```

(Illustrative numbers.) The API key is never written to these files, and the script checks that before it exits.

---

## Troubleshooting

| Problem | What to do |
|---|---|
| `NANSEN_API_KEY is not set` (exit 2) | Create `.env` from `.env.example` and paste your key, or export `NANSEN_API_KEY`. |
| `Nansen rejected the API key (HTTP 401/403)` (exit 4) | Check the key for typos and extra spaces, and confirm it is active and has API/MCP access in your Nansen account. If Nansen changed the header name, set `NANSEN_API_KEY_HEADER` in `.env`. |
| `Nansen MCP unreachable` (exit 5) | Check your internet connection, VPN, proxy or firewall. If Nansen moved the endpoint, set `NANSEN_MCP_URL` in `.env`. Try `--timeout 60`. |
| `Could not find token` (exit 3) | Check the symbol and `--chain`, or pass `--address <contract>`. |
| Verdict says `INSUFFICIENT_DATA`, or a signal is "unavailable" | A Nansen tool returned an error (e.g. `NANSEN_TOOL_ERROR ... unclassified_failure`) or an unexpected format. Run with `--raw` and **send the `--raw` output** (e.g. `python -m zalat PEPE --raw 2> raw_output.txt`) so the parsers can be tuned. The key is never included. |
| Arabic looks broken | Use Windows Terminal (not the old console window), or a UTF-8 terminal on macOS/Linux. |

Settings you can put in `.env` (or the environment):

```
NANSEN_API_KEY=...                              # required
NANSEN_MCP_URL=https://mcp.nansen.ai/ra/mcp/    # MCP endpoint (default shown)
NANSEN_API_KEY_HEADER=NANSEN-API-KEY            # header that carries the key (default shown)
ZALAT_TIMEOUT=30                                # seconds
```

---

## Limitations (v1)

- **Fear & Greed is market-wide.** It measures overall crypto sentiment and leans heavily on Bitcoin. It is **not**
  sentiment about your specific token, and the output says so.
- The exact response formats of Nansen's data tools are not publicly documented, so the parsers are deliberately
  forgiving. If a format is not recognised, that signal shows as *unavailable* rather than a wrong number. Please
  share `--raw` output if this happens.
- It analyses one token per run. There is no caching, history, backtesting, alerts or charts.
- The thresholds and weights are simple heuristics, not a validated trading model.

---

## Disclaimer

**English:** This tool is for research and education only. It is **not financial advice**. On-chain labels and
sentiment indices can be wrong or late. Do your own research, and never invest more than you can afford to lose.

**العربية:** هذه الأداة للبحث والتعليم فقط، وهي **ليست نصيحة مالية**. قد تكون تصنيفات المحافظ ومؤشرات المزاج
خاطئة أو متأخرة. قم ببحثك الخاص، ولا تستثمر أبداً أكثر مما تستطيع تحمّل خسارته.

---

## License

MIT © HeeHesham. See [LICENSE](LICENSE).
