import traceback
import sys
from types import ModuleType

# --- TWISTED MOCK: Bypasses C-Compiler Crashes on Android ---
class MockModule(ModuleType):
    def __getattr__(self, name):
        return MockModule(name)

# Create distinct dummy classes to prevent duplicate base class collisions
class DummyReconnectingFactory: pass
class DummyWSFactory: pass
class DummyWSProtocol: pass

sys.modules['twisted'] = MockModule('twisted')
sys.modules['twisted.internet'] = MockModule('twisted.internet')
sys.modules['twisted.internet.protocol'] = MockModule('twisted.internet.protocol')
sys.modules['twisted.internet.protocol'].ReconnectingClientFactory = DummyReconnectingFactory
sys.modules['twisted.python'] = MockModule('twisted.python')

sys.modules['autobahn'] = MockModule('autobahn')
sys.modules['autobahn.twisted'] = MockModule('autobahn.twisted')
sys.modules['autobahn.twisted.websocket'] = MockModule('autobahn.twisted.websocket')
sys.modules['autobahn.twisted.websocket'].WebSocketClientProtocol = DummyWSProtocol
sys.modules['autobahn.twisted.websocket'].WebSocketClientFactory = DummyWSFactory
sys.modules['autobahn.twisted.websocket'].connectWS = lambda *args, **kwargs: None
# -----------------------------------------------------------

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.core.window import Window
from kivy.clock import Clock

CRASH_ERROR = ""
SUCCESS_LOAD = False

try:
    import csv, datetime, io, json, logging, math, os, random, re, threading, time, urllib.parse, webbrowser
    from flask import Flask, jsonify, render_template_string, request
    from kiteconnect import KiteTicker
    import pytz
    import requests
    import websocket
    
    try:
        import nest_asyncio
        nest_asyncio.apply()
    except Exception:
        pass

    IST = pytz.timezone("Asia/Kolkata")
    stealth_ws = None
    EVENT_LOG = []
    SYSTEM_START_TIME = time.time()
    FLASK_PORT = random.randint(6000, 9000)

    API_CONFIG = {"user_id": "", "enc_token": "", "is_connected": False}
    KITE_SESSION = requests.Session()
    DIAGNOSTICS = {
        "ws_status": "DISCONNECTED",
        "rest_history_status": "WAITING",
        "last_rest_ping": "N/A",
    }

    def log_event(msg):
        ts = datetime.datetime.now(IST).strftime("%H:%M:%S")
        EVENT_LOG.append(f"[{ts}] {msg}")
        if len(EVENT_LOG) > 20:
            EVENT_LOG.pop(0)

    RISK_CONFIG = {
        "target_pnl": 1000.0,
        "stoploss_pnl": -500.0,
        "auto_squareoff": False,
        "panic_exit": False,
        "protection_buffer_pct": 0.5,
        "tsl_enabled": False,
        "tsl_gap": 200.0,
        "time_exit_enabled": False,
        "time_exit_target": "15:25:00",
    }

    STRATEGY_CONFIG = {
        "armed": False,
        "fired": False,
        "leg_prot_pct": 2.0,
        "risk_free_rate": 7.0,
        "use_premium_cond": False,
        "prem_gate": "AND",
        "condition": ">=",
        "target_premium": 150.0,
        "use_diff_cond": False,
        "diff_gate": "AND",
        "diff_target": 5.0,
        "use_vwap_cond": False,
        "vwap_gate": "AND",
        "vwap_direction": "<",
        "use_time_cond": False,
        "time_gate": "AND",
        "target_time": "09:15:00",
        "use_underlying_cond": False,
        "und_ltp_gate": "AND",
        "und_cond": ">=",
        "und_target": 22000.0,
        "use_und_vwap_cond": False,
        "und_vwap_gate": "AND",
        "und_vwap_dir": ">",
        "use_iv_cond": False,
        "iv_gate": "AND",
        "iv_cond": ">=",
        "iv_target": 15.0,
        "master_und_exch": "",
        "master_und_sym": "",
        "master_und_token": None,
    }

    STRATEGY_LEGS, INSTRUMENT_MAP, TOKEN_EXPIRY_MAP = [], {}, {}
    GLOBAL_EXPIRIES, GLOBAL_INSTRUMENT_META, GLOBAL_SYMBOL_MAP = {}, {}, {}
    ACTIVE_POSITIONS, LIVE_PNLS = {}, {}
    ORDER_FIRED = False
    CURRENT_ACTIVE_SL = None
    LIVE_LEG_PRICES, LIVE_LEG_VWAP, LIVE_LEG_DEPTH = {}, {}, {}
    (
        CURRENT_COMBO_PREMIUM,
        CURRENT_COMBO_VWAP,
        CURRENT_GAP,
        NET_PORTFOLIO_PNL,
        CURRENT_PREM_DIFF,
    ) = (0.0, 0.0, 0.0, 0.0, 0.0)
    LIVE_MASTER_UND_LTP, LIVE_MASTER_UND_VWAP, CURRENT_COMBO_IV = 0.0, 0.0, 0.0

    (
        CHART_LABELS,
        CHART_PREMIUM,
        CHART_IV,
        CHART_VWAP,
        CHART_MASTER,
        CHART_PNL,
        CHART_MEAN,
    ) = ([], [], [], [], [], [], [])
    CHART_LEGS = {}
    LAST_CHART_UPDATE = 0
    LEG_ENTRY_SNAPSHOTS = {}

    def reset_chart():
        global CHART_LABELS, CHART_PREMIUM, CHART_IV, CHART_VWAP, CHART_MASTER, CHART_LEGS, CHART_PNL, CHART_MEAN, LAST_CHART_UPDATE
        CHART_LABELS.clear()
        CHART_PREMIUM.clear()
        CHART_IV.clear()
        CHART_VWAP.clear()
        CHART_MASTER.clear()
        CHART_PNL.clear()
        CHART_LEGS.clear()
        CHART_MEAN.clear()
        LAST_CHART_UPDATE = time.time()

    def fetch_instrument_tokens():
        global INSTRUMENT_MAP, TOKEN_EXPIRY_MAP, GLOBAL_EXPIRIES, GLOBAL_INSTRUMENT_META, GLOBAL_SYMBOL_MAP
        log_event("Downloading Master Instrument Database...")
        while True:
            try:
                headers = {"User-Agent": "Mozilla/5.0"}
                req = requests.get(
                    "https://api.kite.trade/instruments", headers=headers, timeout=15
                )
                reader = csv.DictReader(io.StringIO(req.text))

                t_INSTRUMENT_MAP, t_TOKEN_EXPIRY_MAP = {}, {}
                t_GLOBAL_EXPIRIES, t_GLOBAL_INSTRUMENT_META, t_GLOBAL_SYMBOL_MAP = (
                    {},
                    {},
                    {},
                )

                for row in reader:
                    name = row.get("name", "").strip()
                    if not name:
                        continue

                    exch = row.get("exchange", "")
                    tsym = row.get("tradingsymbol", "")
                    try:
                        token = int(row.get("instrument_token", 0))
                    except Exception:
                        continue

                    exp_raw = row.get("expiry", "")
                    exp_str = exp_raw.split(" ")[0] if exp_raw else ""

                    try:
                        strike_val = float(row.get("strike", 0.0))
                    except Exception:
                        strike_val = 0.0

                    opt_val = str(row.get("instrument_type", ""))
                    if "CE" in opt_val:
                        opt_val = "CE"
                    elif "PE" in opt_val:
                        opt_val = "PE"
                    elif "FUT" in opt_val:
                        opt_val = "FUT"
                    else:
                        opt_val = "EQ"

                    t_INSTRUMENT_MAP[f"{exch}:{tsym}"] = token
                    t_TOKEN_EXPIRY_MAP[token] = exp_raw

                    sym_key = f"{exch}|{name}|{exp_str}|{strike_val}|{opt_val}"
                    t_GLOBAL_SYMBOL_MAP[sym_key] = {
                        "tradingsymbol": tsym,
                        "instrument_token": token,
                    }

                    if exp_str:
                        key = f"{exch}:{name}"
                        if key not in t_GLOBAL_EXPIRIES:
                            t_GLOBAL_EXPIRIES[key] = set()
                        t_GLOBAL_EXPIRIES[key].add(exp_str)

                    if name not in t_GLOBAL_INSTRUMENT_META:
                        try:
                            lot = int(float(row.get("lot_size", 1)))
                        except Exception:
                            lot = 1
                        if name == "NIFTY":
                            lot = 65
                        t_GLOBAL_INSTRUMENT_META[name] = {"lot_size": lot, "strikes": set()}
                    if strike_val > 0:
                        t_GLOBAL_INSTRUMENT_META[name]["strikes"].add(strike_val)

                for k in t_GLOBAL_EXPIRIES:
                    t_GLOBAL_EXPIRIES[k] = sorted(list(t_GLOBAL_EXPIRIES[k]))
                for k, v in t_GLOBAL_INSTRUMENT_META.items():
                    strikes = sorted(list(v["strikes"]))
                    step = 50
                    if len(strikes) > 1:
                        diffs = [
                            round(strikes[i + 1] - strikes[i], 2)
                            for i in range(len(strikes) - 1)
                        ]
                        diffs = [d for d in diffs if d > 0]
                        if diffs:
                            step = max(set(diffs), key=diffs.count)
                    v["strike_step"] = step
                    del v["strikes"]

                INSTRUMENT_MAP, TOKEN_EXPIRY_MAP = t_INSTRUMENT_MAP, t_TOKEN_EXPIRY_MAP
                GLOBAL_EXPIRIES, GLOBAL_INSTRUMENT_META, GLOBAL_SYMBOL_MAP = (
                    t_GLOBAL_EXPIRIES,
                    t_GLOBAL_INSTRUMENT_META,
                    t_GLOBAL_SYMBOL_MAP,
                )

                log_event(f"Database Ready: {len(INSTRUMENT_MAP)} tokens loaded.")
                break
            except Exception:
                time.sleep(5)

    def norm_cdf(x):
        return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

    def norm_pdf(x):
        return math.exp(-(x**2) / 2.0) / math.sqrt(2.0 * math.pi)

    def get_fractional_dte(exch, exp_date_str, ref_dt=None):
        try:
            if not exp_date_str:
                return 0.002
            exp_date = datetime.datetime.strptime(exp_date_str, "%Y-%m-%d").date()
            exp_time = (
                datetime.time(23, 30)
                if exch == "MCX"
                else (
                    datetime.time(17, 0)
                    if exch == "CDS"
                    else datetime.time(15, 30)
                )
            )
            exp_dt = IST.localize(datetime.datetime.combine(exp_date, exp_time))
            curr_dt = ref_dt if ref_dt else datetime.datetime.now(IST)
            return max(0.001, (exp_dt - curr_dt).total_seconds() / 86400.0) / 365.0
        except Exception:
            return 0.002

    def calc_iv(cp_flag, S_or_F, K, T, r, price, is_future=False):
        if T <= 0 or S_or_F <= 0 or K <= 0 or price <= 0:
            return 0.0
        drift_r = 0.0 if is_future else r
        sigma = 0.3
        for _ in range(50):
            try:
                d1 = (math.log(S_or_F / K) + (drift_r + 0.5 * sigma**2) * T) / (
                    sigma * math.sqrt(T)
                )
                d2 = d1 - sigma * math.sqrt(T)
                df = math.exp(-r * T)
                if is_future:
                    est_price = (
                        df * (S_or_F * norm_cdf(d1) - K * norm_cdf(d2))
                        if cp_flag == "CE"
                        else df * (K * norm_cdf(-d2) - S_or_F * norm_cdf(-d1))
                    )
                    vega = df * S_or_F * norm_pdf(d1) * math.sqrt(T)
                else:
                    est_price = (
                        S_or_F * norm_cdf(d1) - K * df * norm_cdf(d2)
                        if cp_flag == "CE"
                        else K * df * norm_cdf(-d2) - S_or_F * norm_cdf(-d1)
                    )
                    vega = S_or_F * norm_pdf(d1) * math.sqrt(T)
                diff = price - est_price
                if abs(diff) < 1e-4 or vega < 1e-4:
                    break
                sigma += diff / vega
            except Exception:
                break
        return max(sigma * 100.0, 0.0)

    def fetch_history(token):
        global DIAGNOSTICS
        try:
            to_date = datetime.datetime.now(IST)
            from_date = to_date - datetime.timedelta(days=4)
            url = f"https://kite.zerodha.com/oms/instruments/historical/{token}/minute"
            params = {
                "user_id": API_CONFIG["user_id"],
                "oi": 1,
                "from": from_date.strftime("%Y-%m-%d 09:00:00"),
                "to": to_date.strftime("%Y-%m-%d 23:59:59"),
            }
            res = KITE_SESSION.get(
                url, 
                params=params, 
                headers={"authorization": f"enctoken {API_CONFIG['enc_token']}"},
                timeout=5
            )
            DIAGNOSTICS["last_rest_ping"] = datetime.datetime.now(IST).strftime("%H:%M:%S")
            if res.status_code == 200:
                DIAGNOSTICS["rest_history_status"] = f"SUCCESS (Token: {token})"
                data = res.json().get("data", {}).get("candles", [])
                history_dict = {}
                for row in data:
                    try:
                        dt = datetime.datetime.strptime(row[0][:19], "%Y-%m-%dT%H:%M:%S")
                        dt = IST.localize(dt)
                        history_dict[dt] = float(row[4])
                    except Exception:
                        pass
                return history_dict
            else:
                DIAGNOSTICS["rest_history_status"] = f"FAILED HTTP {res.status_code}"
        except Exception as e:
            DIAGNOSTICS["rest_history_status"] = f"ERROR: {str(e)[:20]}"
        return {}

    def rebuild_historical_chart():
        global CHART_LABELS, CHART_PREMIUM, CHART_IV, CHART_VWAP, CHART_MASTER, CHART_LEGS, CHART_PNL, CHART_MEAN, LAST_CHART_UPDATE
        active_legs = [l for l in STRATEGY_LEGS if l.get("enabled", True)]
        master_token = STRATEGY_CONFIG.get("master_und_token")
        if not active_legs or not master_token:
            reset_chart()
            return
        log_event("Fetching Historical Intraday Data...")

        master_dict = fetch_history(master_token)
        if not master_dict:
            log_event("Failed to fetch Master Asset history.")
            return

        leg_dicts = {}
        for token in list(set([l["token"] for l in active_legs])):
            ld = fetch_history(token)
            if ld:
                leg_dicts[token] = ld

        if not leg_dicts:
            return

        all_timestamps = set(master_dict.keys())
        for ld in leg_dicts.values():
            all_timestamps.update(ld.keys())
        sorted_timestamps = sorted(list(all_timestamps))

        last_known = {"master": 0.0}
        for t in leg_dicts.keys():
            last_known[t] = 0.0

        final_rows = []
        for dt in sorted_timestamps:
            if dt in master_dict:
                last_known["master"] = master_dict[dt]
            for t in leg_dicts.keys():
                if dt in leg_dicts[t]:
                    last_known[t] = leg_dicts[t]

            is_valid = True
            for v in last_known.values():
                if v == 0.0:
                    is_valid = False
                    break

            if is_valid:
                final_rows.append((dt, dict(last_known)))

        final_rows = final_rows[-2000:]

        t_labels, t_prem, t_iv, t_vwap, t_master, t_pnl, t_mean = (
            [],
            [],
            [],
            [],
            [],
            [],
            [],
        )
        t_legs = {l["tradingsymbol"]: [] for l in active_legs}
        rf = float(STRATEGY_CONFIG.get("risk_free_rate", 7.0)) / 100.0
        master_sym = STRATEGY_CONFIG.get("master_und_sym", "")

        for dt, row_vals in final_rows:
            master_ltp = row_vals["master"]
            c_prem = 0.0
            ivs = []

            candle_dt = dt
            mean_px = 0.0
            if len(active_legs) >= 2:
                l1 = row_vals.get(active_legs[0]["token"], 0.0)
                l2 = row_vals.get(active_legs[1]["token"], 0.0)
                s1 = (
                    1
                    if active_legs[0].get("transaction_type", "SELL") == "SELL"
                    else -1
                )
                s2 = (
                    1
                    if active_legs[1].get("transaction_type", "SELL") == "SELL"
                    else -1
                )
                if l1 > 0 and l2 > 0:
                    mean_px = abs(((l1 * s1) + (l2 * s2)) / 2.0)

            for l in active_legs:
                sym = l["tradingsymbol"]
                leg_px = row_vals.get(l["token"], 0.0)
                t_legs[sym].append(round(leg_px, 2))
                if leg_px > 0:
                    c_prem += (
                        leg_px
                        if l.get("transaction_type", "SELL") == "SELL"
                        else -leg_px
                    )
                    if (
                        l.get("opt_type") in ["CE", "PE"]
                        and l.get("strike", 0) > 0
                        and l.get("exp_date")
                    ):
                        dte = get_fractional_dte(l["exchange"], l["exp_date"], candle_dt)
                        if dte > 0 and master_ltp > 0:
                            iv = calc_iv(
                                l["opt_type"],
                                master_ltp,
                                l["strike"],
                                dte,
                                rf,
                                leg_px,
                                (l.get("exchange") == "MCX") or ("FUT" in master_sym),
                            )
                            if iv > 0:
                                ivs.append(iv)

            c_prem = abs(c_prem)
            c_iv = sum(ivs) / len(ivs) if len(ivs) > 0 else 0.0

            t_labels.append(dt.strftime("%d %b %H:%M"))
            t_prem.append(round(c_prem, 2))
            t_iv.append(round(c_iv, 2))
            t_vwap.append(round(c_prem, 2))
            t_master.append(round(master_ltp, 2))
            t_pnl.append(0.0)
            t_mean.append(round(mean_px, 2))

        CHART_LABELS, CHART_PREMIUM, CHART_IV = t_labels, t_prem, t_iv
        CHART_VWAP, CHART_MASTER, CHART_LEGS, CHART_PNL, CHART_MEAN = (
            t_vwap,
            t_master,
            t_legs,
            t_pnl,
            t_mean,
        )
        LAST_CHART_UPDATE = time.time()
        log_event("Historical Multi-Axis Chart Rebuild Complete.")

    def fire_order(
        token, exch, sym, action, qty, prod, ltp, prot_pct, requested_type="SMART"
    ):
        if not API_CONFIG["is_connected"]:
            return
        limit_price, final_order_type, tick = 0, "MARKET", 0.05

        if exch == "MCX":
            tick = (
                0.05
                if sym.endswith("CE") or sym.endswith("PE")
                else (0.10 if "NATGAS" in sym else 1.0)
            )
        elif exch == "CDS":
            tick = 0.0025
        elif exch == "BSE":
            tick = 0.01

        is_mcx_opt = exch == "MCX" and (sym.endswith("CE") or sym.endswith("PE"))
        if is_mcx_opt and requested_type == "MARKET":
            requested_type = "PROTECTED"

        if requested_type == "SMART":
            depth = LIVE_LEG_DEPTH.get(token, {})
            if (
                action == "BUY"
                and len(depth.get("sell", [])) > 0
                and depth["sell"][0]["price"] > 0
            ):
                limit_price = depth["sell"][0]["price"] + (tick * 3)
            elif (
                action == "SELL"
                and len(depth.get("buy", [])) > 0
                and depth["buy"][0]["price"] > 0
            ):
                limit_price = depth["buy"][0]["price"] - (tick * 3)

            if limit_price > 0:
                limit_price = round(round(limit_price / tick) * tick, 4)
                final_order_type = "LIMIT"
            else:
                requested_type = "PROTECTED"

        if requested_type == "PROTECTED" or (
            requested_type == "MARKET" and is_mcx_opt
        ):
            if ltp == 0:
                ltp = LIVE_LEG_PRICES.get(token, 0.0)
            if ltp > 0:
                buf = max(prot_pct, 1.0) / 100.0
                raw_price = ltp * (1 + buf) if action == "BUY" else ltp * (1 - buf)
                limit_price = round(round(max(raw_price, tick) / tick) * tick, 4)
                final_order_type = "LIMIT"
            elif is_mcx_opt:
                log_event(
                    f"REJECT GUARD ({sym}): Cannot place MARKET on MCX Option with 0 LTP."
                )
                return

        payload = {
            "exchange": exch,
            "tradingsymbol": sym,
            "transaction_type": action,
            "order_type": final_order_type,
            "quantity": qty,
            "price": limit_price,
            "product": prod,
            "validity": "DAY",
            "variety": "regular",
        }
        log_event(
            f"EXEC FIRED: {action} {qty}x {sym} @ {final_order_type} {limit_price if limit_price > 0 else ''}"
        )

        try:
            res = KITE_SESSION.post(
                "https://kite.zerodha.com/oms/orders/regular", 
                data=payload, 
                headers={"authorization": f"enctoken {API_CONFIG['enc_token']}"},
                timeout=5
            )
            if res.status_code == 200 and res.json().get("status") == "success":
                log_event(f"CONFIRMED ({sym}): ID {res.json().get('data', {}).get('order_id', 'N/A')}")
            else:
                log_event(f"REJECTED ({sym}): {res.text}")
        except Exception as e:
            log_event(f"EXCEPTION ({sym}): {str(e)[:50]}")

    def execute_multi_leg_strategy():
        active_legs = [l for l in STRATEGY_LEGS if l.get("enabled", True)]
        threads = [
            threading.Thread(
                target=fire_order,
                args=(
                    l["token"],
                    l["exchange"],
                    l["tradingsymbol"],
                    l["transaction_type"],
                    l["quantity"],
                    l["product"],
                    LIVE_LEG_PRICES.get(l["token"], 0),
                    STRATEGY_CONFIG["leg_prot_pct"],
                    l["order_type"],
                ),
            )
            for l in active_legs
        ]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        STRATEGY_CONFIG["armed"] = False

    def trigger_all_portfolio_exits():
        global ORDER_FIRED
        ORDER_FIRED = True
        globals()["LAST_EXIT_FIRE_TIME"] = time.time()
        threads = []
        for t, p in ACTIVE_POSITIONS.items():
            action = "SELL" if p["type"] == "LONG" else "BUY"
            ltp = LIVE_LEG_PRICES.get(t, p["entry_price"])
            exit_order_type = (
                "PROTECTED"
                if p["exchange"] == "MCX" or p["symbol"].endswith(("CE", "PE"))
                else "MARKET"
            )
            th = threading.Thread(
                target=fire_order,
                args=(
                    t,
                    p["exchange"],
                    p["symbol"],
                    action,
                    p["qty"],
                    p["product"],
                    ltp,
                    max(RISK_CONFIG["protection_buffer_pct"], 3.0),
                    exit_order_type,
                ),
            )
            threads.append(th)
            th.start()
        for th in threads:
            th.join()

    parser = KiteTicker("dummy", "dummy")

    def on_message(ws, message):
        global CURRENT_COMBO_PREMIUM, CURRENT_COMBO_VWAP, CURRENT_GAP, NET_PORTFOLIO_PNL
        global CURRENT_ACTIVE_SL, ORDER_FIRED, CURRENT_PREM_DIFF, CURRENT_COMBO_IV
        global LIVE_MASTER_UND_LTP, LIVE_MASTER_UND_VWAP, LAST_CHART_UPDATE

        if isinstance(message, bytes):
            try:
                ticks = parser._parse_binary(message)
            except Exception:
                return

            for tick in ticks:
                token = tick["instrument_token"]
                if token == STRATEGY_CONFIG.get("master_und_token"):
                    if "last_price" in tick:
                        LIVE_MASTER_UND_LTP = tick["last_price"]
                    if "average_traded_price" in tick:
                        LIVE_MASTER_UND_VWAP = tick["average_traded_price"]
                if "last_price" in tick:
                    LIVE_LEG_PRICES[token] = tick["last_price"]
                if "average_traded_price" in tick:
                    LIVE_LEG_VWAP[token] = tick["average_traded_price"]
                if "depth" in tick:
                    LIVE_LEG_DEPTH[token] = tick["depth"]

                enabled_legs = [l for l in STRATEGY_LEGS if l.get("enabled", True)]
                combo_valid = len(enabled_legs) > 0 and all(
                    LIVE_LEG_PRICES.get(l["token"], 0) > 0 for l in enabled_legs
                )

                if combo_valid:
                    CURRENT_COMBO_PREMIUM = abs(
                        sum(
                            (
                                LIVE_LEG_PRICES.get(l["token"], 0)
                                if l.get("transaction_type", "SELL") == "SELL"
                                else -LIVE_LEG_PRICES.get(l["token"], 0)
                            )
                            for l in enabled_legs
                        )
                    )
                    CURRENT_COMBO_VWAP = abs(
                        sum(
                            (
                                LIVE_LEG_VWAP.get(l["token"], 0)
                                if l.get("transaction_type", "SELL") == "SELL"
                                else -LIVE_LEG_VWAP.get(l["token"], 0)
                            )
                            for l in enabled_legs
                        )
                    )
                    CURRENT_GAP = CURRENT_COMBO_PREMIUM - CURRENT_COMBO_VWAP
                    CURRENT_PREM_DIFF = (
                        abs(
                            LIVE_LEG_PRICES.get(enabled_legs[0]["token"], 0)
                            - LIVE_LEG_PRICES.get(enabled_legs[1]["token"], 0)
                        )
                        if len(enabled_legs) >= 2
                        else 0.0
                    )

                    ivs = []
                    for l in enabled_legs:
                        if (
                            l.get("opt_type") in ["CE", "PE"]
                            and l.get("strike", 0) > 0
                            and l.get("exp_date")
                        ):
                            dte = get_fractional_dte(l["exchange"], l["exp_date"])
                            calc_master = (
                                LIVE_MASTER_UND_LTP
                                if LIVE_MASTER_UND_LTP > 0
                                else l.get("strike", 0)
                            )
                            if dte > 0 and calc_master > 0:
                                iv = calc_iv(
                                    l["opt_type"],
                                    calc_master,
                                    l["strike"],
                                    dte,
                                    float(STRATEGY_CONFIG.get("risk_free_rate", 7.0)) / 100.0,
                                    LIVE_LEG_PRICES[l["token"]],
                                    (l.get("exchange") == "MCX")
                                    or ("FUT" in STRATEGY_CONFIG.get("master_und_sym", "")),
                                )
                                if iv > 0:
                                    ivs.append(iv)
                    CURRENT_COMBO_IV = sum(ivs) / len(ivs) if len(ivs) > 0 else 0.0
                else:
                    (
                        CURRENT_COMBO_PREMIUM,
                        CURRENT_COMBO_VWAP,
                        CURRENT_GAP,
                        CURRENT_PREM_DIFF,
                        CURRENT_COMBO_IV,
                    ) = (0.0, 0.0, 0.0, 0.0, 0.0)

                curr_time = time.time()
                if curr_time - LAST_CHART_UPDATE > 10.0 and combo_valid:
                    CHART_LABELS.append(datetime.datetime.now(IST).strftime("%d %b %H:%M"))
                    CHART_PREMIUM.append(CURRENT_COMBO_PREMIUM)
                    CHART_IV.append(CURRENT_COMBO_IV)
                    CHART_VWAP.append(CURRENT_COMBO_VWAP)
                    CHART_MASTER.append(LIVE_MASTER_UND_LTP)
                    CHART_PNL.append(NET_PORTFOLIO_PNL)
                    CHART_MEAN.append(
                        abs(
                            (
                                LIVE_LEG_PRICES.get(enabled_legs[0]["token"], 0)
                                * (
                                    1
                                    if enabled_legs[0].get("transaction_type", "SELL")
                                    == "SELL"
                                    else -1
                                )
                            )
                            + (
                                LIVE_LEG_PRICES.get(enabled_legs[1]["token"], 0)
                                * (
                                    1
                                    if enabled_legs[1].get("transaction_type", "SELL")
                                    == "SELL"
                                    else -1
                                )
                            )
                        )
                        / 2.0
                        if len(enabled_legs) >= 2
                        else 0.0
                    )

                    active_syms = [l["tradingsymbol"] for l in enabled_legs]
                    for sym in active_syms:
                        if sym not in CHART_LEGS:
                            CHART_LEGS[sym] = [0.0] * (len(CHART_LABELS) - 1)
                    for sym in list(CHART_LEGS.keys()):
                        tkn = (
                            next(
                                (
                                    l["token"]
                                    for l in enabled_legs
                                    if l["tradingsymbol"] == sym
                                ),
                                None,
                            )
                            if sym in active_syms
                            else None
                        )
                        CHART_LEGS[sym].append(LIVE_LEG_PRICES.get(tkn, 0.0) if tkn else 0.0)

                    if len(CHART_LABELS) > 2000:
                        for lst in [
                            CHART_LABELS,
                            CHART_PREMIUM,
                            CHART_IV,
                            CHART_VWAP,
                            CHART_MASTER,
                            CHART_PNL,
                            CHART_MEAN,
                        ]:
                            lst.pop(0)
                        for k in CHART_LEGS:
                            CHART_LEGS[k].pop(0)
                    LAST_CHART_UPDATE = curr_time

                if (
                    len(enabled_legs) > 0
                    and STRATEGY_CONFIG["armed"]
                    and not STRATEGY_CONFIG["fired"]
                ):
                    active_evals = []
                    if STRATEGY_CONFIG["use_premium_cond"] and combo_valid:
                        c, tgt = (
                            STRATEGY_CONFIG["condition"],
                            STRATEGY_CONFIG["target_premium"],
                        )
                        trig = (
                            (c == ">=" and CURRENT_COMBO_PREMIUM >= tgt)
                            or (c == "<=" and CURRENT_COMBO_PREMIUM <= tgt)
                            or (c == ">" and CURRENT_COMBO_PREMIUM > tgt)
                            or (c == "<" and CURRENT_COMBO_PREMIUM < tgt)
                        )
                        active_evals.append((STRATEGY_CONFIG.get("prem_gate", "AND"), trig))

                    if STRATEGY_CONFIG["use_diff_cond"] and combo_valid:
                        active_evals.append((
                            STRATEGY_CONFIG.get("diff_gate", "AND"),
                            CURRENT_PREM_DIFF <= STRATEGY_CONFIG["diff_target"],
                        ))

                    if STRATEGY_CONFIG["use_vwap_cond"] and combo_valid:
                        d = STRATEGY_CONFIG["vwap_direction"]
                        trig = (
                            d == ">" and CURRENT_COMBO_PREMIUM > CURRENT_COMBO_VWAP
                        ) or (d == "<" and CURRENT_COMBO_PREMIUM < CURRENT_COMBO_VWAP)
                        active_evals.append((STRATEGY_CONFIG.get("vwap_gate", "AND"), trig))

                    if STRATEGY_CONFIG["use_iv_cond"] and CURRENT_COMBO_IV > 0:
                        c, tgt = STRATEGY_CONFIG["iv_cond"], STRATEGY_CONFIG["iv_target"]
                        trig = (
                            (c == ">=" and CURRENT_COMBO_IV >= tgt)
                            or (c == "<=" and CURRENT_COMBO_IV <= tgt)
                            or (c == ">" and CURRENT_COMBO_IV > tgt)
                            or (c == "<" and CURRENT_COMBO_IV < tgt)
                        )
                        active_evals.append((STRATEGY_CONFIG.get("iv_gate", "AND"), trig))

                    if STRATEGY_CONFIG["use_time_cond"]:
                        try:
                            t_str = STRATEGY_CONFIG["target_time"]
                            if len(t_str.split(":")) == 2:
                                t_str += ":00"
                            active_evals.append((
                                STRATEGY_CONFIG.get("time_gate", "AND"),
                                datetime.datetime.now(IST).time()
                                >= datetime.datetime.strptime(t_str, "%H:%M:%S").time(),
                            ))
                        except Exception:
                            active_evals.append((STRATEGY_CONFIG.get("time_gate", "AND"), False))

                    if (
                        STRATEGY_CONFIG["use_underlying_cond"]
                        and STRATEGY_CONFIG["master_und_token"]
                    ):
                        ul, tg, c = (
                            LIVE_MASTER_UND_LTP,
                            STRATEGY_CONFIG["und_target"],
                            STRATEGY_CONFIG["und_cond"],
                        )
                        trig = ul > 0 and (
                            (c == ">=" and ul >= tg)
                            or (c == "<=" and ul <= tg)
                            or (c == ">" and ul > tg)
                            or (c == "<" and ul < tg)
                        )
                        active_evals.append((STRATEGY_CONFIG.get("und_ltp_gate", "AND"), trig))

                    if (
                        STRATEGY_CONFIG["use_und_vwap_cond"]
                        and STRATEGY_CONFIG["master_und_token"]
                    ):
                        ul, uv, d = (
                            LIVE_MASTER_UND_LTP,
                            LIVE_MASTER_UND_VWAP,
                            STRATEGY_CONFIG["und_vwap_dir"],
                        )
                        trig = ul > 0 and uv > 0 and ((d == ">" and ul > uv) or (d == "<" and ul < uv))
                        active_evals.append(
                            (STRATEGY_CONFIG.get("und_vwap_gate", "AND"), trig)
                        )

                    final_trigger = False
                    if active_evals:
                        final_trigger = active_evals[0][1]
                        for gate, res in active_evals[1:]:
                            final_trigger = (
                                final_trigger and res if gate == "AND" else final_trigger or res
                            )

                        if final_trigger:
                            STRATEGY_CONFIG["fired"] = True
                            log_event("MULTI-GATE CONDITIONS MET! Firing Execution Order...")
                            execute_multi_leg_strategy()

                if token in ACTIVE_POSITIONS and "last_price" in tick:
                    if (
                        ORDER_FIRED
                        and "LAST_EXIT_FIRE_TIME" in globals()
                        and time.time() - globals()["LAST_EXIT_FIRE_TIME"] > 15.0
                    ):
                        ORDER_FIRED = False

                    if not ORDER_FIRED:
                        current_pnl, all_legs_ticked = 0.0, True
                        for t, p in ACTIVE_POSITIONS.items():
                            ltp = LIVE_LEG_PRICES.get(t, 0.0)
                            if ltp == 0:
                                all_legs_ticked = False
                                break
                            current_pnl += (
                                (ltp - p["entry_price"]) * p["qty"] * p["multiplier"]
                                if p["type"] == "LONG"
                                else (p["entry_price"] - ltp) * p["qty"] * p["multiplier"]
                            )

                        if all_legs_ticked:
                            NET_PORTFOLIO_PNL = current_pnl
                            if CURRENT_ACTIVE_SL is None or not RISK_CONFIG["tsl_enabled"]:
                                CURRENT_ACTIVE_SL = RISK_CONFIG["stoploss_pnl"]
                            if RISK_CONFIG["tsl_enabled"] and NET_PORTFOLIO_PNL > 0:
                                if (
                                    NET_PORTFOLIO_PNL - RISK_CONFIG["tsl_gap"]
                                ) > CURRENT_ACTIVE_SL:
                                    CURRENT_ACTIVE_SL = NET_PORTFOLIO_PNL - RISK_CONFIG["tsl_gap"]
                            if CURRENT_ACTIVE_SL < RISK_CONFIG["stoploss_pnl"]:
                                CURRENT_ACTIVE_SL = RISK_CONFIG["stoploss_pnl"]

                            boot_safe = time.time() - SYSTEM_START_TIME > 5.0
                            time_exit_triggered = False
                            if RISK_CONFIG.get("time_exit_enabled"):
                                try:
                                    t_str = RISK_CONFIG["time_exit_target"]
                                    if len(t_str.split(":")) == 2:
                                        t_str += ":00"
                                    if (
                                        datetime.datetime.now(IST).time()
                                        >= datetime.datetime.strptime(t_str, "%H:%M:%S").time()
                                    ):
                                        time_exit_triggered = True
                                except Exception:
                                    pass

                            if RISK_CONFIG["panic_exit"] and boot_safe:
                                trigger_all_portfolio_exits()
                                RISK_CONFIG["panic_exit"] = False
                            elif boot_safe:
                                if time_exit_triggered:
                                    RISK_CONFIG["time_exit_enabled"] = False
                                    log_event("TIME EXIT MET: Squaring off all positions!")
                                    trigger_all_portfolio_exits()
                                elif RISK_CONFIG["auto_squareoff"]:
                                    if (
                                        NET_PORTFOLIO_PNL >= RISK_CONFIG["target_pnl"]
                                        or NET_PORTFOLIO_PNL <= CURRENT_ACTIVE_SL
                                    ):
                                        log_event(
                                            f"RISK/TARGET HIT ({NET_PORTFOLIO_PNL:.2f}): Squaring"
                                            " off!"
                                        )
                                        trigger_all_portfolio_exits()

    def on_open(ws):
        global DIAGNOSTICS
        DIAGNOSTICS["ws_status"] = "CONNECTED"
        log_event("WebSocket Connected.")
        sub_tokens = [
            l["token"]
            for l in STRATEGY_LEGS
            if l.get("enabled", True) and "token" in l
        ]
        if STRATEGY_CONFIG.get("master_und_token"):
            sub_tokens.append(STRATEGY_CONFIG["master_und_token"])
        sub_tokens.extend(list(ACTIVE_POSITIONS.keys()))
        unique_tokens = list(set(sub_tokens))
        if unique_tokens:
            try:
                ws.send(json.dumps({"a": "subscribe", "v": unique_tokens}))
                ws.send(json.dumps({"a": "mode", "v": ["full", unique_tokens]}))
            except Exception as e:
                log_event(f"Sub restore failed: {e}")

    def on_error(ws, err):
        log_event(f"WS Error: {err}")

    def on_close(ws, c, m):
        DIAGNOSTICS["ws_status"] = "DISCONNECTED"

    def start_websocket_stream():
        global stealth_ws
        while True:
            try:
                if API_CONFIG["is_connected"]:
                    encoded_token = urllib.parse.quote(
                        urllib.parse.unquote(API_CONFIG["enc_token"])
                    )
                    ws_url = (
                        "wss://ws.zerodha.com/?api_key=kitefront&user_id="
                        f"{API_CONFIG['user_id']}&enctoken={encoded_token}&uid="
                        f"{int(time.time()*1000)}&user-agent=kite3-web&version=3.0.0"
                    )
                    stealth_ws = websocket.WebSocketApp(
                        ws_url,
                        header={"User-Agent": "Mozilla/5.0"},
                        on_open=on_open,
                        on_message=on_message,
                        on_error=on_error,
                        on_close=on_close,
                    )
                    stealth_ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception:
                pass
            time.sleep(5)

    def portfolio_sync_thread():
        global ACTIVE_POSITIONS
        while True:
            time.sleep(10)
            if not API_CONFIG["is_connected"]:
                continue
            try:
                res = KITE_SESSION.get(
                    "https://kite.zerodha.com/oms/portfolio/positions",
                    headers={"authorization": f"enctoken {API_CONFIG['enc_token']}"}
                )
                if res.status_code == 200:
                    server_pos = {}
                    for p in res.json().get("data", {}).get("net", []):
                        if p["quantity"] != 0:
                            server_pos[p["instrument_token"]] = {
                                "symbol": p["tradingsymbol"],
                                "exchange": p["exchange"],
                                "qty": abs(p["quantity"]),
                                "entry_price": float(p["average_price"]),
                                "type": "LONG" if p["quantity"] > 0 else "SHORT",
                                "multiplier": float(p.get("multiplier", 1)),
                                "product": p.get("product", "NRML"),
                            }
                    ACTIVE_POSITIONS = server_pos
                    tokens_to_sub = list(server_pos.keys())
                    if (
                        tokens_to_sub
                        and stealth_ws
                        and stealth_ws.sock
                        and stealth_ws.sock.connected
                    ):
                        stealth_ws.send(json.dumps({"a": "subscribe", "v": tokens_to_sub}))
                        stealth_ws.send(
                            json.dumps({"a": "mode", "v": ["full", tokens_to_sub]})
                        )
            except Exception:
                pass

    app = Flask(__name__)
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)

    HTML_TEMPLATE = r"""
    <!DOCTYPE html>
    <html lang="en" data-bs-theme="dark">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Garua Algo Command Center</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js"></script>
        <style>
            body { background-color: #0b0c10; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
            .card { background-color: #1f2833 !important; border-color: #45a29e; border-radius: 8px; }
            .text-cyan { color: #66fcf1; }
            .table-dark { background-color: #1f2833 !important; }
            .table-hover tbody tr:hover { background-color: #2b3a4a !important; }
            .logs-window { height: 250px; overflow-y: auto; background-color: #000; color: #0f0; font-family: monospace; font-size: 0.85rem; padding: 10px; border-radius: 4px; }
        </style>
    </head>
    <body class="container-fluid py-3">
        <nav class="navbar navbar-dark mb-3 rounded" style="background-color: #1f2833; border-bottom: 2px solid #66fcf1;">
          <div class="container-fluid">
            <span class="navbar-brand fw-bold text-cyan">Garua Engine V25.8</span>
            <div class="d-flex text-white align-items-center">
               <span id="timeBadge" class="badge bg-secondary me-2 fs-6">--:--:--</span>
               <span id="wsBadge" class="badge bg-danger me-2 fs-6">WS: DISCONNECTED</span>
               <span id="apiBadge" class="badge bg-danger fs-6">API: DISCONNECTED</span>
               <button class="btn btn-sm btn-outline-success ms-3 fw-bold" data-bs-toggle="modal" data-bs-target="#loginModal">🔑 LOGIN</button>
            </div>
          </div>
        </nav>
        <div class="row g-3 mb-3">
             <div class="col-6 col-md-3">
               <div class="card h-100 shadow">
                 <div class="card-body text-center">
                   <h6 class="card-title text-muted fw-bold">NET P&L</h6>
                   <h3 id="netPnl" class="text-white fw-bold">₹0.00</h3>
                   <small class="text-muted">Trailing SL: <span id="activeSl" class="text-danger">0.00</span></small>
                 </div>
               </div>
             </div>
             <div class="col-6 col-md-3">
               <div class="card h-100 shadow">
                 <div class="card-body text-center">
                   <h6 class="card-title text-muted fw-bold">COMBO PREMIUM</h6>
                   <h3 id="comboPrem" class="text-cyan fw-bold">0.00</h3>
                   <small class="text-muted">VWAP: <span id="comboVwap">0.00</span> | Gap: <span id="comboGap">0.00</span></small>
                 </div>
               </div>
             </div>
             <div class="col-6 col-md-3">
               <div class="card h-100 shadow">
                 <div class="card-body text-center">
                   <h6 class="card-title text-muted fw-bold">MASTER ASSET (LTP)</h6>
                   <h3 id="masterLtp" class="text-white fw-bold" style="color:#c5a8ff !important;">0.00</h3>
                   <small class="text-muted">VWAP: <span id="masterVwap">0.00</span></small>
                 </div>
               </div>
             </div>
             <div class="col-6 col-md-3">
               <div class="card h-100 shadow">
                 <div class="card-body text-center">
                   <h6 class="card-title text-muted fw-bold">COMBO IV / SPREAD</h6>
                   <h3 id="comboIv" class="text-warning fw-bold">0.0%</h3>
                   <small class="text-muted">Prem Diff: <span id="premDiff">0.00</span></small>
                 </div>
               </div>
             </div>
        </div>
        <div class="card shadow mb-3">
           <div class="card-body d-flex flex-wrap justify-content-between align-items-center py-2">
              <div>
                 <button class="btn btn-sm btn-outline-info me-2 fw-bold" onclick="importPositions()">📥 IMPORT POSITIONS</button>
                 <button class="btn btn-sm btn-outline-warning me-2 fw-bold" disabled>⚡ ARM STRATEGY</button>
              </div>
              <div>
                 <button class="btn btn-sm btn-danger fw-bold shadow">🛑 PANIC EXIT ALL</button>
              </div>
           </div>
        </div>
        <div class="row g-3">
             <div class="col-lg-8">
                <div class="card shadow mb-3">
                   <div class="card-header border-secondary text-cyan fw-bold">Live Multi-Axis Telemetry</div>
                   <div class="card-body" style="background-color: #0b0c10;">
                      <canvas id="algoChart" style="height: 350px; width: 100%;"></canvas>
                   </div>
                </div>
                <div class="card shadow">
                   <div class="card-header border-secondary text-success fw-bold">Live Active Positions</div>
                   <div class="card-body p-0 table-responsive">
                      <table class="table table-dark table-hover mb-0 text-center align-middle" style="font-size: 0.85rem;">
                         <thead class="text-muted">
                            <tr>
                               <th>Symbol</th>
                               <th>Side</th>
                               <th>Qty</th>
                               <th>Entry</th>
                               <th>LTP</th>
                               <th>P&L</th>
                               <th>IV</th>
                               <th>Delta</th>
                            </tr>
                         </thead>
                         <tbody id="livePositionsBody">
                            <tr><td colspan="8" class="text-muted py-3">No active positions synced.</td></tr>
                         </tbody>
                      </table>
                   </div>
                </div>
             </div>
             <div class="col-lg-4">
                <div class="card shadow mb-3">
                   <div class="card-header border-secondary text-warning fw-bold">Strategy Builder Legs</div>
                   <div class="card-body p-0 table-responsive">
                      <table class="table table-dark mb-0 text-center align-middle" style="font-size: 0.85rem;">
                         <thead class="text-muted">
                            <tr>
                               <th>Symbol</th>
                               <th>Side</th>
                               <th>Qty</th>
                               <th>LTP</th>
                            </tr>
                         </thead>
                         <tbody id="stratLegsBody">
                            <tr><td colspan="4" class="text-muted py-3">No legs loaded into engine.</td></tr>
                         </tbody>
                      </table>
                   </div>
                </div>
                <div class="card shadow">
                   <div class="card-header border-secondary text-light fw-bold">Execution Logs</div>
                   <div class="card-body p-0">
                      <div class="logs-window" id="logsContainer">
                         <div class="text-muted">Waiting for engine events...</div>
                      </div>
                   </div>
                </div>
             </div>
        </div>

        <!-- Login Modal -->
        <div class="modal fade" id="loginModal" tabindex="-1" data-bs-theme="dark">
          <div class="modal-dialog">
            <div class="modal-content" style="background-color: #1f2833; color: white;">
              <div class="modal-header border-secondary">
                <h5 class="modal-title text-cyan">Zerodha Authentication</h5>
                <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
              </div>
              <div class="modal-body">
                <div class="mb-3">
                  <label>User ID</label>
                  <input type="text" id="inputUserId" class="form-control bg-dark text-white border-secondary">
                </div>
                <div class="mb-3">
                  <label>ENCTOKEN</label>
                  <input type="password" id="inputEncToken" class="form-control bg-dark text-white border-secondary">
                </div>
              </div>
              <div class="modal-footer border-secondary">
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                <button type="button" class="btn btn-success fw-bold" onclick="submitAuth()">Connect</button>
              </div>
            </div>
          </div>
        </div>

    <script>
        let chartObj = null;
        function initChart() {
            const ctx = document.getElementById('algoChart').getContext('2d');
            chartObj = new Chart(ctx, {
                type: 'line',
                data: { labels: [], datasets: [
                    { label: 'Combo Premium', borderColor: '#66fcf1', backgroundColor: 'rgba(102, 252, 241, 0.1)', data: [], yAxisID: 'y', fill: true, tension: 0.2, pointRadius: 0 },
                    { label: 'Combo VWAP', borderColor: '#fd7e14', borderDash: [5, 5], data: [], yAxisID: 'y', tension: 0.2, pointRadius: 0 },
                    { label: 'Master Asset', borderColor: '#c5a8ff', data: [], yAxisID: 'y1', tension: 0.2, pointRadius: 0 },
                    { label: 'Net P&L', borderColor: '#4caf50', data: [], yAxisID: 'y2', hidden: true, pointRadius: 0 }
                ]},
                options: {
                    responsive: true, maintainAspectRatio: false, animation: false,
                    interaction: { mode: 'index', intersect: false },
                    scales: {
                        x: { ticks: { color: '#888', maxTicksLimit: 10 }, grid: { color: '#1f2833' } },
                        y: { type: 'linear', display: true, position: 'left', ticks: { color: '#66fcf1' }, grid: { color: '#1f2833' } },
                        y1: { type: 'linear', display: true, position: 'right', ticks: { color: '#c5a8ff' }, grid: { drawOnChartArea: false } },
                        y2: { type: 'linear', display: false, position: 'right' }
                    },
                    plugins: { legend: { labels: { color: '#c5c6c7' } } }
                }
            });
        }

        async function updateDashboard() {
            try {
                const res = await fetch('/api/data');
                const data = await res.json();
                document.getElementById('timeBadge').innerText = data.server_time;
                const apiB = document.getElementById('apiBadge');
                apiB.innerText = data.api_connected ? 'API: CONNECTED' : 'API: DISCONNECTED';
                apiB.className = data.api_connected ? 'badge bg-success fs-6' : 'badge bg-danger fs-6';
                const wsB = document.getElementById('wsBadge');
                const wsStatus = data.diagnostics.api.ws_status || 'DISCONNECTED';
                wsB.innerText = 'WS: ' + wsStatus;
                wsB.className = wsStatus === 'CONNECTED' ? 'badge bg-success me-2 fs-6' : 'badge bg-danger me-2 fs-6';
                const pnlStr = data.pnl.toFixed(2);
                const pnlEl = document.getElementById('netPnl');
                pnlEl.innerText = (data.pnl >= 0 ? '+₹' : '-₹') + Math.abs(pnlStr);
                pnlEl.className = data.pnl >= 0 ? 'text-success fw-bold' : 'text-danger fw-bold';
                document.getElementById('activeSl').innerText = data.active_sl.toFixed(2);
                document.getElementById('comboPrem').innerText = data.premium.toFixed(2);
                document.getElementById('comboVwap').innerText = data.vwap.toFixed(2);
                document.getElementById('comboGap').innerText = data.gap.toFixed(2);
                document.getElementById('masterLtp').innerText = data.master_ltp.toFixed(2);
                document.getElementById('masterVwap').innerText = data.master_vwap.toFixed(2);
                document.getElementById('comboIv').innerText = data.combo_iv.toFixed(2) + '%';
                document.getElementById('premDiff').innerText = data.prem_diff.toFixed(2);

                if (data.chart.labels.length > 0) {
                    chartObj.data.labels = data.chart.labels;
                    chartObj.data.datasets[0].data = data.chart.premium;
                    chartObj.data.datasets[1].data = data.chart.vwap;
                    chartObj.data.datasets[2].data = data.chart.master;
                    chartObj.data.datasets[3].data = data.chart.pnl;
                    chartObj.update();
                }

                let legsHtml = '';
                data.legs.forEach(l => {
                    const sideColor = l.type === 'BUY' ? 'text-primary' : 'text-danger';
                    legsHtml += `<tr><td class="fw-bold">${l.symbol}</td><td class="${sideColor} fw-bold">${l.type}</td><td>${l.qty}</td><td class="text-cyan">${l.ltp.toFixed(2)}</td></tr>`;
                });
                document.getElementById('stratLegsBody').innerHTML = legsHtml || '<tr><td colspan="4" class="text-muted py-3">No legs loaded into engine.</td></tr>';

                let posHtml = '';
                data.live_positions.forEach(p => {
                    const sideColor = p.type === 'LONG' ? 'text-primary' : 'text-danger';
                    const pnlColor = p.pnl >= 0 ? 'text-success' : 'text-danger';
                    posHtml += `<tr>
                        <td class="fw-bold">${p.symbol}</td>
                        <td class="${sideColor} fw-bold">${p.type}</td>
                        <td>${p.qty}</td>
                        <td>${p.entry_price.toFixed(2)}</td>
                        <td class="text-cyan">${p.ltp.toFixed(2)}</td>
                        <td class="${pnlColor} fw-bold">${(p.pnl >= 0 ? '+' : '')}${p.pnl.toFixed(2)}</td>
                        <td class="text-warning">${p.iv.toFixed(2)}%</td>
                        <td>${p.delta.toFixed(3)}</td>
                    </tr>`;
                });
                document.getElementById('livePositionsBody').innerHTML = posHtml || '<tr><td colspan="8" class="text-muted py-3">No active positions synced.</td></tr>';

                const logsDiv = document.getElementById('logsContainer');
                if(data.logs && data.logs.length > 0) {
                    logsDiv.innerHTML = data.logs.map(log => `<div>> ${log}</div>`).join('');
                }
            } catch (err) {
                console.error('Data poll error:', err);
            }
        }

        async function submitAuth() {
            const uid = document.getElementById('inputUserId').value;
            const enc = document.getElementById('inputEncToken').value;
            if(!uid || !enc) {
                alert("Please enter both User ID and ENCTOKEN");
                return;
            }
            try {
                const res = await fetch('/api/auth', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({user_id: uid, enc_token: enc})
                });
                const data = await res.json();
                alert(data.message);
                var myModalEl = document.getElementById('loginModal');
                var modal = bootstrap.Modal.getInstance(myModalEl);
                modal.hide();
            } catch(err) {
                alert("Failed to submit credentials.");
            }
        }

        async function importPositions() {
            try {
                const res = await fetch('/api/import_positions', {method: 'POST'});
                const data = await res.json();
                alert(data.message || `Successfully imported ${data.count} positions.`);
            } catch (err) {
                alert("Error importing positions. Ensure API is connected.");
            }
        }

        window.onload = () => {
            initChart();
            setInterval(updateDashboard, 1000);
        };
    </script>
    </body>
    </html>
    """

    @app.route("/")
    def home():
        return render_template_string(HTML_TEMPLATE)

    @app.route("/api/auth", methods=["POST"])
    def api_auth():
        data = request.json
        API_CONFIG["user_id"] = data.get("user_id", "").strip()
        API_CONFIG["enc_token"] = data.get("enc_token", "").strip()
        API_CONFIG["is_connected"] = True
        log_event(f"User {API_CONFIG['user_id']} credentials updated via UI.")
        return jsonify({"status": "success", "message": "Credentials saved! Connecting to Zerodha..."})

    @app.route("/api/import_positions", methods=["POST"])
    def api_import_positions():
        imported = 0
        for token, p in ACTIVE_POSITIONS.items():
            existing = any(l["token"] == token for l in STRATEGY_LEGS)
            if not existing:
                sym = p["symbol"]
                opt_type = (
                    "CE"
                    if sym.endswith("CE")
                    else ("PE" if sym.endswith("PE") else ("FUT" if "FUT" in sym else "EQ"))
                )
                strike = 0.0

                strike_match = re.search(r"(\d+(?:\.\d+)?)(CE|PE)$", sym)
                if strike_match:
                    strike = float(strike_match.group(1))

                exp_raw = TOKEN_EXPIRY_MAP.get(token)
                if (
                    not exp_raw
                    or str(exp_raw).lower() == "nan"
                    or not str(exp_raw).strip()
                ):
                    exp_date_str = datetime.datetime.now(IST).strftime("%Y-%m-%d")
                else:
                    exp_date_str = str(exp_raw).split(" ")[0]

                STRATEGY_LEGS.append({
                    "exchange": p["exchange"],
                    "tradingsymbol": sym,
                    "transaction_type": "BUY" if p["type"] == "LONG" else "SELL",
                    "quantity": p["qty"],
                    "product": p["product"],
                    "order_type": "SMART",
                    "opt_type": opt_type,
                    "strike": strike,
                    "exp_date": exp_date_str,
                    "token": token,
                    "enabled": True,
                })
                imported += 1

        if imported > 0:
            threading.Thread(target=rebuild_historical_chart, daemon=True).start()
            log_event(
                f"Auto-Imported {imported} open positions into Strategy Builder."
            )
            return jsonify({"status": "ok", "count": imported})
        return jsonify({"status": "error", "message": "No new positions to import."})

    @app.route("/api/data")
    def api_data():
        payload_legs = []
        master_ltp = LIVE_MASTER_UND_LTP
        rf = float(STRATEGY_CONFIG.get("risk_free_rate", 7.0)) / 100.0
        is_future_model = (
            "FUT" in STRATEGY_CONFIG.get("master_und_sym", "")
        ) or (STRATEGY_CONFIG.get("master_und_exch") == "MCX")
        drift_r = 0.0 if is_future_model else rf

        for l in STRATEGY_LEGS:
            temp = l.copy()
            token = l["token"]
            ltp = LIVE_LEG_PRICES.get(token, 0.0)
            temp["ltp"] = ltp
            temp["symbol"] = l["tradingsymbol"]
            temp["type"] = l["transaction_type"]
            temp["qty"] = l["quantity"]

            pos = ACTIVE_POSITIONS.get(token)
            is_live = False
            if pos:
                entry = pos["entry_price"]
                temp["entry_price"] = entry
                mult = pos["multiplier"]
                qty = pos["qty"]
                is_long = pos["type"] == "LONG"
                if is_long:
                    temp["pnl"] = (ltp - entry) * qty * mult
                else:
                    temp["pnl"] = (entry - ltp) * qty * mult
                temp["prem_change_pct"] = (
                    ((ltp - entry) / entry * 100.0) if entry > 0 else 0.0
                )
                temp["is_live"] = True
                is_live = True
            else:
                temp["entry_price"] = 0.0
                temp["pnl"] = 0.0
                temp["prem_change_pct"] = 0.0
                temp["is_live"] = False

            dte_val = get_fractional_dte(l["exchange"], l.get("exp_date", ""))
            temp["dte"] = dte_val * 365.0

            iv_val, delta, gamma, theta, vega = 0.0, 0.0, 0.0, 0.0, 0.0
            calc_master = master_ltp if master_ltp > 0 else l.get("strike", 0)

            if (
                dte_val > 0
                and ltp > 0
                and calc_master > 0
                and l.get("strike", 0) > 0
                and l.get("opt_type") in ["CE", "PE"]
            ):
                iv_val = (
                    calc_iv(
                        l["opt_type"],
                        calc_master,
                        l["strike"],
                        dte_val,
                        rf,
                        ltp,
                        is_future_model,
                    )
                    / 100.0
                )
                if iv_val > 0:
                    d1 = (
                        math.log(calc_master / l["strike"])
                        + (drift_r + 0.5 * iv_val**2) * dte_val
                    ) / (iv_val * math.sqrt(dte_val))
                    d2 = d1 - iv_val * math.sqrt(dte_val)
                    df = math.exp(-rf * dte_val)

                    n_d1 = norm_cdf(d1)
                    np_d1 = norm_pdf(d1)

                    leg_delta = n_d1 if l["opt_type"] == "CE" else n_d1 - 1.0
                    if is_future_model:
                        leg_delta *= df
                    delta = leg_delta

                    leg_gamma = np_d1 / (calc_master * iv_val * math.sqrt(dte_val))
                    if is_future_model:
                        leg_gamma *= df
                    gamma = leg_gamma

                    leg_vega = (calc_master * np_d1 * math.sqrt(dte_val)) / 100.0
                    if is_future_model:
                        leg_vega *= df
                    vega = leg_vega

                    term1 = (
                        -(
                            calc_master
                            * np_d1
                            * iv_val
                            * (df if is_future_model else 1.0)
                        )
                        / (2 * math.sqrt(dte_val))
                    )
                    term2 = rf * l["strike"] * math.exp(-rf * dte_val)
                    if l["opt_type"] == "CE":
                        theta = (term1 - term2 * norm_cdf(d2)) / 365.0
                    else:
                        theta = (term1 + term2 * norm_cdf(-d2)) / 365.0

            iv_perc = iv_val * 100.0
            temp["iv"] = iv_perc
            temp["delta"] = delta
            temp["gamma"] = gamma
            temp["theta"] = theta
            temp["vega"] = vega

            if is_live:
                if token not in LEG_ENTRY_SNAPSHOTS:
                    LEG_ENTRY_SNAPSHOTS[token] = {
                        "iv": iv_perc,
                        "delta": delta,
                        "gamma": gamma,
                        "theta": theta,
                        "vega": vega,
                    }
                snap = LEG_ENTRY_SNAPSHOTS[token]
                temp["iv_change"] = iv_perc - snap["iv"]
                temp["delta_change"] = delta - snap["delta"]
                temp["gamma_change"] = gamma - snap["gamma"]
                temp["theta_change"] = theta - snap["theta"]
                temp["vega_change"] = vega - snap["vega"]
            else:
                temp["iv_change"] = 0.0
                temp["delta_change"] = 0.0
                temp["gamma_change"] = 0.0
                temp["theta_change"] = 0.0
                temp["vega_change"] = 0.0
                if token in LEG_ENTRY_SNAPSHOTS:
                    del LEG_ENTRY_SNAPSHOTS[token]

            payload_legs.append(temp)

        live_positions_payload = []
        for token, pos in ACTIVE_POSITIONS.items():
            ltp = LIVE_LEG_PRICES.get(token, pos["entry_price"])
            entry = pos["entry_price"]
            mult = pos["multiplier"]
            qty = pos["qty"]
            is_long = pos["type"] == "LONG"

            pnl = (
                (ltp - entry) * qty * mult if is_long else (entry - ltp) * qty * mult
            )
            prem_chg = ((ltp - entry) / entry * 100.0) if entry > 0 else 0.0

            sym = pos["symbol"]
            opt_type = (
                "CE"
                if sym.endswith("CE")
                else ("PE" if sym.endswith("PE") else "OTHER")
            )
            strike = 0.0

            strike_match = re.search(r"(\d+(?:\.\d+)?)(CE|PE)$", sym)
            if strike_match:
                strike = float(strike_match.group(1))

            pos_iv, delta, gamma, theta, vega = 0.0, 0.0, 0.0, 0.0, 0.0
            exp_date_raw = TOKEN_EXPIRY_MAP.get(token)
            if (
                not exp_date_raw
                or str(exp_date_raw).lower() == "nan"
                or not str(exp_date_raw).strip()
            ):
                dte_val = 0.002
            else:
                dte_val = get_fractional_dte(
                    pos["exchange"], str(exp_date_raw).split(" ")[0]
                )

            calc_master = master_ltp if master_ltp > 0 else strike
            if opt_type in ["CE", "PE"] and strike > 0 and calc_master > 0 and ltp > 0:
                pos_iv = (
                    calc_iv(
                        opt_type,
                        calc_master,
                        strike,
                        dte_val,
                        rf,
                        ltp,
                        is_future_model,
                    )
                    / 100.0
                )
                if pos_iv > 0:
                    d1 = (
                        math.log(calc_master / strike)
                        + (drift_r + 0.5 * pos_iv**2) * dte_val
                    ) / (pos_iv * math.sqrt(dte_val))
                    d2 = d1 - pos_iv * math.sqrt(dte_val)
                    df = math.exp(-rf * dte_val)
                    n_d1 = norm_cdf(d1)
                    np_d1 = norm_pdf(d1)

                    leg_delta = n_d1 if opt_type == "CE" else n_d1 - 1.0
                    if is_future_model:
                        leg_delta *= df
                    delta = leg_delta

                    leg_gamma = np_d1 / (calc_master * pos_iv * math.sqrt(dte_val))
                    if is_future_model:
                        leg_gamma *= df
                    gamma = leg_gamma

                    leg_vega = (calc_master * np_d1 * math.sqrt(dte_val)) / 100.0
                    if is_future_model:
                        leg_vega *= df
                    vega = leg_vega

                    term1 = (
                        -(
                            calc_master
                            * np_d1
                            * pos_iv
                            * (df if is_future_model else 1.0)
                        )
                        / (2 * math.sqrt(dte_val))
                    )
                    term2 = rf * strike * math.exp(-rf * dte_val)
                    if opt_type == "CE":
                        theta = (term1 - term2 * norm_cdf(d2)) / 365.0
                    else:
                        theta = (term1 + term2 * norm_cdf(-d2)) / 365.0

            iv_perc = pos_iv * 100.0
            iv_change, delta_change, gamma_change, theta_change, vega_change = (
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
            )

            if token not in LEG_ENTRY_SNAPSHOTS:
                LEG_ENTRY_SNAPSHOTS[token] = {
                    "iv": iv_perc,
                    "delta": delta,
                    "gamma": gamma,
                    "theta": theta,
                    "vega": vega,
                }
            snap = LEG_ENTRY_SNAPSHOTS[token]
            iv_change = iv_perc - snap["iv"]
            delta_change = delta - snap["delta"]
            gamma_change = gamma - snap["gamma"]
            theta_change = theta - snap["theta"]
            vega_change = vega - snap["vega"]

            live_positions_payload.append({
                "token": token,
                "symbol": sym,
                "type": pos["type"],
                "qty": qty,
                "entry_price": entry,
                "ltp": ltp,
                "pnl": pnl,
                "prem_change_pct": prem_chg,
                "iv": iv_perc,
                "delta": delta,
                "gamma": gamma,
                "theta": theta,
                "vega": vega,
                "iv_change": iv_change,
                "delta_change": delta_change,
                "gamma_change": gamma_change,
                "theta_change": theta_change,
                "vega_change": vega_change,
                "is_live": True,
            })

        return jsonify({
            "server_time": datetime.datetime.now(IST).strftime("%H:%M:%S"),
            "api_connected": API_CONFIG["is_connected"],
            "inst_count": len(INSTRUMENT_MAP),
            "premium": CURRENT_COMBO_PREMIUM,
            "vwap": CURRENT_COMBO_VWAP,
            "gap": CURRENT_GAP,
            "prem_diff": CURRENT_PREM_DIFF,
            "combo_iv": CURRENT_COMBO_IV,
            "pnl": NET_PORTFOLIO_PNL,
            "master_ltp": LIVE_MASTER_UND_LTP,
            "master_vwap": LIVE_MASTER_UND_VWAP,
            "active_sl": (
                CURRENT_ACTIVE_SL
                if CURRENT_ACTIVE_SL is not None
                else RISK_CONFIG["stoploss_pnl"]
            ),
            "strat": STRATEGY_CONFIG,
            "risk": RISK_CONFIG,
            "legs": payload_legs,
            "live_positions": live_positions_payload,
            "chart": {
                "labels": CHART_LABELS,
                "premium": CHART_PREMIUM,
                "iv": CHART_IV,
                "vwap": CHART_VWAP,
                "master": CHART_MASTER,
                "pnl": CHART_PNL,
                "mean": CHART_MEAN,
                "legs": CHART_LEGS,
            },
            "diagnostics": {"api": DIAGNOSTICS},
            "logs": EVENT_LOG[::-1],
        })

    def run_flask():
        app.run(host="127.0.0.1", port=FLASK_PORT, debug=False, use_reloader=False)

    SUCCESS_LOAD = True

except Exception as e:
    CRASH_ERROR = traceback.format_exc()
    SUCCESS_LOAD = False

class AlgoWebApp(App):
    def build(self):
        if not SUCCESS_LOAD:
            layout = BoxLayout(orientation="vertical", padding=20)
            sv = ScrollView()
            lbl = Label(
                text=f"FATAL BOOT ERROR:\n\n{CRASH_ERROR}", 
                color=(1, 0.2, 0.2, 1), 
                font_size='14sp',
                size_hint_y=None,
                halign="left",
                valign="top"
            )
            lbl.bind(width=lambda *x: lbl.setter('text_size')(lbl, (lbl.width, None)), texture_size=lambda *x: lbl.setter('height')(lbl, lbl.texture_size[1]))
            sv.add_widget(lbl)
            layout.add_widget(Label(text="Garua Engine Crash Reporter", font_size='20sp', size_hint_y=0.1, color=(1,1,0,1)))
            layout.add_widget(sv)
            return layout

        threading.Thread(target=fetch_instrument_tokens, daemon=True).start()
        threading.Thread(target=portfolio_sync_thread, daemon=True).start()
        threading.Thread(target=run_flask, daemon=True).start()
        threading.Thread(target=start_websocket_stream, daemon=True).start()

        layout = BoxLayout(orientation="vertical", padding=30, spacing=20)
        self.lbl = Label(
            text="Garua Engine V25.8\nBooting Server...",
            halign="center",
            font_size="22sp",
            color=(0.05, 0.8, 0.94, 1),
        )
        self.btn = Button(
            text="OPEN ALGO COMMAND CENTER",
            size_hint=(1, 0.25),
            disabled=True,
            background_color=(0, 0.7, 0, 1),
            font_size="18sp",
            bold=True,
        )
        self.btn.bind(on_press=self.open_ui)
        layout.add_widget(self.lbl)
        layout.add_widget(self.btn)

        Clock.schedule_once(self.ready, 4)
        return layout

    def ready(self, dt):
        self.lbl.text = (
            f"Garua Engine V25.8\nServer Active on Port {FLASK_PORT}\n\nClick"
            " below to open the Live Dashboard."
        )
        self.btn.disabled = False

    def open_ui(self, inst):
        try:
            webbrowser.open(f"http://127.0.0.1:{FLASK_PORT}")
        except Exception:
            self.lbl.text = (
                "Could not launch browser natively.\nOpen Chrome to:"
                f"\nhttp://127.0.0.1:{FLASK_PORT}"
            )

if __name__ == "__main__":
    AlgoWebApp().run()
