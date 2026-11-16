"""Offline tests for bybit_demo_bot.py with a fake exchange (Bybit is not called).

    python -m unittest autobot/test_bybit_demo_bot.py
"""
import datetime as dt, os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bybit_demo_bot as bot


class FakeExchange:
    def __init__(self, closes, equity=50000.0, pos=0.0):
        self.closes, self.equity, self.pos, self.orders = closes, equity, pos, []
        self.urls = {"api": {"private": "https://api-demo.bybit.com"}}

    def load_markets(self):
        pass

    def fetch_ohlcv(self, symbol, tf, limit=None):
        day0 = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        n = len(self.closes)                       # last element = today's unfinished bar
        return [[int((day0 - dt.timedelta(days=n - 1 - i)).timestamp() * 1000), c, c, c, c, 1]
                for i, c in enumerate(self.closes)]

    def fetch_balance(self, params=None):
        return {"info": {"result": {"list": [{"totalEquity": str(self.equity)}]}}, "USDT": {"total": self.equity}}

    def fetch_positions(self, symbols=None):
        if not self.pos:
            return []
        return [{"contracts": abs(self.pos), "side": "long" if self.pos > 0 else "short"}]

    def amount_to_precision(self, symbol, amount):
        return "%.3f" % (int(amount * 1000) / 1000)

    def set_leverage(self, lev, symbol):
        pass

    def create_order(self, symbol, typ, side, amount, price, params):
        self.orders.append((side, amount, params["reduceOnly"]))
        self.pos += amount if side == "buy" else -amount
        return {"id": str(len(self.orders)), "status": "closed"}


class BotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        bot.DIR = self.tmp.name
        self.argv = sys.argv

    def tearDown(self):
        sys.argv = self.argv
        self.tmp.cleanup()

    def run_bot(self, ex, *args):
        bot.connect = lambda: ex
        sys.argv = ["bot", *args]
        return bot.main()

    def test_first_entry_short_below_average(self):
        ex = FakeExchange([100.0] * 104 + [80.0, 999.0])       # yesterday 80 < SMA, today's bar ignored
        self.run_bot(ex, "--trade")
        self.assertEqual(ex.orders, [("sell", 62.5, False)])   # 0.5 * 10000 / 80
        self.assertLess(ex.pos, 0)

    def test_first_entry_long_above_average(self):
        ex = FakeExchange([100.0] * 104 + [125.0, 1.0])
        self.run_bot(ex, "--trade")
        self.assertEqual(ex.orders, [("buy", 40.0, False)])

    def test_dry_run_sends_nothing(self):
        ex = FakeExchange([100.0] * 104 + [80.0, 80.0])
        self.run_bot(ex)
        self.assertEqual(ex.orders, [])
        self.assertFalse(os.path.exists(bot.P("state.json")))

    def test_flip_only_on_rebalance_day_and_closes_first(self):
        ex = FakeExchange([100.0] * 104 + [125.0, 125.0], pos=-62.5)
        today = dt.datetime.now(dt.timezone.utc).weekday()
        bot.save("settings.json", {"rebalance_weekday": (today + 1) % 7})
        bot.save("state.json", {"start_equity": 50000.0, "started": "x", "last_rebalance": None})
        self.run_bot(ex, "--trade")
        self.assertEqual(ex.orders, [])                        # not the day: hold
        bot.save("settings.json", {"rebalance_weekday": today})
        self.run_bot(ex, "--trade")
        self.assertEqual(ex.orders, [("buy", 62.5, True), ("buy", 40.0, False)])
        self.run_bot(ex, "--trade")                            # same week: nothing more
        self.assertEqual(len(ex.orders), 2)

    def test_loss_limit_closes_and_stops(self):
        ex = FakeExchange([100.0] * 104 + [80.0, 80.0], equity=47000.0, pos=-62.5)
        bot.save("state.json", {"start_equity": 50000.0, "started": "x", "last_rebalance": None})
        self.run_bot(ex, "--trade")
        self.assertEqual(ex.orders, [("buy", 62.5, True)])
        self.assertTrue(os.path.exists(bot.P("STOP")))
        self.run_bot(ex, "--trade")                            # stopped: no new orders
        self.assertEqual(len(ex.orders), 1)

    def test_refuses_non_demo_endpoint(self):
        import types
        fake = types.SimpleNamespace(urls={"api": {"private": "https://api.bybit.com"}},
                                     enable_demo_trading=lambda on: None)
        ccxt = types.SimpleNamespace(bybit=lambda cfg: fake)
        sys.modules["ccxt"], old = ccxt, sys.modules.get("ccxt")
        os.environ["BYBIT_DEMO_KEY"], os.environ["BYBIT_DEMO_SECRET"] = "k", "s"
        try:
            with self.assertRaises(SystemExit):
                BOT_CONNECT()
        finally:
            if old:
                sys.modules["ccxt"] = old
            else:
                del sys.modules["ccxt"]
            del os.environ["BYBIT_DEMO_KEY"], os.environ["BYBIT_DEMO_SECRET"]


BOT_CONNECT = bot.connect      # the real connect(), kept before tests replace it

if __name__ == "__main__":
    unittest.main()
