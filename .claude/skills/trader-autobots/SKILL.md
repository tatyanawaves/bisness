---
name: trader-autobots
description: >-
  Paper Autobots. Runs, monitors, tunes and stops the two automatic PAPER
  trading bots in autobot/: the monthly momentum + reversal bot
  (paper_bot.py, top 10 of ~98 US large caps, rebalanced once a month, buys
  at 15:20 ET) and the intraday opening-range breakout bot (orb_bot.py,
  chains trader-scanner, trader-entry, trader-exit, trader-timemachine,
  trader-budget and trader-risk into one bracket order, flat by 15:55 ET).
  Shows both side by side against SPY with report.py. Use when the user says
  "отчёт", "report", "how are the bots doing", "compare the strategies",
  "run the bot", "dry run", "stop the bot", "pause", "resume", "change the
  bot's limits", "tune the strategy", "liquidate", or asks about the
  scheduled bot runs.
argument-hint: "[report | dry-run | stop | resume | tune | liquidate]"
---

# trader-autobots

Two bots trade the Alpaca **paper** account on their own, on a schedule the
user turned on. Every other skill in this pack asks the user for a yes on each
order; these bots do not, because the user explicitly asked for paper-only
automation. That is why their hard rules live in code, not in settings.

| bot | file | money | when it runs | what it does |
| --- | --- | --- | --- | --- |
| monthly | `autobot/paper_bot.py` | $5,000 sleeve | weekdays 15:20 ET | once a month: rank 12-1 month momentum + 5-day reversal, keep stocks above their 200-day average while SPY is above its own, buy the top 10 equal weight. Every day: sell everything if the sleeve is down 15% |
| intraday | `autobot/orb_bot.py` | $5,000 sleeve | weekdays hourly 9:55 to 15:55 ET | 9:50-15:30: one bracket trade at most per run, only when the Time Machine replays AND the ~60-day history both show a positive average R. After 15:45: cancel its legs and sell what it holds |
| report | `autobot/report.py` | | on demand and after every run | both bots: equity, P/L, % return, fills, holdings, SPY over the same period |

## Hard rules (in the code, do not remove)

- Only `https://paper-api.alpaca.markets`. There is no live-account switch, and
  a bot exits if the account number does not start with `PA`.
- Every order goes through `trader-risk/check.py` with the bot's own config;
  only PASS is sent. Verdicts go to the bot's own folder, never to the shared
  `trader/state/risk.json` that manual tickets use.
- Each bot only counts its own orders (`client_order_id` starts with
  `autobot-` or `orbbot-`), so the two bots and manual trades never mix, even
  in the same ticker. All state is rebuilt from Alpaca on every run.
- Dry run unless `--trade`. The kill switch is a `STOP` file in the bot's folder.
- Never point a bot at a live account, never raise a limit, and never turn a
  bot back on without the user asking in the chat.

## Commands

```bash
python3 autobot/report.py                 # both bots vs SPY
python3 autobot/report.py --json

python3 autobot/paper_bot.py              # dry run: what the monthly bot would do now
python3 autobot/paper_bot.py --trade      # what the schedule runs
python3 autobot/paper_bot.py --force-rebalance --trade   # rebalance again this month (user asked)
python3 autobot/paper_bot.py --liquidate --trade         # sell everything, then STOP

python3 autobot/orb_bot.py                # dry run (takes ~5 minutes: full-market scan)
python3 autobot/orb_bot.py --trade        # what the schedule runs
python3 autobot/orb_bot.py --flatten --trade             # close its positions now
```

Alpaca keys come from the environment (`Key`/`Secret`, or `ALPACA_API_KEY`/
`ALPACA_SECRET_KEY`). Never print them.

## Tuning (only what the user asks for)

Each bot reads optional overrides from a `settings.json` next to its state:
`trader/autobot/settings.json` (monthly) and `trader/orbbot/settings.json`
(intraday). Anything not set keeps the default in the code.

| bot | key | default | meaning |
| --- | --- | --- | --- |
| monthly | `budget` | 5000 | the sleeve the bot manages |
| monthly | `top_n` | 10 | how many stocks it holds |
| monthly | `cash_buffer_pct` | 10 | kept in cash |
| monthly | `max_drawdown_pct` | 15 | loss vs budget that sells everything |
| monthly | `max_position_pct`, `max_order_usd` | 15, 1000 | handed to trader-risk |
| intraday | `max_loss_per_trade_usd` | 50 | risk at the stop |
| intraday | `max_daily_loss_usd`, `max_trades_per_day` | 150, 3 | day limits |
| intraday | `min_mc_avg_r` | 0.05 | minimum average R in the 10,000 replays |
| intraday | `min_history_avg_r` | 0.0 | minimum average R on past sessions |
| intraday | `candidates` | 15 | latest breakouts it rates per run |

`trader/` is git-ignored, so a settings file written here does NOT reach the
scheduled cloud runs, which start from a fresh clone. For a change the
schedule must pick up, edit `DEFAULT_CONFIG` in the bot's file, commit and
push to the branch the schedule clones, and tell the user what changed.
Before any change, run the bot as a dry run and show the result.

Tuning is curve fitting unless it is checked on data the rule was not chosen
on. The monthly rule was picked on 2021-2024 and checked on 2025-2026; a
month or two of paper results is mostly noise. Say so before changing a rule
because of a few trades.

## The schedule

Two scheduled tasks (claude.ai routines) start a fresh cloud session, clone
`tatyanawaves/bisness` (branch `ccr-09243fdd-xh71s5`, or the default branch
once merged), run the bot with `--trade`, run `report.py`, and send a push
summary in Russian:

- `Paper autobot: monthly momentum (15:20 ET)`, cron `CRON_TZ=America/New_York 20 15 * * 1-5`
- `Paper ORB bot: intraday (hourly 9:55-15:55 ET)`, cron `CRON_TZ=America/New_York 55 9-15 * * 1-5`

To pause or resume, update the scheduled task (enabled false/true) when the
user asks. To stop one bot for good, disable its task AND, if it holds
anything, run its `--liquidate`/`--flatten` with `--trade`.

## What the backtests said (say it, do not oversell it)

- Monthly rule, top 10, 2025-01 to 2026-11 (held out): 34.9% a year vs SPY
  15.9% and an equal-weight universe 22.4%, max drawdown -18%. The universe was
  picked today, so winners are in it (survivorship bias); without the five
  biggest winners the 2021-2024 edge over equal weight disappeared.
- Entry timing for the monthly bot: buying on the Entry Timer's breakout was
  0.06% worse than at 10:20 on 307 past buys; a 15:25 buy was 0.10% cheaper.
  Timing inside the day barely matters for a month-long hold.
- Intraday breakouts on 2026-11-16: none of the 15 latest had a positive edge
  in both the replays and the history. Days without a trade are normal.

## Steps for "отчёт" / "report"

1. `python3 autobot/report.py`.
2. Show both rows: P/L in dollars and %, SPY over the same period, holdings.
3. If a bot has no fills yet, say when its next run is.
4. Never call a short paper result proof that a strategy works.

## Safety

- Education and tooling, not financial advice. Paper money only.
- Most people who day trade lose money; the intraday bot's limits keep each
  loss small, they do not make it win.
- Going live is the user's own decision and is not something these bots can do.
