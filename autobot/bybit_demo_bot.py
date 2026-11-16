#!/usr/bin/env python3
"""Bybit DEMO bot: BTC long/short by the 100-day average. Runs on YOUR computer.

Rule (checked on 2021-2026 daily data, see autobot/BYBIT_DEMO.md):
  once a week (Monday, UTC) look at yesterday's daily close of BTC/USDT:
    close above its 100-day average -> be LONG
    close below                      -> be SHORT
  position size = size_fraction x budget (default 0.5 x 10,000 USDT), leverage 1.

Hard rules, not settings:
  * Bybit DEMO TRADING only (api-demo.bybit.com). The bot switches ccxt to demo mode and
    exits if the endpoint is anything else. There is no flag for a real account.
  * Dry run unless --trade.
  * Kill switch: a STOP file in trader/bybit/, written automatically (after closing the
    position) when the account is down max_loss_usd from where the bot started.

Keys: environment variables BYBIT_DEMO_KEY / BYBIT_DEMO_SECRET, or the file
trader/bybit/.env (two lines, KEY=value). Create them in Bybit: switch to Demo Trading,
then API. Never paste keys into a chat.

    pip install ccxt
    python autobot/bybit_demo_bot.py              # dry run: shows what it would do
    python autobot/bybit_demo_bot.py --trade      # sends orders to the DEMO account
    python autobot/bybit_demo_bot.py --status     # position, P/L, last actions
    python autobot/bybit_demo_bot.py --close --trade   # close the position and stop
"""
import argparse, datetime as dt, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "trader", "bybit")
P = lambda name: os.path.join(DIR, name)
SYMBOL = "BTC/USDT:USDT"
DEFAULTS = {"budget": 10000, "size_fraction": 0.5, "sma_days": 100, "max_loss_usd": 2500,
            "rebalance_weekday": 0, "resize_tolerance": 0.25}


def log(event, **kw):
    kw.update(event=event, at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    with open(P("log.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(kw) + "\n")
    print("[%s] %s" % (event, json.dumps({k: v for k, v in kw.items() if k not in ("event", "at")})))


def load(name, default):
    try:
        with open(P(name), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save(name, obj):
    with open(P(name), "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


def keys():
    k, s = os.environ.get("BYBIT_DEMO_KEY"), os.environ.get("BYBIT_DEMO_SECRET")
    if not (k and s) and os.path.exists(P(".env")):
        for line in open(P(".env"), encoding="utf-8"):
            name, _, value = line.strip().partition("=")
            value = value.strip().strip('"').strip("'")
            if name.strip() == "BYBIT_DEMO_KEY":
                k = value
            elif name.strip() == "BYBIT_DEMO_SECRET":
                s = value
    if not (k and s):
        sys.exit("No demo keys. Set BYBIT_DEMO_KEY and BYBIT_DEMO_SECRET, or write them to %s" % P(".env"))
    return k, s


def connect():
    import ccxt
    k, s = keys()
    ex = ccxt.bybit({"apiKey": k, "secret": s, "enableRateLimit": True, "options": {"defaultType": "swap"}})
    ex.enable_demo_trading(True)
    urls = json.dumps(ex.urls.get("api"))
    if "api-demo" not in urls or "api.bybit.com" in urls or "api.bytick.com" in urls:
        sys.exit("Refusing to run: the exchange endpoint is not Bybit Demo Trading.")
    return ex


def signal(ex, sma_days):
    """+1 long / -1 short from the last COMPLETED daily bar."""
    bars = ex.fetch_ohlcv(SYMBOL, "1d", limit=sma_days + 5)
    today = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    done = [b for b in bars if b[0] < today.timestamp() * 1000]
    if len(done) < sma_days:
        raise RuntimeError("only %d daily bars, need %d" % (len(done), sma_days))
    closes = [b[4] for b in done[-sma_days:]]
    sma = sum(closes) / sma_days
    last = closes[-1]
    return (1 if last > sma else -1), last, sma, dt.datetime.fromtimestamp(done[-1][0] / 1000, dt.timezone.utc).date()


def account_equity(ex):
    bal = ex.fetch_balance({"type": "unified"})
    try:
        return float(bal["info"]["result"]["list"][0]["totalEquity"])
    except Exception:
        return float(bal["USDT"]["total"])


def position(ex):
    """Signed BTC amount: + long, - short, 0 flat."""
    for p in ex.fetch_positions([SYMBOL]):
        qty = float(p.get("contracts") or 0)
        if qty:
            return qty if p.get("side") == "long" else -qty
    return 0.0


def order(ex, delta, reduce_only, trade):
    """delta > 0 buys, delta < 0 sells (BTC)."""
    amount = float(ex.amount_to_precision(SYMBOL, abs(delta)))
    if amount <= 0:
        return None
    side = "buy" if delta > 0 else "sell"
    if not trade:
        log("would_order", side=side, amount=amount, reduce_only=reduce_only)
        return None
    o = ex.create_order(SYMBOL, "market", side, amount, None, {"reduceOnly": reduce_only})
    log("order", side=side, amount=amount, reduce_only=reduce_only, id=o.get("id"), status=o.get("status"))
    return o


def move_to(ex, current, target, trade):
    """Go from current to target signed amount; close first when the direction flips."""
    if current and (target == 0 or current * target < 0):
        order(ex, -current, True, trade)
        current = 0.0
    if target != current:
        order(ex, target - current, False, trade)


def main():
    ap = argparse.ArgumentParser(description="Bybit DEMO bot: BTC long/short by the 100-day average.")
    ap.add_argument("--trade", action="store_true", help="send orders to the DEMO account (default: dry run)")
    ap.add_argument("--status", action="store_true", help="show position and P/L, do nothing")
    ap.add_argument("--close", action="store_true", help="close the position and write STOP")
    a = ap.parse_args()
    os.makedirs(DIR, exist_ok=True)
    cfg = dict(DEFAULTS, **load("settings.json", {}))

    if os.path.exists(P("STOP")) and not (a.status or a.close):
        print("Bot is stopped: %s exists. Delete it to start again." % P("STOP"))
        return 0

    ex = connect()
    ex.load_markets()
    eq, pos = account_equity(ex), position(ex)
    state = load("state.json", None)
    if state is None:
        state = {"start_equity": eq, "started": dt.date.today().isoformat(), "last_rebalance": None}
        if a.trade:
            save("state.json", state)
    pnl = eq - state["start_equity"]
    sig, last, sma, as_of = signal(ex, cfg["sma_days"])
    log("status", equity=round(eq, 2), pnl_since_start=round(pnl, 2), position_btc=pos,
        signal="LONG" if sig > 0 else "SHORT", close=last, sma=round(sma, 2), bar=str(as_of), dry_run=not a.trade)
    if a.status:
        return 0

    if a.close or pnl <= -cfg["max_loss_usd"]:
        log("stopping", reason="--close" if a.close else "loss limit %s USDT reached" % cfg["max_loss_usd"])
        move_to(ex, pos, 0.0, a.trade)
        if a.trade:
            with open(P("STOP"), "w") as f:
                f.write("stopped %s\n" % dt.datetime.now().isoformat())
        return 0

    target = sig * cfg["budget"] * cfg["size_fraction"] / last
    week = dt.datetime.now(dt.timezone.utc).strftime("%G-W%V")
    is_day = dt.datetime.now(dt.timezone.utc).weekday() == cfg["rebalance_weekday"]
    flip = pos != 0 and pos * target < 0
    off_size = pos != 0 and abs(abs(pos) - abs(target)) / abs(target) > cfg["resize_tolerance"]

    if pos == 0:
        why = "first entry"
    elif (flip or off_size) and is_day and state.get("last_rebalance") != week:
        why = "weekly check: direction changed" if flip else "weekly check: size drifted"
    else:
        print("Holding %s %.4f BTC. Next check on the weekly rebalance day." % ("long" if pos > 0 else "short", abs(pos)))
        return 0

    try:
        if a.trade:
            ex.set_leverage(1, SYMBOL)
    except Exception as err:            # Bybit answers "leverage not modified" when it is already 1
        if "not modified" not in str(err).lower():
            log("leverage_warning", error=str(err)[:200])
    log("rebalance", why=why, from_btc=pos, to_btc=round(target, 6), notional_usdt=round(abs(target) * last, 2))
    move_to(ex, pos, target, a.trade)
    if a.trade:
        state["last_rebalance"] = week
        save("state.json", state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
