import sys
import os
import traceback

# 1. IMMEDIATE LOG REDIRECTION TO DISK
LOG_PATH = "/storage/emulated/0/Download/garua_crash_log.txt"

def write_fatal_log(err_text):
    try:
        with open(LOG_PATH, "w") as f:
            f.write(err_text)
    except Exception:
        # Fallback if scoped storage blocks the first path
        try:
            with open("/sdcard/Download/garua_crash_log.txt", "w") as f2:
                f2.write(err_text)
        except Exception:
            pass

try:
    from types import ModuleType

    # --- TWISTED MOCK: Bypasses C-Compiler Crashes on Android ---
    class MockModule(ModuleType):
        def __getattr__(self, name):
            return MockModule(name)

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

except Exception:
    write_fatal_log("BOOT-STAGE IMPORT ERROR:\n" + traceback.format_exc())
    sys.exit(1)

CRASH_ERROR = ""
SUCCESS_LOAD = False

try:
    import csv, datetime, io, json, logging, math, random, re, threading, time, urllib.parse, webbrowser, ssl
    from flask import Flask, jsonify, render_template_string, request
    from kiteconnect import KiteTicker
    import pytz
    import requests
    import websocket
    import socket

    # --- THE SOCKET MONKEY-PATCH FOR ANDROID [Errno 7] ---
    # This intercepts Python's broken DNS lookup and forces it over HTTP
    orig_getaddrinfo = socket.getaddrinfo
    ZERODHA_WS_IP = None
    
    def get_zerodha_ip():
        global ZERODHA_WS_IP
        if ZERODHA_WS_IP: return ZERODHA_WS_IP
        try:
            # Bypass native DNS entirely by using an unblocked public HTTP API
            res = requests.get("https://networkcalc.com/api/dns/lookup/ws.zerodha.com", timeout=5).json()
            ZERODHA_WS_IP = res["records"]["A"][0]["address"]
            return ZERODHA_WS_IP
        except Exception:
            pass
            
        try:
            res = requests.get("https://dns.google/resolve?name=ws.zerodha.com&type=A", timeout=5).json()
            ZERODHA_WS_IP = res["Answer"][0]["data"]
            return ZERODHA_WS_IP
        except Exception:
            pass
            
        # Ultimate fail-safe: Hardcoded Zerodha Cloudflare IP
        ZERODHA_WS_IP = "104.18.23.45"
        return ZERODHA_WS_IP

    def patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if host == "ws.zerodha.com":
            ip = get_zerodha_ip()
            return orig_getaddrinfo(ip, port, family, type, proto, flags)
        return orig_getaddrinfo(host, port, family, type, proto, flags)

    socket.getaddrinfo = patched_getaddrinfo
    # -----------------------------------------------------

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
        if len(EVENT_LOG) > 30:
            EVENT_LOG.pop(0)

    RISK_CONFIG = {
        "target_pnl": 2000.0,
        "stoploss_pnl": -1000.0,
        "auto_squareoff": True,
        "panic_exit": False,
        "protection_buffer_pct": 1.0,
        "tsl_enabled": False,
        "tsl_gap": 300.0,
        "time_exit_enabled": False,
        "time_exit_target": "15:25",
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
        "target_time": "09:20",
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
        "master_und_exch": "NSE",
        "master_und_sym": "NIFTY 50",
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
        log_event("Downloading Master Instruments...")
        while True:
            try:
                headers = {"User-Agent": "Mozilla/5.0"}
                req = requests.get("https://api.kite.trade/instruments", headers=headers, timeout=15, verify=False)
                reader = csv.DictReader(io.StringIO(req.text))

                t_INSTRUMENT_MAP, t_TOKEN_EXPIRY_MAP = {}, {}
                t_GLOBAL_EXPIRIES, t_GLOBAL_INSTRUMENT_META, t_GLOBAL_SYMBOL_MAP = {}, {}, {}

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
                    if "CE" in opt_val: opt_val = "CE"
                    elif "PE" in opt_val: opt_val = "PE"
                    elif "FUT" in opt_val: opt_val = "FUT"
                    else: opt_val = "EQ"

                    t_INSTRUMENT_MAP[f"{exch}:{tsym}"] = token
                    t_TOKEN_EXPIRY_MAP[token] = exp_raw

                    sym_key = f"{exch}|{name}|{exp_str}|{strike_val}|{opt_val}"
                    t_GLOBAL_SYMBOL_MAP[sym_key] = {"tradingsymbol": tsym, "instrument_token": token}

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
                        t_GLOBAL_INSTRUMENT_META[name] = {"lot_size": lot, "strikes": set()}
                    if strike_val > 0:
                        t_GLOBAL_INSTRUMENT_META[name]["strikes"].add(strike_val)

                for k in t_GLOBAL_EXPIRIES:
                    t_GLOBAL_EXPIRIES[k] = sorted(list(t_GLOBAL_EXPIRIES[k]))
                for k, v in t_GLOBAL_INSTRUMENT_META.items():
                    strikes = sorted(list(v["strikes"]))
                    step = 50
                    if len(strikes) > 1:
                        diffs = [round(strikes[i + 1] - strikes[i], 2) for i in range(len(strikes) - 1)]
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

                if "NSE:NIFTY 50" in INSTRUMENT_MAP:
                    STRATEGY_CONFIG["master_und_token"] = INSTRUMENT_MAP["NSE:NIFTY 50"]

                log_event(f"Instruments Ready: {len(INSTRUMENT_MAP)} tokens mapped.")
                break
            except Exception as e:
                log_event(f"DB Error: {str(e)[:40]}")
                time.sleep(5)

    def norm_cdf(x):
        return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

    def norm_pdf(x):
        return math.exp(-(x**2) / 2.0) / math.sqrt(2.0 * math.pi)

    def get_fractional_dte(exch, exp_date_str, ref_dt=None):
        try:
            if not exp_date_str: return 0.002
            exp_date = datetime.datetime.strptime(exp_date_str, "%Y-%m-%d").date()
            exp_time = datetime.time(23, 30) if exch == "MCX" else (datetime.time(17, 0) if exch == "CDS" else datetime.time(15, 30))
            exp_dt = IST.localize(datetime.datetime.combine(exp_date, exp_time))
            curr_dt = ref_dt if ref_dt else datetime.datetime.now(IST)
            return max(0.001, (exp_dt - curr_dt).total_seconds() / 86400.0) / 365.0
        except Exception:
            return 0.002

    def calc_iv(cp_flag, S_or_F, K, T, r, price, is_future=False):
        if T <= 0 or S_or_F <= 0 or K <= 0 or price <= 0: return 0.0
        drift_r = 0.0 if is_future else r
        sigma = 0.3
        for _ in range(50):
            try:
                d1 = (math.log(S_or_F / K) + (drift_r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
                d2 = d1 - sigma * math.sqrt(T)
                df = math.exp(-r * T)
                if is_future:
                    est_price = df * (S_or_F * norm_cdf(d1) - K * norm_cdf(d2)) if cp_flag == "CE" else df * (K * norm_cdf(-d2) - S_or_F * norm_cdf(-d1))
                    vega = df * S_or_F * norm_pdf(d1) * math.sqrt(T)
                else:
                    est_price = S_or_F * norm_cdf(d1) - K * df * norm_cdf(d2) if cp_flag == "CE" else K * df * norm_cdf(-d2) - S_or_F * norm_cdf(-d1)
                    vega = S_or_F * norm_pdf(d1) * math.sqrt(T)
                diff = price - est_price
                if abs(diff) < 1e-4 or vega < 1e-4: break
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
            res = KITE_SESSION.get(url, params=params, headers={"authorization": f"enctoken {API_CONFIG['enc_token']}"}, timeout=5)
            DIAGNOSTICS["last_rest_ping"] = datetime.datetime.now(IST).strftime("%H:%M:%S")
            if res.status_code == 200:
                DIAGNOSTICS["rest_history_status"] = f"SUCCESS ({token})"
                data = res.json().get("data", {}).get("candles", [])
                history_dict = {}
                for row in data:
                    try:
                        dt = datetime.datetime.strptime(row[0][:19], "%Y-%m-%dT%H:%M:%S")
                        history_dict[IST.localize(dt)] = float(row[4])
                    except Exception:
                        pass
                return history_dict
            else:
                DIAGNOSTICS["rest_history_status"] = f"FAILED HTTP {res.status_code}"
        except Exception as e:
            DIAGNOSTICS["rest_history_status"] = f"ERR: {str(e)[:15]}"
        return {}

    def rebuild_historical_chart():
        global CHART_LABELS, CHART_PREMIUM, CHART_IV, CHART_VWAP, CHART_MASTER, CHART_LEGS, CHART_PNL, CHART_MEAN, LAST_CHART_UPDATE
        active_legs = [l for l in STRATEGY_LEGS if l.get("enabled", True)]
        master_token = STRATEGY_CONFIG.get("master_und_token")
        if not active_legs or not master_token:
            reset_chart()
            return
        log_event("Rebuilding Intraday Chart...")

        master_dict = fetch_history(master_token)
        if not master_dict: return

        leg_dicts = {}
        for token in list(set([l["token"] for l in active_legs])):
            ld = fetch_history(token)
            if ld: leg_dicts[token] = ld

        if not leg_dicts: return
        all_timestamps = set(master_dict.keys())
        for ld in leg_dicts.values(): all_timestamps.update(ld.keys())
        sorted_timestamps = sorted(list(all_timestamps))

        last_known = {"master": 0.0}
        for t in leg_dicts.keys(): last_known[t] = 0.0

        final_rows = []
        for dt in sorted_timestamps:
            if dt in master_dict: last_known["master"] = master_dict[dt]
            for t in leg_dicts.keys():
                if dt in leg_dicts[t]: last_known[t] = leg_dicts[t]
            if all(v > 0 for v in last_known.values()):
                final_rows.append((dt, dict(last_known)))

        final_rows = final_rows[-2000:]
        t_labels, t_prem, t_iv, t_vwap, t_master, t_pnl, t_mean = [], [], [], [], [], [], []
        t_legs = {l["tradingsymbol"]: [] for l in active_legs}
        rf = float(STRATEGY_CONFIG.get("risk_free_rate", 7.0)) / 100.0
        master_sym = STRATEGY_CONFIG.get("master_und_sym", "")

        for dt, row_vals in final_rows:
            master_ltp = row_vals["master"]
            c_prem = 0.0
            ivs = []

            for l in active_legs:
                sym = l["tradingsymbol"]
                leg_px = row_vals.get(l["token"], 0.0)
                t_legs[sym].append(round(leg_px, 2))
                if leg_px > 0:
                    c_prem += leg_px if l.get("transaction_type", "SELL") == "SELL" else -leg_px
                    if l.get("opt_type") in ["CE", "PE"] and l.get("strike", 0) > 0 and l.get("exp_date"):
                        dte = get_fractional_dte(l["exchange"], l["exp_date"], dt)
                        if dte > 0 and master_ltp > 0:
                            iv = calc_iv(l["opt_type"], master_ltp, l["strike"], dte, rf, leg_px, (l.get("exchange") == "MCX") or ("FUT" in master_sym))
                            if iv > 0: ivs.append(iv)

            t_labels.append(dt.strftime("%d %b %H:%M"))
            t_prem.append(round(abs(c_prem), 2))
            t_iv.append(round(sum(ivs) / len(ivs) if ivs else 0.0, 2))
            t_vwap.append(round(abs(c_prem), 2))
            t_master.append(round(master_ltp, 2))
            t_pnl.append(0.0)
            t_mean.append(0.0)

        CHART_LABELS, CHART_PREMIUM, CHART_IV = t_labels, t_prem, t_iv
        CHART_VWAP, CHART_MASTER, CHART_LEGS, CHART_PNL, CHART_MEAN = t_vwap, t_master, t_legs, t_pnl, t_mean
        LAST_CHART_UPDATE = time.time()
        log_event("Historical Telemetry Synced.")

    def fire_order(token, exch, sym, action, qty, prod, ltp, prot_pct, requested_type="SMART"):
        if not API_CONFIG["is_connected"]: return
        limit_price, final_order_type, tick = 0, "MARKET", 0.05

        if exch == "MCX": tick = 0.05 if sym.endswith(("CE", "PE")) else (0.10 if "NATGAS" in sym else 1.0)
        elif exch == "CDS": tick = 0.0025
        elif exch == "BSE": tick = 0.01

        is_mcx_opt = exch == "MCX" and sym.endswith(("CE", "PE"))
        if is_mcx_opt and requested_type == "MARKET": requested_type = "PROTECTED"

        if requested_type == "SMART":
            depth = LIVE_LEG_DEPTH.get(token, {})
            if action == "BUY" and depth.get("sell") and depth["sell"][0]["price"] > 0:
                limit_price = depth["sell"][0]["price"] + (tick * 3)
            elif action == "SELL" and depth.get("buy") and depth["buy"][0]["price"] > 0:
                limit_price = depth["buy"][0]["price"] - (tick * 3)

            if limit_price > 0:
                limit_price = round(round(limit_price / tick) * tick, 4)
                final_order_type = "LIMIT"
            else:
                requested_type = "PROTECTED"

        if requested_type == "PROTECTED" or (requested_type == "MARKET" and is_mcx_opt):
            if ltp == 0: ltp = LIVE_LEG_PRICES.get(token, 0.0)
            if ltp > 0:
                buf = max(prot_pct, 1.0) / 100.0
                raw_price = ltp * (1 + buf) if action == "BUY" else ltp * (1 - buf)
                limit_price = round(round(max(raw_price, tick) / tick) * tick, 4)
                final_order_type = "LIMIT"
            elif is_mcx_opt:
                log_event(f"REJECT ({sym}): Market Order blocked on MCX Option.")
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
        log_event(f"FIRE: {action} {qty}x {sym} @ {final_order_type} {limit_price if limit_price > 0 else ''}")

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
            log_event(f"ERR ({sym}): {str(e)[:40]}")

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
        for th in threads: th.start()
        for th in threads: th.join()
        STRATEGY_CONFIG["armed"] = False

    def trigger_all_portfolio_exits():
        global ORDER_FIRED
        ORDER_FIRED = True
        globals()["LAST_EXIT_FIRE_TIME"] = time.time()
        threads = []
        for t, p in ACTIVE_POSITIONS.items():
            action = "SELL" if p["type"] == "LONG" else "BUY"
            ltp = LIVE_LEG_PRICES.get(t, p["entry_price"])
            exit_order_type = "PROTECTED" if p["exchange"] == "MCX" or p["symbol"].endswith(("CE", "PE")) else "MARKET"
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
        for th in threads: th.join()

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
                    if "last_price" in tick: LIVE_MASTER_UND_LTP = tick["last_price"]
                    if "average_traded_price" in tick: LIVE_MASTER_UND_VWAP = tick["average_traded_price"]
                if "last_price" in tick: LIVE_LEG_PRICES[token] = tick["last_price"]
                if "average_traded_price" in tick: LIVE_LEG_VWAP[token] = tick["average_traded_price"]
                if "depth" in tick: LIVE_LEG_DEPTH[token] = tick["depth"]

                enabled_legs = [l for l in STRATEGY_LEGS if l.get("enabled", True)]
                combo_valid = len(enabled_legs) > 0 and all(LIVE_LEG_PRICES.get(l["token"], 0) > 0 for l in enabled_legs)

                if combo_valid:
                    CURRENT_COMBO_PREMIUM = abs(sum(
                        (LIVE_LEG_PRICES.get(l["token"], 0) if l.get("transaction_type", "SELL") == "SELL" else -LIVE_LEG_PRICES.get(l["token"], 0))
                        for l in enabled_legs
                    ))
                    CURRENT_COMBO_VWAP = abs(sum(
                        (LIVE_LEG_VWAP.get(l["token"], 0) if l.get("transaction_type", "SELL") == "SELL" else -LIVE_LEG_VWAP.get(l["token"], 0))
                        for l in enabled_legs
                    ))
                    CURRENT_GAP = CURRENT_COMBO_PREMIUM - CURRENT_COMBO_VWAP
                    CURRENT_PREM_DIFF = abs(LIVE_LEG_PRICES.get(enabled_legs[0]["token"], 0) - LIVE_LEG_PRICES.get(enabled_legs[1]["token"], 0)) if len(enabled_legs) >= 2 else 0.0

                    ivs = []
                    for l in enabled_legs:
                        if l.get("opt_type") in ["CE", "PE"] and l.get("strike", 0) > 0 and l.get("exp_date"):
                            dte = get_fractional_dte(l["exchange"], l["exp_date"])
                            calc_master = LIVE_MASTER_UND_LTP if LIVE_MASTER_UND_LTP > 0 else l.get("strike", 0)
                            if dte > 0 and calc_master > 0:
                                iv = calc_iv(l["opt_type"], calc_master, l["strike"], dte, float(STRATEGY_CONFIG.get("risk_free_rate", 7.0)) / 100.0, LIVE_LEG_PRICES[l["token"]], (l.get("exchange") == "MCX") or ("FUT" in STRATEGY_CONFIG.get("master_und_sym", "")))
                                if iv > 0: ivs.append(iv)
                    CURRENT_COMBO_IV = sum(ivs) / len(ivs) if ivs else 0.0
                else:
                    CURRENT_COMBO_PREMIUM, CURRENT_COMBO_VWAP, CURRENT_GAP, CURRENT_PREM_DIFF, CURRENT_COMBO_IV = 0.0, 0.0, 0.0, 0.0, 0.0

                curr_time = time.time()
                if curr_time - LAST_CHART_UPDATE > 10.0 and combo_valid:
                    CHART_LABELS.append(datetime.datetime.now(IST).strftime("%d %b %H:%M"))
                    CHART_PREMIUM.append(CURRENT_COMBO_PREMIUM)
                    CHART_IV.append(CURRENT_COMBO_IV)
                    CHART_VWAP.append(CURRENT_COMBO_VWAP)
                    CHART_MASTER.append(LIVE_MASTER_UND_LTP)
                    CHART_PNL.append(NET_PORTFOLIO_PNL)
                    LAST_CHART_UPDATE = curr_time

                if len(enabled_legs) > 0 and STRATEGY_CONFIG["armed"] and not STRATEGY_CONFIG["fired"]:
                    active_evals = []
                    if STRATEGY_CONFIG["use_premium_cond"] and combo_valid:
                        c, tgt = STRATEGY_CONFIG["condition"], STRATEGY_CONFIG["target_premium"]
                        trig = (c == ">=" and CURRENT_COMBO_PREMIUM >= tgt) or (c == "<=" and CURRENT_COMBO_PREMIUM <= tgt) or (c == ">" and CURRENT_COMBO_PREMIUM > tgt) or (c == "<" and CURRENT_COMBO_PREMIUM < tgt)
                        active_evals.append((STRATEGY_CONFIG.get("prem_gate", "AND"), trig))

                    if STRATEGY_CONFIG["use_diff_cond"] and combo_valid:
                        active_evals.append((STRATEGY_CONFIG.get("diff_gate", "AND"), CURRENT_PREM_DIFF <= STRATEGY_CONFIG["diff_target"]))

                    if STRATEGY_CONFIG["use_vwap_cond"] and combo_valid:
                        d = STRATEGY_CONFIG["vwap_direction"]
                        trig = (d == ">" and CURRENT_COMBO_PREMIUM > CURRENT_COMBO_VWAP) or (d == "<" and CURRENT_COMBO_PREMIUM < CURRENT_COMBO_VWAP)
                        active_evals.append((STRATEGY_CONFIG.get("vwap_gate", "AND"), trig))

                    if STRATEGY_CONFIG["use_time_cond"]:
                        try:
                            t_str = STRATEGY_CONFIG["target_time"]
                            if len(t_str.split(":")) == 2: t_str += ":00"
                            active_evals.append((STRATEGY_CONFIG.get("time_gate", "AND"), datetime.datetime.now(IST).time() >= datetime.datetime.strptime(t_str, "%H:%M:%S").time()))
                        except Exception:
                            active_evals.append((STRATEGY_CONFIG.get("time_gate", "AND"), False))

                    if STRATEGY_CONFIG["use_underlying_cond"] and STRATEGY_CONFIG["master_und_token"]:
                        ul, tg, c = LIVE_MASTER_UND_LTP, STRATEGY_CONFIG["und_target"], STRATEGY_CONFIG["und_cond"]
                        trig = ul > 0 and ((c == ">=" and ul >= tg) or (c == "<=" and ul <= tg) or (c == ">" and ul > tg) or (c == "<" and ul < tg))
                        active_evals.append((STRATEGY_CONFIG.get("und_ltp_gate", "AND"), trig))

                    if active_evals:
                        final_trigger = active_evals[0][1]
                        for gate, res in active_evals[1:]:
                            final_trigger = (final_trigger and res) if gate == "AND" else (final_trigger or res)
                        if final_trigger:
                            STRATEGY_CONFIG["fired"] = True
                            log_event("STRATEGY TRIGGERED! Executing Orders...")
                            execute_multi_leg_strategy()

                if token in ACTIVE_POSITIONS and "last_price" in tick:
                    if ORDER_FIRED and "LAST_EXIT_FIRE_TIME" in globals() and time.time() - globals()["LAST_EXIT_FIRE_TIME"] > 15.0:
                        ORDER_FIRED = False

                    if not ORDER_FIRED:
                        current_pnl, all_legs_ticked = 0.0, True
                        for t, p in ACTIVE_POSITIONS.items():
                            ltp = LIVE_LEG_PRICES.get(t, 0.0)
                            if ltp == 0:
                                all_legs_ticked = False
                                break
                            current_pnl += ((ltp - p["entry_price"]) * p["qty"] * p["multiplier"]) if p["type"] == "LONG" else ((p["entry_price"] - ltp) * p["qty"] * p["multiplier"])

                        if all_legs_ticked:
                            NET_PORTFOLIO_PNL = current_pnl
                            if CURRENT_ACTIVE_SL is None or not RISK_CONFIG["tsl_enabled"]:
                                CURRENT_ACTIVE_SL = RISK_CONFIG["stoploss_pnl"]
                            if RISK_CONFIG["tsl_enabled"] and NET_PORTFOLIO_PNL > 0:
                                if (NET_PORTFOLIO_PNL - RISK_CONFIG["tsl_gap"]) > CURRENT_ACTIVE_SL:
                                    CURRENT_ACTIVE_SL = NET_PORTFOLIO_PNL - RISK_CONFIG["tsl_gap"]
                            if CURRENT_ACTIVE_SL < RISK_CONFIG["stoploss_pnl"]:
                                CURRENT_ACTIVE_SL = RISK_CONFIG["stoploss_pnl"]

                            boot_safe = time.time() - SYSTEM_START_TIME > 5.0
                            time_exit_met = False
                            if RISK_CONFIG.get("time_exit_enabled"):
                                try:
                                    t_str = RISK_CONFIG["time_exit_target"]
                                    if len(t_str.split(":")) == 2: t_str += ":00"
                                    if datetime.datetime.now(IST).time() >= datetime.datetime.strptime(t_str, "%H:%M:%S").time():
                                        time_exit_met = True
                                except Exception:
                                    pass

                            if RISK_CONFIG["panic_exit"] and boot_safe:
                                trigger_all_portfolio_exits()
                                RISK_CONFIG["panic_exit"] = False
                            elif boot_safe:
                                if time_exit_met:
                                    RISK_CONFIG["time_exit_enabled"] = False
                                    log_event("TIME EXIT TRIGGERED: Squareoff.")
                                    trigger_all_portfolio_exits()
                                elif RISK_CONFIG["auto_squareoff"]:
                                    if NET_PORTFOLIO_PNL >= RISK_CONFIG["target_pnl"] or NET_PORTFOLIO_PNL <= CURRENT_ACTIVE_SL:
                                        log_event(f"RISK TRIGGERED (P&L: {NET_PORTFOLIO_PNL:.2f}): Squareoff.")
                                        trigger_all_portfolio_exits()

    def on_open(ws):
        global DIAGNOSTICS
        DIAGNOSTICS["ws_status"] = "CONNECTED"
        log_event("WebSocket Online.")
        sub_tokens = [l["token"] for l in STRATEGY_LEGS if l.get("enabled", True) and "token" in l]
        if STRATEGY_CONFIG.get("master_und_token"): sub_tokens.append(STRATEGY_CONFIG["master_und_token"])
        sub_tokens.extend(list(ACTIVE_POSITIONS.keys()))
        unique = list(set(sub_tokens))
        if unique:
            try:
                ws.send(json.dumps({"a": "subscribe", "v": unique}))
                ws.send(json.dumps({"a": "mode", "v": ["full", unique]}))
            except Exception: pass

    def on_error(ws, err):
        log_event(f"WS Error: {err}")

    def on_close(ws, c, m):
        DIAGNOSTICS["ws_status"] = "DISCONNECTED"

    def start_websocket_stream():
        global stealth_ws
        while True:
            try:
                if API_CONFIG["is_connected"]:
                    encoded_token = urllib.parse.quote(urllib.parse.unquote(API_CONFIG["enc_token"]))
                    ws_url = (
                        "wss://ws.zerodha.com/?api_key=kitefront"
                        f"&user_id={API_CONFIG['user_id']}"
                        f"&enctoken={encoded_token}"
                        f"&uid={int(time.time()*1000)}"
                        "&user-agent=kite3-web&version=3.0.0"
                    )
                    
                    stealth_ws = websocket.WebSocketApp(
                        ws_url,
                        header={"User-Agent": "Mozilla/5.0"},
                        on_open=on_open,
                        on_message=on_message,
                        on_error=on_error,
                        on_close=on_close,
                    )
                    
                    # Bypassing Android SSL validation to allow our Monkey-Patch to connect safely
                    stealth_ws.run_forever(
                        ping_interval=30, 
                        ping_timeout=10,
                        sslopt={"cert_reqs": ssl.CERT_NONE}
                    )
            except Exception as e: 
                log_event(f"WS Outer Loop Error: {str(e)[:30]}")
            time.sleep(5)

    def portfolio_sync_thread():
        global ACTIVE_POSITIONS
        while True:
            time.sleep(10)
            if not API_CONFIG["is_connected"]: continue
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
                    if tokens_to_sub and stealth_ws and stealth_ws.sock and stealth_ws.sock.connected:
                        stealth_ws.send(json.dumps({"a": "subscribe", "v": tokens_to_sub}))
                        stealth_ws.send(json.dumps({"a": "mode", "v": ["full", tokens_to_sub]}))
            except Exception: pass

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
            body { background-color: #0b0c10; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #c5c6c7; }
            .card { background-color: #1f2833 !important; border-color: #45a29e; border-radius: 8px; }
            .text-cyan { color: #66fcf1; }
            .table-dark { background-color: #1f2833 !important; }
            .table-hover tbody tr:hover { background-color: #2b3a4a !important; }
            .logs-window { height: 180px; overflow-y: auto; background-color: #000; color: #0f0; font-family: monospace; font-size: 0.8rem; padding: 10px; border-radius: 4px; }
            .form-control, .form-select { background-color: #0b0c10; color: #66fcf1; border: 1px solid #45a29e; }
            .form-control:focus, .form-select:focus { background-color: #0b0c10; color: #66fcf1; border-color: #66fcf1; box-shadow: 0 0 5px rgba(102, 252, 241, 0.5); }
            .nav-tabs .nav-link { color: #888; }
            .nav-tabs .nav-link.active { background-color: #1f2833; color: #66fcf1; border-color: #45a29e #45a29e #1f2833; font-weight: bold; }
        </style>
    </head>
    <body class="container-fluid py-2">
        <nav class="navbar navbar-dark mb-3 rounded px-3 py-2" style="background-color: #1f2833; border-bottom: 2px solid #66fcf1;">
          <div class="container-fluid p-0">
            <span class="navbar-brand fw-bold text-cyan mb-0">Garua Engine V25.8</span>
            <div class="d-flex text-white align-items-center">
               <span id="timeBadge" class="badge bg-secondary me-2">--:--:--</span>
               <span id="wsBadge" class="badge bg-danger me-2">WS: DISCONNECTED</span>
               <span id="apiBadge" class="badge bg-danger me-2">API: DISCONNECTED</span>
               <button class="btn btn-sm btn-outline-success fw-bold" data-bs-toggle="modal" data-bs-target="#loginModal">🔑 LOGIN</button>
            </div>
          </div>
        </nav>

        <div class="row g-2 mb-3">
             <div class="col-6 col-md-3">
               <div class="card h-100 shadow-sm text-center p-2">
                   <small class="text-muted fw-bold">NET P&L</small>
                   <h3 id="netPnl" class="fw-bold my-1">₹0.00</h3>
                   <small class="text-muted">SL: <span id="activeSl" class="text-danger">0.00</span></small>
               </div>
             </div>
             <div class="col-6 col-md-3">
               <div class="card h-100 shadow-sm text-center p-2">
                   <small class="text-muted fw-bold">COMBO PREMIUM</small>
                   <h3 id="comboPrem" class="text-cyan fw-bold my-1">0.00</h3>
                   <small class="text-muted">VWAP: <span id="comboVwap">0.00</span> | Gap: <span id="comboGap">0.00</span></small>
               </div>
             </div>
             <div class="col-6 col-md-3">
               <div class="card h-100 shadow-sm text-center p-2">
                   <small class="text-muted fw-bold">MASTER (LTP)</small>
                   <h3 id="masterLtp" class="text-white fw-bold my-1" style="color:#c5a8ff !important;">0.00</h3>
                   <small class="text-muted">VWAP: <span id="masterVwap">0.00</span></small>
               </div>
             </div>
             <div class="col-6 col-md-3">
               <div class="card h-100 shadow-sm text-center p-2">
                   <small class="text-muted fw-bold">COMBO IV</small>
                   <h3 id="comboIv" class="text-warning fw-bold my-1">0.0%</h3>
                   <small class="text-muted">Spread: <span id="premDiff">0.00</span></small>
               </div>
             </div>
        </div>

        <div class="card shadow-sm mb-3">
           <div class="card-body d-flex flex-wrap justify-content-between align-items-center py-2">
              <div>
                 <button class="btn btn-sm btn-outline-info me-2 fw-bold" onclick="importPositions()">📥 IMPORT POSITIONS</button>
                 <button id="armBtn" class="btn btn-sm btn-outline-warning me-2 fw-bold" onclick="toggleArm()">⚡ ARM STRATEGY</button>
              </div>
              <div>
                 <button class="btn btn-sm btn-danger fw-bold" onclick="panicExit()">🛑 PANIC EXIT ALL</button>
              </div>
           </div>
        </div>

        <ul class="nav nav-tabs mb-3 border-secondary" id="engineTabs" role="tablist">
          <li class="nav-item"><button class="nav-link active" id="telemetry-tab" data-bs-toggle="tab" data-bs-target="#tab-telemetry" type="button">📊 Telemetry & Positions</button></li>
          <li class="nav-item"><button class="nav-link" id="builder-tab" data-bs-toggle="tab" data-bs-target="#tab-builder" type="button">🛠️ Leg Builder</button></li>
          <li class="nav-item"><button class="nav-link" id="risk-tab" data-bs-toggle="tab" data-bs-target="#tab-risk" type="button">🛡️ Risk & Multi-Gate</button></li>
        </ul>

        <div class="tab-content" id="engineTabsContent">
          <!-- TAB 1: TELEMETRY -->
          <div class="tab-pane fade show active" id="tab-telemetry" role="tabpanel">
             <div class="row g-2">
               <div class="col-12">
                  <div class="card shadow-sm mb-2">
                     <div class="card-header border-secondary py-1 text-cyan fw-bold">Live Multi-Axis Telemetry</div>
                     <div class="card-body p-2" style="background-color: #0b0c10;">
                        <canvas id="algoChart" style="height: 300px; width: 100%;"></canvas>
                     </div>
                  </div>
               </div>
               <div class="col-12">
                  <div class="card shadow-sm mb-2">
                     <div class="card-header border-secondary py-1 text-success fw-bold">Active Live Positions</div>
                     <div class="card-body p-0 table-responsive">
                        <table class="table table-dark table-hover mb-0 text-center align-middle" style="font-size: 0.8rem;">
                           <thead class="text-muted">
                              <tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Entry</th><th>LTP</th><th>P&L</th><th>IV</th><th>Delta</th></tr>
                           </thead>
                           <tbody id="livePositionsBody">
                              <tr><td colspan="8" class="text-muted py-2">No active positions.</td></tr>
                           </tbody>
                        </table>
                     </div>
                  </div>
               </div>
               <div class="col-12">
                  <div class="card shadow-sm">
                     <div class="card-header border-secondary py-1 text-light fw-bold">Execution Logs</div>
                     <div class="card-body p-0">
                        <div class="logs-window" id="logsContainer"><div>> Initializing engine...</div></div>
                     </div>
                  </div>
               </div>
             </div>
          </div>

          <!-- TAB 2: LEG BUILDER -->
          <div class="tab-pane fade" id="tab-builder" role="tabpanel">
             <div class="card shadow-sm mb-3">
               <div class="card-header border-secondary text-cyan fw-bold">Add New Leg</div>
               <div class="card-body">
                  <div class="row g-2">
                     <div class="col-6 col-md-2">
                        <label class="form-label small">Exchange</label>
                        <select id="legExch" class="form-select form-select-sm"><option value="NFO">NFO</option><option value="BFO">BFO</option><option value="MCX">MCX</option><option value="CDS">CDS</option></select>
                     </div>
                     <div class="col-6 col-md-3">
                        <label class="form-label small">Tradingsymbol</label>
                        <input type="text" id="legSym" class="form-control form-control-sm" placeholder="e.g. NIFTY26SEP24000CE">
                     </div>
                     <div class="col-6 col-md-2">
                        <label class="form-label small">Side</label>
                        <select id="legSide" class="form-select form-select-sm"><option value="SELL">SELL</option><option value="BUY">BUY</option></select>
                     </div>
                     <div class="col-6 col-md-2">
                        <label class="form-label small">Quantity</label>
                        <input type="number" id="legQty" class="form-control form-control-sm" value="75">
                     </div>
                     <div class="col-6 col-md-3">
                        <label class="form-label small">Order Type</label>
                        <select id="legOrderType" class="form-select form-select-sm"><option value="SMART">SMART (Best Limit)</option><option value="MARKET">MARKET</option><option value="PROTECTED">PROTECTED LIMIT</option></select>
                     </div>
                     <div class="col-12 text-end mt-2">
                        <button class="btn btn-sm btn-info fw-bold" onclick="addLeg()">➕ Add Leg</button>
                        <button class="btn btn-sm btn-outline-danger ms-2" onclick="clearLegs()">Clear All</button>
                     </div>
                  </div>
               </div>
             </div>
             <div class="card shadow-sm">
                <div class="card-header border-secondary text-warning fw-bold">Active Strategy Legs</div>
                <div class="card-body p-0 table-responsive">
                   <table class="table table-dark table-hover mb-0 text-center align-middle" style="font-size: 0.85rem;">
                      <thead class="text-muted">
                         <tr><th>Status</th><th>Symbol</th><th>Side</th><th>Qty</th><th>LTP</th><th>Actions</th></tr>
                      </thead>
                      <tbody id="stratLegsBody">
                         <tr><td colspan="6" class="text-muted py-2">No legs loaded.</td></tr>
                      </tbody>
                   </table>
                </div>
             </div>
          </div>

          <!-- TAB 3: RISK & GATES -->
          <div class="tab-pane fade" id="tab-risk" role="tabpanel">
             <div class="row g-2">
               <div class="col-12 col-md-6">
                  <div class="card shadow-sm h-100">
                     <div class="card-header border-secondary text-cyan fw-bold">Portfolio Risk Control</div>
                     <div class="card-body">
                        <div class="mb-2">
                           <label class="form-label small">Target Profit (₹)</label>
                           <input type="number" id="riskTarget" class="form-control form-control-sm" value="2000">
                        </div>
                        <div class="mb-2">
                           <label class="form-label small">Max Stoploss (₹ Negative)</label>
                           <input type="number" id="riskSl" class="form-control form-control-sm" value="-1000">
                        </div>
                        <div class="form-check form-switch mb-2">
                           <input class="form-check-input" type="checkbox" id="riskTslToggle">
                           <label class="form-check-label small" for="riskTslToggle">Enable Trailing SL</label>
                        </div>
                        <div class="mb-2">
                           <label class="form-label small">TSL Gap (₹)</label>
                           <input type="number" id="riskTslGap" class="form-control form-control-sm" value="300">
                        </div>
                        <div class="form-check form-switch mb-2">
                           <input class="form-check-input" type="checkbox" id="riskSquareoffToggle" checked>
                           <label class="form-check-label small" for="riskSquareoffToggle">Auto Square-off when SL/TP Hit</label>
                        </div>
                        <button class="btn btn-sm btn-success fw-bold mt-2" onclick="saveRisk()">Save Risk Settings</button>
                     </div>
                  </div>
               </div>
               <div class="col-12 col-md-6">
                  <div class="card shadow-sm h-100">
                     <div class="card-header border-secondary text-warning fw-bold">Multi-Gate Trigger Logic</div>
                     <div class="card-body">
                        <div class="form-check form-switch mb-2">
                           <input class="form-check-input" type="checkbox" id="gatePremToggle">
                           <label class="form-check-label small" for="gatePremToggle">Trigger on Combo Premium</label>
                        </div>
                        <div class="input-group input-group-sm mb-2">
                           <select id="gatePremCond" class="form-select" style="max-width: 90px;"><option value=">=">&gt;=</option><option value="<=">&lt;=</option></select>
                           <input type="number" id="gatePremVal" class="form-control" value="150">
                        </div>
                        <div class="form-check form-switch mb-2">
                           <input class="form-check-input" type="checkbox" id="gateTimeToggle">
                           <label class="form-check-label small" for="gateTimeToggle">Trigger at Specific Time</label>
                        </div>
                        <div class="mb-2">
                           <input type="time" id="gateTimeVal" class="form-control form-control-sm" value="09:20">
                        </div>
                        <div class="form-check form-switch mb-2">
                           <input class="form-check-input" type="checkbox" id="gateVwapToggle">
                           <label class="form-check-label small" for="gateVwapToggle">Trigger on VWAP Crossover</label>
                        </div>
                        <select id="gateVwapDir" class="form-select form-select-sm mb-2"><option value="<">Premium &lt; VWAP</option><option value=">">Premium &gt; VWAP</option></select>
                        <button class="btn btn-sm btn-warning fw-bold mt-2" onclick="saveStrategy()">Save Trigger Conditions</button>
                     </div>
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
                  <label class="small">User ID</label>
                  <input type="text" id="inputUserId" class="form-control bg-dark text-white border-secondary">
                </div>
                <div class="mb-3">
                  <label class="small">ENCTOKEN</label>
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
                apiB.className = data.api_connected ? 'badge bg-success me-2' : 'badge bg-danger me-2';
                const wsB = document.getElementById('wsBadge');
                const wsStatus = data.diagnostics.api.ws_status || 'DISCONNECTED';
                wsB.innerText = 'WS: ' + wsStatus;
                wsB.className = wsStatus === 'CONNECTED' ? 'badge bg-success me-2' : 'badge bg-danger me-2';
                
                const pnlStr = data.pnl.toFixed(2);
                const pnlEl = document.getElementById('netPnl');
                pnlEl.innerText = (data.pnl >= 0 ? '+₹' : '-₹') + Math.abs(pnlStr);
                pnlEl.className = data.pnl >= 0 ? 'text-success fw-bold my-1' : 'text-danger fw-bold my-1';
                
                document.getElementById('activeSl').innerText = data.active_sl.toFixed(2);
                document.getElementById('comboPrem').innerText = data.premium.toFixed(2);
                document.getElementById('comboVwap').innerText = data.vwap.toFixed(2);
                document.getElementById('comboGap').innerText = data.gap.toFixed(2);
                document.getElementById('masterLtp').innerText = data.master_ltp.toFixed(2);
                document.getElementById('masterVwap').innerText = data.master_vwap.toFixed(2);
                document.getElementById('comboIv').innerText = data.combo_iv.toFixed(2) + '%';
                document.getElementById('premDiff').innerText = data.prem_diff.toFixed(2);

                const armBtn = document.getElementById('armBtn');
                if(data.strat.armed) {
                    armBtn.className = 'btn btn-sm btn-warning me-2 fw-bold shadow';
                    armBtn.innerText = '⚠️ ARMED (CLICK TO DISARM)';
                } else {
                    armBtn.className = 'btn btn-sm btn-outline-warning me-2 fw-bold';
                    armBtn.innerText = '⚡ ARM STRATEGY';
                }

                if (data.chart.labels.length > 0) {
                    chartObj.data.labels = data.chart.labels;
                    chartObj.data.datasets[0].data = data.chart.premium;
                    chartObj.data.datasets[1].data = data.chart.vwap;
                    chartObj.data.datasets[2].data = data.chart.master;
                    chartObj.data.datasets[3].data = data.chart.pnl;
                    chartObj.update();
                }

                let legsHtml = '';
                data.legs.forEach((l, idx) => {
                    const sideColor = l.type === 'BUY' ? 'text-primary' : 'text-danger';
                    const statusBadge = l.enabled ? '<span class="badge bg-success">ON</span>' : '<span class="badge bg-secondary">OFF</span>';
                    legsHtml += `<tr>
                        <td><button class="btn btn-sm p-0" onclick="toggleLeg(${idx})">${statusBadge}</button></td>
                        <td class="fw-bold">${l.symbol}</td>
                        <td class="${sideColor} fw-bold">${l.type}</td>
                        <td>${l.qty}</td>
                        <td class="text-cyan">${l.ltp.toFixed(2)}</td>
                        <td><button class="btn btn-sm btn-outline-danger py-0 px-1" onclick="deleteLeg(${idx})">✕</button></td>
                    </tr>`;
                });
                document.getElementById('stratLegsBody').innerHTML = legsHtml || '<tr><td colspan="6" class="text-muted py-2">No legs loaded.</td></tr>';

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
                document.getElementById('livePositionsBody').innerHTML = posHtml || '<tr><td colspan="8" class="text-muted py-2">No active positions synced.</td></tr>';

                const logsDiv = document.getElementById('logsContainer');
                if(data.logs && data.logs.length > 0) {
                    logsDiv.innerHTML = data.logs.map(log => `<div>> ${log}</div>`).join('');
                }
            } catch (err) {}
        }

        async function submitAuth() {
            const uid = document.getElementById('inputUserId').value.trim();
            const enc = document.getElementById('inputEncToken').value.trim();
            if(!uid || !enc) return alert("Please fill both User ID and ENCTOKEN");
            const res = await fetch('/api/auth', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({user_id: uid, enc_token: enc})
            });
            const d = await res.json();
            alert(d.message);
            bootstrap.Modal.getInstance(document.getElementById('loginModal')).hide();
        }

        async function addLeg() {
            const exch = document.getElementById('legExch').value;
            const sym = document.getElementById('legSym').value.trim().toUpperCase();
            const side = document.getElementById('legSide').value;
            const qty = parseInt(document.getElementById('legQty').value);
            const ord = document.getElementById('legOrderType').value;
            if(!sym || !qty) return alert("Provide valid symbol and quantity");
            const res = await fetch('/api/add_leg', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({exchange: exch, symbol: sym, transaction_type: side, quantity: qty, order_type: ord})
            });
            const d = await res.json();
            if(d.status !== 'ok') alert(d.message);
            document.getElementById('legSym').value = '';
        }

        async function toggleLeg(idx) { await fetch(`/api/toggle_leg/${idx}`, {method: 'POST'}); }
        async function deleteLeg(idx) { await fetch(`/api/delete_leg/${idx}`, {method: 'POST'}); }
        async function clearLegs() { await fetch('/api/clear_legs', {method: 'POST'}); }
        async function toggleArm() { await fetch('/api/arm_strategy', {method: 'POST'}); }
        async function panicExit() { if(confirm("Flatten all open positions immediately?")) await fetch('/api/panic_exit', {method: 'POST'}); }
        async function importPositions() {
            const res = await fetch('/api/import_positions', {method: 'POST'});
            const d = await res.json();
            alert(d.message || `Imported ${d.count} positions.`);
        }

        async function saveRisk() {
            await fetch('/api/update_risk', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    target_pnl: parseFloat(document.getElementById('riskTarget').value),
                    stoploss_pnl: parseFloat(document.getElementById('riskSl').value),
                    tsl_enabled: document.getElementById('riskTslToggle').checked,
                    tsl_gap: parseFloat(document.getElementById('riskTslGap').value),
                    auto_squareoff: document.getElementById('riskSquareoffToggle').checked
                })
            });
            alert("Risk configuration updated.");
        }

        async function saveStrategy() {
            await fetch('/api/update_strategy', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    use_premium_cond: document.getElementById('gatePremToggle').checked,
                    condition: document.getElementById('gatePremCond').value,
                    target_premium: parseFloat(document.getElementById('gatePremVal').value),
                    use_time_cond: document.getElementById('gateTimeToggle').checked,
                    target_time: document.getElementById('gateTimeVal').value,
                    use_vwap_cond: document.getElementById('gateVwapToggle').checked,
                    vwap_direction: document.getElementById('gateVwapDir').value
                })
            });
            alert("Trigger conditions saved.");
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
        log_event(f"User {API_CONFIG['user_id']} authenticated.")
        return jsonify({"status": "success", "message": "Credentials verified! Engine streaming."})

    @app.route("/api/add_leg", methods=["POST"])
    def api_add_leg():
        data = request.json
        exch = data.get("exchange", "NFO")
        sym = data.get("symbol", "").strip().upper()
        key = f"{exch}:{sym}"
        token = INSTRUMENT_MAP.get(key)
        if not token:
            return jsonify({"status": "error", "message": f"Symbol {key} not found in master list."})

        opt_type = "CE" if sym.endswith("CE") else ("PE" if sym.endswith("PE") else ("FUT" if "FUT" in sym else "EQ"))
        strike = 0.0
        m = re.search(r"(\d+(?:\.\d+)?)(CE|PE)$", sym)
        if m: strike = float(m.group(1))

        exp_raw = TOKEN_EXPIRY_MAP.get(token, "")
        exp_date_str = str(exp_raw).split(" ")[0] if exp_raw else datetime.datetime.now(IST).strftime("%Y-%m-%d")

        STRATEGY_LEGS.append({
            "exchange": exch,
            "tradingsymbol": sym,
            "transaction_type": data.get("transaction_type", "SELL"),
            "quantity": int(data.get("quantity", 75)),
            "product": "NRML",
            "order_type": data.get("order_type", "SMART"),
            "opt_type": opt_type,
            "strike": strike,
            "exp_date": exp_date_str,
            "token": token,
            "enabled": True,
        })
        threading.Thread(target=rebuild_historical_chart, daemon=True).start()
        log_event(f"Leg Added: {sym}")
        return jsonify({"status": "ok"})

    @app.route("/api/delete_leg/<int:idx>", methods=["POST"])
    def api_delete_leg(idx):
        if 0 <= idx < len(STRATEGY_LEGS):
            removed = STRATEGY_LEGS.pop(idx)
            log_event(f"Removed Leg: {removed['tradingsymbol']}")
            threading.Thread(target=rebuild_historical_chart, daemon=True).start()
        return jsonify({"status": "ok"})

    @app.route("/api/toggle_leg/<int:idx>", methods=["POST"])
    def api_toggle_leg(idx):
        if 0 <= idx < len(STRATEGY_LEGS):
            STRATEGY_LEGS[idx]["enabled"] = not STRATEGY_LEGS[idx]["enabled"]
            threading.Thread(target=rebuild_historical_chart, daemon=True).start()
        return jsonify({"status": "ok"})

    @app.route("/api/clear_legs", methods=["POST"])
    def api_clear_legs():
        STRATEGY_LEGS.clear()
        reset_chart()
        log_event("All legs cleared.")
        return jsonify({"status": "ok"})

    @app.route("/api/update_risk", methods=["POST"])
    def api_update_risk():
        d = request.json
        RISK_CONFIG.update(d)
        log_event("Risk parameters updated.")
        return jsonify({"status": "ok"})

    @app.route("/api/update_strategy", methods=["POST"])
    def api_update_strategy():
        d = request.json
        STRATEGY_CONFIG.update(d)
        log_event("Trigger conditions updated.")
        return jsonify({"status": "ok"})

    @app.route("/api/arm_strategy", methods=["POST"])
    def api_arm_strategy():
        STRATEGY_CONFIG["armed"] = not STRATEGY_CONFIG["armed"]
        STRATEGY_CONFIG["fired"] = False
        log_event(f"Strategy Armed: {STRATEGY_CONFIG['armed']}")
        return jsonify({"status": "ok", "armed": STRATEGY_CONFIG["armed"]})

    @app.route("/api/panic_exit", methods=["POST"])
    def api_panic_exit():
        RISK_CONFIG["panic_exit"] = True
        log_event("PANIC EXIT REQUESTED.")
        return jsonify({"status": "ok"})

    @app.route("/api/import_positions", methods=["POST"])
    def api_import_positions():
        imported = 0
        for token, p in ACTIVE_POSITIONS.items():
            if not any(l["token"] == token for l in STRATEGY_LEGS):
                sym = p["symbol"]
                opt_type = "CE" if sym.endswith("CE") else ("PE" if sym.endswith("PE") else ("FUT" if "FUT" in sym else "EQ"))
                strike = 0.0
                m = re.search(r"(\d+(?:\.\d+)?)(CE|PE)$", sym)
                if m: strike = float(m.group(1))

                exp_raw = TOKEN_EXPIRY_MAP.get(token, "")
                exp_date_str = str(exp_raw).split(" ")[0] if exp_raw else datetime.datetime.now(IST).strftime("%Y-%m-%d")

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
            log_event(f"Imported {imported} positions.")
            return jsonify({"status": "ok", "count": imported})
        return jsonify({"status": "error", "message": "No unimported positions."})

    @app.route("/api/data")
    def api_data():
        payload_legs = []
        master_ltp = LIVE_MASTER_UND_LTP
        rf = float(STRATEGY_CONFIG.get("risk_free_rate", 7.0)) / 100.0

        for l in STRATEGY_LEGS:
            temp = l.copy()
            token = l["token"]
            ltp = LIVE_LEG_PRICES.get(token, 0.0)
            temp["ltp"] = ltp
            temp["symbol"] = l["tradingsymbol"]
            temp["type"] = l["transaction_type"]
            temp["qty"] = l["quantity"]
            payload_legs.append(temp)

        live_positions_payload = []
        for token, pos in ACTIVE_POSITIONS.items():
            ltp = LIVE_LEG_PRICES.get(token, pos["entry_price"])
            entry = pos["entry_price"]
            mult = pos["multiplier"]
            qty = pos["qty"]
            is_long = pos["type"] == "LONG"
            pnl = ((ltp - entry) * qty * mult) if is_long else ((entry - ltp) * qty * mult)

            sym = pos["symbol"]
            opt_type = "CE" if sym.endswith("CE") else ("PE" if sym.endswith("PE") else "OTHER")
            strike = 0.0
            m = re.search(r"(\d+(?:\.\d+)?)(CE|PE)$", sym)
            if m: strike = float(m.group(1))

            pos_iv, delta = 0.0, 0.0
            exp_date_raw = TOKEN_EXPIRY_MAP.get(token, "")
            dte_val = get_fractional_dte(pos["exchange"], str(exp_date_raw).split(" ")[0]) if exp_date_raw else 0.002
            calc_master = master_ltp if master_ltp > 0 else strike

            if opt_type in ["CE", "PE"] and strike > 0 and calc_master > 0 and ltp > 0:
                pos_iv = calc_iv(opt_type, calc_master, strike, dte_val, rf, ltp) / 100.0
                if pos_iv > 0:
                    d1 = (math.log(calc_master / strike) + (rf + 0.5 * pos_iv**2) * dte_val) / (pos_iv * math.sqrt(dte_val))
                    delta = norm_cdf(d1) if opt_type == "CE" else norm_cdf(d1) - 1.0

            live_positions_payload.append({
                "token": token,
                "symbol": sym,
                "type": pos["type"],
                "qty": qty,
                "entry_price": entry,
                "ltp": ltp,
                "pnl": pnl,
                "iv": pos_iv * 100.0,
                "delta": delta,
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
            "active_sl": CURRENT_ACTIVE_SL if CURRENT_ACTIVE_SL is not None else RISK_CONFIG["stoploss_pnl"],
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
            },
            "diagnostics": {"api": DIAGNOSTICS},
            "logs": EVENT_LOG[::-1],
        })

    def run_flask():
        app.run(host="0.0.0.0", port=FLASK_PORT, debug=False, use_reloader=False, threaded=True)

    SUCCESS_LOAD = True

except Exception as e:
    CRASH_ERROR = traceback.format_exc()
    SUCCESS_LOAD = False

class AlgoWebApp(App):
    def build(self):
        if not SUCCESS_LOAD:
            layout = BoxLayout(orientation="vertical", padding=20)
            sv = ScrollView()
            lbl = Label(text=f"FATAL BOOT ERROR:\n\n{CRASH_ERROR}", color=(1, 0.2, 0.2, 1), font_size='14sp', size_hint_y=None, halign="left", valign="top")
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
        self.lbl = Label(text="Garua Engine V25.8\nBooting Server...", halign="center", font_size="22sp", color=(0.05, 0.8, 0.94, 1))
        self.btn = Button(text="OPEN ALGO COMMAND CENTER", size_hint=(1, 0.25), disabled=True, background_color=(0, 0.7, 0, 1), font_size="18sp", bold=True)
        self.btn.bind(on_press=self.open_ui)
        layout.add_widget(self.lbl)
        layout.add_widget(self.btn)

        Clock.schedule_once(self.ready, 4)
        return layout

    def ready(self, dt):
        self.lbl.text = f"Garua Engine V25.8\nServer Active on Port {FLASK_PORT}\n\nClick below to open the Live Dashboard."
        self.btn.disabled = False

    def open_ui(self, inst):
        try:
            webbrowser.open(f"http://127.0.0.1:{FLASK_PORT}")
        except Exception:
            self.lbl.text = f"Could not launch browser natively.\nOpen Chrome to:\nhttp://127.0.0.1:{FLASK_PORT}"

if __name__ == "__main__":
    try:
        AlgoWebApp().run()
    except Exception:
        write_fatal_log("APP RUNTIME CRASH:\n" + traceback.format_exc())
        raise
