#!/usr/bin/env python3
"""Side-by-side report of both paper bots, rebuilt from their own Alpaca orders.

    python3 autobot/report.py            # table
    python3 autobot/report.py --json
"""
import datetime as dt, json, os, sys

import paper_bot as core

BOTS = [("monthly momentum+reversal", "autobot-", 5000), ("intraday ORB + Entry Timer", "orbbot-", 5000)]


def spy_since(day):
    d = core.api("GET", core.DATA, "/v2/stocks/SPY/bars",
                 params={"timeframe": "1Day", "start": day, "feed": "sip", "adjustment": "all", "limit": 1000})
    bars = d.get("bars") or []
    last = core.last_prices(["SPY"]).get("SPY")
    return (last / bars[0]["o"] - 1) * 100 if bars and last else None


def main():
    core.DIR = os.path.join(core.ROOT, "trader", "report")
    os.makedirs(core.DIR, exist_ok=True)
    positions = core.api("GET", core.PAPER, "/v2/positions")
    out = []
    for name, prefix, budget in BOTS:
        st = core.rebuild_state(budget, prefix)
        held = core.bot_book(st, positions)
        eq = core.equity(st, held)
        fills = [o for o in st["orders"] if o.get("filled_avg_price")]
        first = min((o["submitted_at"][:10] for o in st["orders"]), default=None)
        out.append({"bot": name, "started": first, "equity": round(eq, 2), "pnl": round(eq - budget, 2),
                    "return_pct": round((eq / budget - 1) * 100, 2), "fills": len(fills),
                    "holdings": {s: round(h["value"], 2) for s, h in held.items()},
                    "spy_return_pct": round(spy_since(first), 2) if first else None})
    if "--json" in sys.argv:
        print(json.dumps(out, indent=2))
        return
    print("Paper bots, %s" % dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    for r in out:
        spy = "" if r["spy_return_pct"] is None else "   SPY same period %+.2f%%" % r["spy_return_pct"]
        print("%-28s since %-10s equity $%9.2f  P/L $%+8.2f (%+.2f%%)  fills %d%s"
              % (r["bot"], r["started"] or "-", r["equity"], r["pnl"], r["return_pct"], r["fills"], spy))
        for s, v in sorted(r["holdings"].items()):
            print("    %-6s $%9.2f" % (s, v))


if __name__ == "__main__":
    main()
