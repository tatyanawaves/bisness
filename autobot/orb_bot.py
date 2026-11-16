#!/usr/bin/env python3
"""Paper-only intraday bot: opening-range breakout timed by the Entry Timer.

One run does whatever fits the New York clock:
  09:50-15:30  look for ONE new entry:
               trader-scanner (orb)  -> charts that closed above their 9:30-9:45 range high
               trader-entry          -> still above the range high now (a breakout that held)
               trader-exit           -> stop at the range midpoint, target 2R, flat by 15:55
               trader-timemachine    -> 10,000 replays + the same rule on ~60 past sessions;
                                        only trades with a positive edge in BOTH go on
               trader-budget         -> whole shares inside max loss / position / cash limits
               trader-risk           -> PASS or nothing is sent
               Alpaca paper          -> ONE bracket order (entry + stop-loss + take-profit)
  15:45-16:00  flatten: cancel the bot's open legs and sell what it still holds.

Hard rules, not settings: paper endpoint only, every order through trader-risk with the
bot's own limits (default $50 max loss a trade, $150 a day, 3 trades a day), a STOP file
stops it, dry run unless --trade. Holdings and P/L are rebuilt from its own Alpaca orders
(client_order_id "orbbot-...") on every run, so it runs from a fresh cloud session.
"""
import argparse, datetime as dt, json, os, subprocess, sys, time
from zoneinfo import ZoneInfo

import paper_bot as core

core.DIR = os.path.join(core.ROOT, "trader", "orbbot")
P, api, PAPER, log, save, load = core.P, core.api, core.PAPER, core.log, core.save, core.load
SK = os.path.join(core.ROOT, ".claude", "skills")
NY = ZoneInfo("America/New_York")
PREFIX = "orbbot-"

DEFAULT_CONFIG = {
    "budget": 5000, "cash_buffer_pct": 10, "max_position_pct": 75, "max_order_usd": 4000, "min_order_usd": 5,
    "max_loss_per_trade_usd": 50, "max_daily_loss_usd": 150, "max_trades_per_day": 3, "max_orders_per_day": 10,
    "min_reward_risk": 1.0, "require_stop": True, "no_entries_before": "09:45", "no_entries_after": "15:30",
    "flat_by": "15:55", "fractional": False, "broker": "alpaca", "paper": True, "blocked": [],
    "allow_options": False, "allow_margin": False, "allow_short": False, "pdt_guard": False,
    # bot-only filters
    "candidates": 15, "min_mc_avg_r": 0.05, "min_history_avg_r": 0.0, "max_confirm": 200,
}


def tool(*args, timeout=600):
    r = subprocess.run([sys.executable, *args], capture_output=True, text=True, cwd=core.ROOT, timeout=timeout)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"_err": (r.stdout + r.stderr)[-400:]}


def entry_time_label(bar_start):
    h, m = map(int, bar_start.split(":"))
    m += 5
    h, m = h + m // 60, m % 60
    return "%d:%02d %s" % (h if h <= 12 else h - 12, m, "AM" if h < 12 else "PM")


def evaluate(sym, cfg):
    """Entry Timer -> Exit Planner -> Time Machine for one chart. Returns a dict or None."""
    e = tool(f"{SK}/trader-entry/entry.py", "check", sym, "--json")
    if e.get("status") != "triggered":
        return None
    orr, last = e["opening_range"], e["last"]
    if last["close"] <= orr["high"]:
        return {"symbol": sym, "skip": "back under the range high"}
    plan_path = P("plan-%s.json" % sym)
    pl = tool(f"{SK}/trader-exit/exit.py", "plan", "--symbol", sym, "--entry", "%.2f" % last["close"],
              "--or-high", str(orr["high"]), "--or-low", str(orr["low"]), "--time", entry_time_label(last["bar_start"]),
              "--config", P("config.json"), "--json", "--write", plan_path)
    if "_err" in pl:
        return {"symbol": sym, "skip": "exit planner: " + pl["_err"][-120:]}
    tm = tool(f"{SK}/trader-timemachine/timemachine.py", "run", "--plan", plan_path, "--until", cfg["flat_by"],
              "--json")
    if "_err" in tm:
        return {"symbol": sym, "skip": "time machine: " + tm["_err"][-120:]}
    mc, hist = tm["mc"], tm.get("history", {})
    return {"symbol": sym, "plan": plan_path, "entry": tm["plan"]["entry"], "stop": tm["plan"]["stop"],
            "target": tm["plan"]["target"], "p_target": mc["p_target"], "p_stop": mc["p_stop"],
            "mc_avg_r": mc["avg_R"], "hist_avg_r": hist.get("avg_R"), "hist_n": hist.get("triggered"),
            "verdict": tm.get("verdict")}


def flatten(state, trade):
    open_orders = [o for o in state["orders"] if o["status"] in ("new", "accepted", "held", "partially_filled",
                                                                   "pending_new")]
    for o in open_orders:
        log("cancel", symbol=o["symbol"], id=o["id"], dry_run=not trade)
        if trade:
            try:
                api("DELETE", PAPER, "/v2/orders/" + o["id"])
            except RuntimeError as err:
                log("cancel_failed", id=o["id"], error=str(err)[:200])
    if trade and open_orders:
        time.sleep(3)
    for sym, q in state["qty"].items():
        if q <= 0:
            continue
        order = {"symbol": sym, "side": "sell", "qty": "%g" % q, "type": "market", "time_in_force": "day"}
        if not trade:
            log("would_flatten", order=order)
            continue
        o = send(order)
        log("flattened", symbol=sym, status=o["status"], qty=o.get("filled_qty"), price=o.get("filled_avg_price"))


def send(order, extra=None):
    body = {k: v for k, v in order.items() if k in ("symbol", "side", "qty", "notional", "type", "time_in_force",
                                                    "order_class")}
    if order.get("order_class") == "bracket":
        body["take_profit"] = {"limit_price": order["take_profit_limit_price"]}
        body["stop_loss"] = {"stop_price": order["stop_loss_stop_price"]}
    body["client_order_id"] = "%s%s-%s-%s-%d" % (PREFIX, dt.date.today().strftime("%Y%m"), order["symbol"],
                                                 order["side"], int(time.time() * 1000))
    o = api("POST", PAPER, "/v2/orders", body)
    for _ in range(20):
        o = api("GET", PAPER, "/v2/orders/" + o["id"])
        if o["status"] in ("filled", "canceled", "rejected", "expired"):
            break
        time.sleep(3)
    return o


def main():
    ap = argparse.ArgumentParser(description="Paper-only intraday opening-range breakout bot.")
    ap.add_argument("--trade", action="store_true", help="send orders to the PAPER account (default: dry run)")
    ap.add_argument("--flatten", action="store_true", help="close everything the bot holds now")
    a = ap.parse_args()
    os.makedirs(core.DIR, exist_ok=True)
    if os.path.exists(P("STOP")):
        print("orb bot is stopped: %s exists." % P("STOP"))
        return 0
    cfg = dict(DEFAULT_CONFIG, **load("settings.json", {}))
    cfg["paper"] = True
    save("config.json", cfg)

    acct = api("GET", PAPER, "/v2/account")
    if not acct.get("account_number", "").startswith("PA"):
        sys.exit("Refusing to run: this is not an Alpaca paper account.")
    clock = api("GET", PAPER, "/v2/clock")
    state = core.rebuild_state(cfg["budget"], PREFIX)
    held = core.bot_book(state, api("GET", PAPER, "/v2/positions"))
    eq = core.equity(state, held)
    log("status", market_open=clock["is_open"], equity=round(eq, 2), pnl=round(eq - cfg["budget"], 2),
        cash=round(state["cash"], 2), holdings={s: h["qty"] for s, h in held.items()}, dry_run=not a.trade)
    if not clock["is_open"]:
        print("Market closed; next open %s." % clock["next_open"])
        return 0

    now = dt.datetime.now(NY).strftime("%H:%M")
    if a.flatten or now >= "15:45":
        flatten(state, a.trade)
        return 0
    if not ("09:50" <= now < cfg["no_entries_after"]):
        print("Outside the entry window (%s ET)." % now)
        return 0

    # ---- 1. Chart Scanner
    if not os.path.exists(os.path.join(core.ROOT, "trader", "universe.txt")):
        tool(f"{SK}/trader-scanner/scan.py", "universe")
    scan = tool(f"{SK}/trader-scanner/scan.py", "orb", "--json", "--no-write", "--quiet",
                "--max-confirm", str(cfg["max_confirm"]), timeout=900)
    hits = scan.get("hits", [])
    monthly = core.rebuild_state(0, "autobot-")["qty"]          # never trade what the monthly bot holds
    hits = [h for h in hits if h["symbol"] not in monthly and h["symbol"] not in state["qty"]]
    hits.sort(key=lambda h: -h.get("bar_index", 0))             # latest breakouts are closest to the price now
    log("scan", as_of=scan.get("as_of"), scanned=scan.get("scanned"), hits=len(scan.get("hits", [])),
        candidates=[h["symbol"] for h in hits[:cfg["candidates"]]])

    # ---- 2-4. Entry Timer -> Exit Planner -> Time Machine
    rated = []
    for h in hits[:cfg["candidates"]]:
        r = evaluate(h["symbol"], cfg)
        if r:
            rated.append(r)
    good = [r for r in rated if "skip" not in r and r["mc_avg_r"] >= cfg["min_mc_avg_r"]
            and (r["hist_avg_r"] or -1) > cfg["min_history_avg_r"]]
    good.sort(key=lambda r: -r["mc_avg_r"])
    log("rated", rated=[{k: r.get(k) for k in ("symbol", "skip", "mc_avg_r", "hist_avg_r", "p_target", "p_stop")}
                        for r in rated], passed_filter=[r["symbol"] for r in good])
    if not good:
        print("No breakout with a positive edge right now. No trade.")
        return 0
    pick = good[0]

    # ---- 5. Budget Manager (bot's own cash and prices)
    px = core.last_prices([pick["symbol"]] + list(held))
    save("prices.json", {"as_of": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "source": "alpaca",
                         "prices": px, "detail": {s: {"fetched": dt.datetime.now(dt.timezone.utc)
                                                      .isoformat(timespec="seconds")} for s in px}})
    save("portfolio.json", {"cash": round(state["cash"], 2),
                            "positions": [{"ticker": s, "shares": h["qty"]} for s, h in held.items()]})
    sized = tool(f"{SK}/trader-budget/size.py", "--plan", pick["plan"], "--config", P("config.json"),
                 "--portfolio", P("portfolio.json"), "--prices", P("prices.json"), "--json",
                 "--write", P("orders.json"))
    orders = load("orders.json", {}).get("orders", [])
    if not orders:
        log("not_sized", symbol=pick["symbol"], detail=str(sized)[:300])
        return 0

    # ---- 6. Risk Manager
    risk = tool(f"{SK}/trader-risk/check.py", "--json", "--orders", P("orders.json"), "--config", P("config.json"),
                "--portfolio", P("portfolio.json"), "--prices", P("prices.json"), "--state", P("broker.json"),
                "--out", P("risk.json"))
    v = (risk.get("results") or [{}])[0]
    if v.get("verdict") != "PASS":
        log("blocked", symbol=pick["symbol"], reasons=v.get("reasons") or risk.get("_err"))
        return 0

    # ---- 7. Order Executor (paper, bracket)
    order = orders[0]
    if not a.trade:
        log("would_place", order={k: order[k] for k in order if k not in ("why", "plan")}, edge=pick)
        return 0
    o = send(order)
    log("placed", symbol=order["symbol"], qty=order["qty"], stop=order["stop_loss_stop_price"],
        target=order["take_profit_limit_price"], status=o["status"], price=o.get("filled_avg_price"), id=o["id"],
        mc_avg_r=pick["mc_avg_r"], hist_avg_r=pick["hist_avg_r"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
