#!/usr/bin/env python3
"""Paper-only autobot for the momentum + reversal strategy.

Strategy (backtested 2021-2026 on ~98 US large caps, see autobot/README.md):
  score = rank(12-1 month momentum) + rank(5-day reversal)
  keep only stocks above their 200-day average, and only while SPY is above its own
  buy the top N (default 10) with equal weights, rebalance once a month.

Hard rules, not settings:
  * Talks ONLY to https://paper-api.alpaca.markets. There is no flag for a live account.
  * Every order goes through trader-risk (check.py) with the bot's own config; only PASS is sent.
  * Kill switch: the file trader/autobot/STOP stops every run. A loss of
    max_drawdown_pct against the starting budget sells everything (and writes STOP).
  * No local state: holdings, cash and the last rebalance month are rebuilt from the
    bot's own Alpaca orders (client_order_id "autobot-...") on every run.
  * Default is a dry run. --trade is needed to send orders.

Standard library only. Keys from env: Key/Secret (or ALPACA_API_KEY/ALPACA_SECRET_KEY).
"""
import argparse, datetime as dt, json, math, os, subprocess, sys, time, urllib.parse, urllib.request

PAPER = "https://paper-api.alpaca.markets"   # hard-coded on purpose
DATA = "https://data.alpaca.markets"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "trader", "autobot")
CHECK = os.path.join(ROOT, ".claude", "skills", "trader-risk", "check.py")
P = lambda name: os.path.join(DIR, name)

UNIVERSE = ("AAPL MSFT NVDA AMZN GOOGL META AVGO TSLA BRK.B JPM V MA UNH XOM JNJ PG HD COST ABBV MRK "
            "LLY PEP KO WMT BAC CVX ORCL CRM AMD ADBE NFLX CSCO INTC QCOM TXN AMAT MU LRCX KLAC PANW "
            "NOW INTU IBM GE CAT DE HON LMT RTX BA UNP UPS GS MS AXP C WFC BLK SCHW SPGI TMO ABT DHR "
            "ISRG AMGN GILD VRTX REGN PFE BMY MDT SYK CI ELV MCD SBUX NKE LOW TJX BKNG DIS CMCSA T VZ "
            "TMUS NEE DUK SO LIN COP SLB EOG PLD AMT ANET UBER PLTR CRWD").split()

DEFAULT_CONFIG = {
    "budget": 5000, "top_n": 10, "cash_buffer_pct": 10, "max_drawdown_pct": 15,
    "rebalance_min_usd": 25,
    # limits handed to trader-risk for the bot's orders
    "max_position_pct": 15, "max_order_usd": 1000, "min_order_usd": 5,
    "max_trades_per_day": 25, "max_orders_per_day": 30, "require_stop": False,
    "max_loss_per_trade_usd": 1000000, "max_daily_loss_usd": 1000000, "min_reward_risk": 0,
    "no_entries_before": "09:45", "no_entries_after": "15:30",
    "fractional": True, "broker": "alpaca", "paper": True, "blocked": [],
    "allow_options": False, "allow_margin": False, "allow_short": False, "pdt_guard": False,
}


def log(event, **kw):
    kw.update(event=event, at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    with open(P("log.jsonl"), "a") as f:
        f.write(json.dumps(kw) + "\n")
    print("[%s] %s" % (event, json.dumps({k: v for k, v in kw.items() if k not in ("event", "at")})))


def load(name, default):
    try:
        with open(P(name)) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save(name, obj):
    tmp = P(name) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
    os.replace(tmp, P(name))


def headers():
    k = os.environ.get("ALPACA_API_KEY") or os.environ.get("Key")
    s = os.environ.get("ALPACA_SECRET_KEY") or os.environ.get("Secret")
    if not k or not s:
        sys.exit("No Alpaca keys in the environment (Key/Secret or ALPACA_API_KEY/ALPACA_SECRET_KEY).")
    return {"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s, "Content-Type": "application/json"}


def api(method, base, path, body=None, params=None):
    url = base + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, data=data, method=method, headers=headers())
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError("%s %s -> %s %s" % (method, path, e.code, e.read()[:300]))


# ---------------------------------------------------------------- signals
def daily_closes(symbols, days=420):
    end = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    start = (dt.date.today() - dt.timedelta(days=int(days * 1.5))).isoformat()
    out = {}
    for i in range(0, len(symbols), 25):
        params = {"symbols": ",".join(symbols[i:i + 25]), "timeframe": "1Day", "start": start, "end": end,
                  "feed": "sip", "adjustment": "all", "limit": 10000}
        while True:
            d = api("GET", DATA, "/v2/stocks/bars", params=params)
            for s, bars in (d.get("bars") or {}).items():
                out.setdefault(s, []).extend((b["t"][:10], b["c"]) for b in bars)
            if not d.get("next_page_token"):
                break
            params["page_token"] = d["next_page_token"]
    today = dt.date.today().isoformat()   # drop today's unfinished bar
    return {s: [x for x in v if x[0] < today] for s, v in out.items()}


def pct_rank(values):
    order = sorted(values, key=values.get)
    n = len(order)
    return {s: (i + 1) / n for i, s in enumerate(order)}


def signals(top_n):
    closes = daily_closes(UNIVERSE + ["SPY"])
    spy = [c for _, c in closes.pop("SPY")]
    market_ok = len(spy) >= 200 and spy[-1] > sum(spy[-200:]) / 200
    mom, rev, info = {}, {}, {}
    for s, rows in closes.items():
        c = [x[1] for x in rows]
        if len(c) < 253:
            continue
        if c[-1] <= sum(c[-200:]) / 200:          # trend filter
            continue
        mom[s] = c[-22] / c[-253] - 1             # 12-1 month momentum
        rev[s] = -(c[-1] / c[-6] - 1)             # 5-day reversal
        info[s] = {"close": c[-1], "as_of": rows[-1][0]}
    if not market_ok or not mom:
        return market_ok, [], info
    rm, rr = pct_rank(mom), pct_rank(rev)
    score = {s: rm[s] + rr[s] for s in mom}
    picks = sorted(score, key=score.get, reverse=True)[:top_n]
    for s in picks:
        info[s].update(score=round(score[s], 3), mom12_1=round(mom[s], 4), rev5=round(rev[s], 4))
    return market_ok, picks, info


# ---------------------------------------------------------------- portfolio
def rebuild_state(budget):
    """Everything the bot needs, rebuilt from its own Alpaca orders (client_order_id 'autobot-...').
    A cloud run starts from an empty disk, so nothing is kept locally between runs."""
    orders, after = [], "2026-01-01T00:00:00Z"
    while True:
        page = api("GET", PAPER, "/v2/orders", params={"status": "all", "limit": 500, "direction": "asc",
                                                         "after": after})
        mine = [o for o in page if (o.get("client_order_id") or "").startswith("autobot-")]
        orders += mine
        if len(page) < 500:
            break
        after = page[-1]["submitted_at"]
    cash, symbols, months, today = float(budget), set(), set(), []
    for o in orders:
        months.add(o["client_order_id"].split("-")[1])
        if o["submitted_at"][:10] == dt.date.today().isoformat():
            today.append({"date": o["submitted_at"][:10], "symbol": o["symbol"], "side": o["side"],
                          "status": "placed", "broker_id": o["id"]})
        if o["status"] not in ("filled", "partially_filled") or not o.get("filled_avg_price"):
            continue
        v = float(o["filled_qty"]) * float(o["filled_avg_price"])
        if o["side"] == "buy":
            cash -= v
            symbols.add(o["symbol"])
        else:
            cash += v
    save("broker.json", {"entries": today})
    return {"cash": cash, "symbols": sorted(symbols), "months": sorted(months), "orders": len(orders)}


def bot_book(state, positions):
    """The bot's holdings = Alpaca positions in symbols the bot bought (exact broker qty)."""
    held = {}
    for p in positions:
        s = p["symbol"]
        if s in state["symbols"]:
            held[s] = {"qty": float(p["qty"]), "price": float(p["current_price"]),
                       "value": float(p["market_value"])}
    return held


def equity(state, held):
    return state["cash"] + sum(h["value"] for h in held.values())


def run_risk(orders, held, prices, cfg, cash):
    save("orders.json", {"source": "autobot", "orders": orders})
    save("portfolio.json", {"cash": round(cash, 2),
                            "positions": [{"ticker": s, "shares": h["qty"]} for s, h in held.items()]})
    save("prices.json", {"as_of": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                         "source": "alpaca", "prices": prices,
                         "detail": {s: {"fetched": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
                                    for s in prices}})
    save("config.json", cfg)
    r = subprocess.run([sys.executable, CHECK, "--json", "--out", P("risk.json"), "--orders", P("orders.json"), "--config", P("config.json"),
                        "--portfolio", P("portfolio.json"), "--prices", P("prices.json"),
                        "--state", P("broker.json")], capture_output=True, text=True, cwd=ROOT)
    try:
        return json.loads(r.stdout)["results"]
    except Exception:
        raise RuntimeError("trader-risk did not answer: " + (r.stdout + r.stderr)[-400:])


def place(order):
    body = {k: v for k, v in order.items() if k in ("symbol", "side", "qty", "notional", "type", "time_in_force")}
    body["client_order_id"] = "autobot-%s-%s-%s-%d" % (dt.date.today().strftime("%Y%m"), order["symbol"],
                                                       order["side"], int(time.time() * 1000))
    o = api("POST", PAPER, "/v2/orders", body)
    for _ in range(20):
        o = api("GET", PAPER, "/v2/orders/" + o["id"])
        if o["status"] in ("filled", "canceled", "rejected", "expired"):
            break
        time.sleep(3)
    return o


def record(state, order, o):
    if o["status"] != "filled":
        return
    qty, px = float(o["filled_qty"]), float(o["filled_avg_price"])
    if order["side"] == "buy":
        state["cash"] -= qty * px
        state["symbols"] = sorted(set(state["symbols"]) | {order["symbol"]})
    else:
        state["cash"] += qty * px
    broker = load("broker.json", {"entries": []})
    broker.setdefault("entries", []).append({"date": dt.date.today().isoformat(), "symbol": order["symbol"],
                                             "side": order["side"], "status": "placed", "broker_id": o["id"]})
    save("broker.json", broker)


def execute(orders, state, cfg, trade):
    """Risk-check the batch, then send each PASS order (sells first). Returns count sent."""
    positions = api("GET", PAPER, "/v2/positions")
    held = bot_book(state, positions)
    prices = {o["symbol"]: o["_price"] for o in orders}
    prices.update({s: h["price"] for s, h in held.items()})
    clean = [{k: v for k, v in o.items() if not k.startswith("_")} for o in orders]
    verdicts = run_risk(clean, held, prices, cfg, state["cash"])
    sent = 0
    for order, v in zip(clean, verdicts):
        if v["verdict"] != "PASS":
            log("blocked", symbol=order["symbol"], side=order["side"], reasons=v["reasons"])
            continue
        if not trade:
            log("would_place", order=order)
            continue
        o = place(order)
        record(state, order, o)
        log("placed", symbol=order["symbol"], side=order["side"], status=o["status"],
            qty=o.get("filled_qty"), price=o.get("filled_avg_price"), id=o["id"])
        sent += 1
    return sent


def main():
    ap = argparse.ArgumentParser(description="Paper-only momentum+reversal autobot.")
    ap.add_argument("--trade", action="store_true", help="send orders to the PAPER account (default: dry run)")
    ap.add_argument("--force-rebalance", action="store_true", help="rebalance now even if done this month")
    ap.add_argument("--liquidate", action="store_true", help="sell everything the bot holds and stop")
    a = ap.parse_args()
    os.makedirs(DIR, exist_ok=True)

    if os.path.exists(P("STOP")) and not a.liquidate:
        print("Autobot is stopped: %s exists. Delete it to start again." % P("STOP"))
        return 0

    cfg = dict(DEFAULT_CONFIG, **load("settings.json", {}))
    cfg["paper"] = True
    acct = api("GET", PAPER, "/v2/account")
    if not acct.get("account_number", "").startswith("PA"):
        sys.exit("Refusing to run: this is not an Alpaca paper account.")
    clock = api("GET", PAPER, "/v2/clock")
    state = rebuild_state(cfg["budget"])
    held = bot_book(state, api("GET", PAPER, "/v2/positions"))
    eq = equity(state, held)
    dd = eq / cfg["budget"] - 1          # loss vs the starting budget
    log("status", market_open=clock["is_open"], equity=round(eq, 2), budget=cfg["budget"],
        return_pct=round(dd * 100, 2), cash=round(state["cash"], 2), holdings=sorted(held),
        pnl=round(eq - cfg["budget"], 2), dry_run=not a.trade)

    if not clock["is_open"]:
        print("Market closed; next open %s. Nothing to do." % clock["next_open"])
        return 0

    sells_all = a.liquidate or dd <= -cfg["max_drawdown_pct"] / 100
    if sells_all:
        orders = [{"symbol": s, "side": "sell", "qty": "%.9f" % h["qty"], "type": "market",
                   "time_in_force": "day", "_price": h["price"]} for s, h in held.items()]
        log("liquidate", reason="--liquidate" if a.liquidate else "drawdown %.1f%%" % (dd * 100))
        execute(orders, state, cfg, a.trade)
        if a.trade:
            open(P("STOP"), "w").write("stopped %s\n" % dt.datetime.now().isoformat())
        return 0

    month = dt.date.today().strftime("%Y%m")
    if month in state["months"] and not a.force_rebalance:
        print("Already rebalanced in %s. Holding." % month)
        return 0

    market_ok, picks, info = signals(cfg["top_n"])
    log("signals", market_ok=market_ok, picks=picks,
        detail={s: info[s] for s in picks})
    invest = eq * (1 - cfg["cash_buffer_pct"] / 100)
    target = {s: invest / len(picks) for s in picks} if picks else {}
    price = lambda s: held[s]["price"] if s in held else info.get(s, {}).get("close")

    sells, buys = [], []
    for s, h in held.items():
        diff = target.get(s, 0) - h["value"]
        if s not in target:
            sells.append({"symbol": s, "side": "sell", "qty": "%.9f" % h["qty"], "type": "market",
                          "time_in_force": "day", "_price": h["price"]})
        elif diff < -cfg["rebalance_min_usd"]:
            q = min(h["qty"], -diff / h["price"])
            sells.append({"symbol": s, "side": "sell", "qty": "%.9f" % q, "type": "market",
                          "time_in_force": "day", "_price": h["price"]})
    for s, t in target.items():
        diff = t - (held[s]["value"] if s in held else 0)
        if diff > cfg["rebalance_min_usd"]:
            buys.append({"symbol": s, "side": "buy", "notional": "%.2f" % (math.floor(diff * 100) / 100), "type": "market", "time_in_force": "day",
                         "_price": price(s)})

    if sells:
        execute(sells, state, cfg, a.trade)
    if buys:
        execute(buys, state, cfg, a.trade)
    log("done", sells=len(sells), buys=len(buys), dry_run=not a.trade)
    return 0


if __name__ == "__main__":
    sys.exit(main())
