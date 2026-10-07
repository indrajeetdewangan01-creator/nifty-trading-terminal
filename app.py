from flask import Flask, render_template_string, jsonify, request
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os

app = Flask(__name__)

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")

# Global variables for Trade Locking & State Management
active_trade = {
    "status": "IDLE",       # IDLE, ACTIVE
    "signal_type": None,    # BUY CE / BUY PE
    "strike": None,
    "entry": 0.0,
    "target": 0.0,
    "stop_loss": 0.0
}

def send_telegram_message(message):
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN":
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print("Telegram Error:", e)

def calculate_indicators(df):
    df['EMA_9'] = df['Close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['Close'].ewm(span=21, adjust=False).mean()
    df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
    
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df['ATR'] = true_range.rolling(14).mean()
    
    return df

@app.route('/')
def index():
    global active_trade
    try:
        tf = request.args.get('tf', '5m').lower()
        ticker = "^NSEI"
        data = yf.download(ticker, period="1d", interval="1m", progress=False)
        
        if data.empty or len(data) < 2:
            return "Fetching market data, please refresh..."

        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        if tf == '1m':
            pass
        elif tf == '3m':
            data = data.resample('3min').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna()
        elif tf == '5m':
            data = data.resample('5min').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna()
        elif tf == '15m':
            data = data.resample('15min').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna()

        data = calculate_indicators(data)
        latest = data.iloc[-1]
        
        spot_price = float(latest['Close'])
        
        if len(data) >= 2:
            prev = data.iloc[-2]
            prev_close = float(prev['Close'])
            price_change = spot_price - prev_close
            price_change_pct = (price_change / prev_close) * 100
        else:
            price_change = 0.0
            price_change_pct = 0.0

        ema_9 = float(latest['EMA_9']) if not np.isnan(latest['EMA_9']) else spot_price
        ema_21 = float(latest['EMA_21']) if not np.isnan(latest['EMA_21']) else spot_price
        ema_50 = float(latest['EMA_50']) if not np.isnan(latest['EMA_50']) else spot_price
        rsi = float(latest['RSI']) if not np.isnan(latest['RSI']) else 50.0
        macd = float(latest['MACD']) if not np.isnan(latest['MACD']) else 0.0
        macd_signal = float(latest['MACD_Signal']) if not np.isnan(latest['MACD_Signal']) else 0.0
        atr = float(latest['ATR']) if not np.isnan(latest['ATR']) else 25.0
        
        sl_buffer = max(round(atr * 1.2, 2), 35.0)
        target_buffer = round(sl_buffer * 2.0, 2)

        # --- TRADE LOCK & TARGET/SL MONITORING LOGIC ---
        if active_trade["status"] == "ACTIVE":
            # Check if Target or Stop-Loss hit
            if active_trade["signal_type"] == "BUY CE":
                if spot_price >= active_trade["target"] or spot_price <= active_trade["stop_loss"]:
                    send_telegram_message(f"🏁 *TRADE CLOSED (CE)*\nSpot Price: ₹{spot_price}\nTarget/SL Hit. Lock Released.")
                    active_trade["status"] = "IDLE"
            elif active_trade["signal_type"] == "BUY PE":
                if spot_price <= active_trade["target"] or spot_price >= active_trade["stop_loss"]:
                    send_telegram_message(f"🏁 *TRADE CLOSED (PE)*\nSpot Price: ₹{spot_price}\nTarget/SL Hit. Lock Released.")
                    active_trade["status"] = "IDLE"

        # If trade is active, lock display values to the active trade parameters
        if active_trade["status"] == "ACTIVE":
            htf_trend = "LOCKED IN TRADE"
            signal_type = active_trade["signal_type"]
            recommended_strike = active_trade["strike"]
            spot_entry = active_trade["entry"]
            spot_sl = active_trade["stop_loss"]
            spot_target = active_trade["target"]
            confluence_score = 85  # Locked active trade high confidence visual
        else:
            # Generate new signal only if filters are strong (Confluence check)
            if spot_price > ema_50 and ema_9 > ema_21 and macd > macd_signal and rsi > 55:
                htf_trend = "BULLISH"
                signal_type = "BUY CE"
                recommended_strike = f"{round(spot_price / 50) * 50} CE"
                spot_entry = spot_price
                spot_sl = spot_price - sl_buffer
                spot_target = spot_price + target_buffer
                confluence_score = 80
            elif spot_price < ema_50 and ema_9 < ema_21 and macd < macd_signal and rsi < 45:
                htf_trend = "BEARISH"
                signal_type = "BUY PE"
                recommended_strike = f"{round(spot_price / 50) * 50} PE"
                spot_entry = spot_price
                spot_sl = spot_price + sl_buffer
                spot_target = spot_price - target_buffer
                confluence_score = 80
            else:
                htf_trend = "SIDEWAYS / CHOPPY"
                signal_type = "WAIT / LOW CONFLUENCE"
                recommended_strike = "N/A"
                spot_entry = spot_price
                spot_sl = 0
                spot_target = 0
                confluence_score = 35

            # If a valid fresh buy signal occurs, LOCK IT and send Telegram alert ONCE
            if "BUY" in signal_type and active_trade["status"] == "IDLE":
                active_trade["status"] = "ACTIVE"
                active_trade["signal_type"] = signal_type
                active_trade["strike"] = recommended_strike
                active_trade["entry"] = spot_entry
                active_trade["target"] = spot_target
                active_trade["stop_loss"] = spot_sl

                sl_pts = round(abs(spot_entry - spot_sl), 2)
                tgt_pts = round(abs(spot_target - spot_entry), 2)
                msg = (f"🚨 *SMART NIFTY LOCKED SIGNAL* 🚨\n\n"
                       f"Signal: {signal_type}\n"
                       f"Strike: {recommended_strike}\n"
                       f"Spot Entry: ₹{round(spot_entry, 2)}\n"
                       f"Spot StopLoss: ₹{round(spot_sl, 2)} (-{sl_pts} pts)\n"
                       f"Spot Target: ₹{round(spot_target, 2)} (+{tgt_pts} pts)\n"
                       f"Status: Trade Locked until Target/SL!")
                send_telegram_message(msg)

        sl_points = round(abs(spot_entry - spot_sl), 2) if spot_sl > 0 else 0
        target_points = round(abs(spot_target - spot_entry), 2) if spot_target > 0 else 0

        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Nifty 50 Pro Terminal - Locked Trade System</title>
            <meta http-equiv="refresh" content="60">
            <style>
                body { background-color: #0b0e14; color: #c9d1d9; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 15px; }
                .container { max-width: 1200px; margin: auto; }
                .card { background: #121821; border: 1px solid #21262d; border-radius: 10px; padding: 15px; margin-bottom: 15px; }
                .header-card { display: flex; justify-content: space-between; align-items: center; background: #161b22; }
                .price-title { font-size: 22px; font-weight: bold; color: #f0f6fc; }
                .text-green { color: #3fb950; }
                .text-red { color: #f85149; }
                .timeframe-tabs { display: flex; gap: 5px; }
                .tf-btn { background: #21262d; border: 1px solid #30363d; color: #8b949e; padding: 6px 12px; border-radius: 4px; font-weight: bold; cursor: pointer; text-decoration: none; display: inline-block; text-align: center; }
                .tf-btn.active { background: #1f6feb; color: #ffffff; border-color: #1f6feb; }
                .grid-2col { display: grid; grid-template-columns: 2fr 1fr; gap: 15px; }
                @media (max-width: 900px) { .grid-2col { grid-template-columns: 1fr; } }
                .metrics-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 10px; }
                .metric-box { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 10px; text-align: center; }
                .metric-val { font-size: 16px; font-weight: bold; margin-top: 4px; }
                .filter-tags { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
                .filter-pill { background: #161b22; border: 1px solid #30363d; padding: 6px 10px; border-radius: 6px; font-size: 12px; }
                .filter-pill span { font-weight: bold; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="card header-card">
                    <div>
                        <div style="font-size: 12px; color: #8b949e; font-weight: bold;">NIFTY 50 PRO TERMINAL</div>
                        <div class="price-title">₹{{ spot_price }} 
                            <span style="font-size: 14px;" class="{% if price_change >= 0 %}text-green{% else %}text-red{% endif %}">
                                {{ price_change_formatted }} ({{ price_change_pct_formatted }}%)
                            </span>
                        </div>
                    </div>
                    <div class="timeframe-tabs">
                        <a href="/?tf=1m" class="tf-btn {% if tf == '1m' %}active{% endif %}">1M</a>
                        <a href="/?tf=3m" class="tf-btn {% if tf == '3m' %}active{% endif %}">3M</a>
                        <a href="/?tf=5m" class="tf-btn {% if tf == '5m' %}active{% endif %}">5M</a>
                        <a href="/?tf=15m" class="tf-btn {% if tf == '15m' %}active{% endif %}">15M</a>
                    </div>
                </div>

                <div class="grid-2col">
                    <div>
                        <div class="card">
                            <h3 style="margin-top: 0; font-size: 15px; color: #8b949e;">LIVE TECHNICAL SUMMARY ({{ tf|upper }})</h3>
                            <p style="margin: 5px 0;"><b>HTF Trend:</b> <span class="{% if htf_trend == 'BULLISH' %}text-green{% elif htf_trend == 'BEARISH' %}text-red{% else %}color: #d29922;{% endif %}">{{ htf_trend }}</span></p>
                            <p style="margin: 5px 0;"><b>Action Signal:</b> <span class="{% if 'CE' in signal_type %}text-green{% elif 'PE' in signal_type %}text-red{% else %}color: #d29922;{% endif %}">{{ signal_type }}</span></p>
                            <p style="margin: 5px 0; font-size: 13px; color: #8b949e;">RSI: {{ rsi }} | MACD: {{ macd }} | ATR Volatility: {{ atr }}</p>
                        </div>

                        <div class="card">
                            <h3 style="margin-top: 0; font-size: 15px; color: #8b949e;">STRATEGY PERFORMANCE HISTORY</h3>
                            <div class="metrics-grid">
                                <div class="metric-box">
                                    <div style="font-size: 11px; color: #8b949e;">Total Trades</div>
                                    <div class="metric-val">3</div>
                                </div>
                                <div class="metric-box">
                                    <div style="font-size: 11px; color: #8b949e;">Target Hits</div>
                                    <div class="metric-val text-green">0</div>
                                </div>
                                <div class="metric-box">
                                    <div style="font-size: 11px; color: #8b949e;">SL Hits</div>
                                    <div class="metric-val text-red">3</div>
                                </div>
                                <div class="metric-box">
                                    <div style="font-size: 11px; color: #8b949e;">Win Rate %</div>
                                    <div class="metric-val">0%</div>
                                </div>
                            </div>
                        </div>

                        <div class="card">
                            <h3 style="margin-top: 0; font-size: 15px; color: #8b949e;">CONFLUENCE & FILTER BREAKDOWN</h3>
                            <div class="filter-tags">
                                <div class="filter-pill">TIMEFRAME: <span>{{ tf|upper }}</span></div>
                                <div class="filter-pill">50 EMA: <span>{% if spot_price > ema_50 %}Above 50 EMA{% else %}Below 50 EMA{% endif %}</span></div>
                                <div class="filter-pill">EMA 9/21: <span>{% if ema_9 > ema_21 %}Bullish Cross{% else %}Bearish Cross{% endif %}</span></div>
                                <div class="filter-pill">RSI QUALITY: <span>{{ rsi }}</span></div>
                                <div class="filter-pill">MACD STATUS: <span>{% if macd > macd_signal %}Bullish Cross{% else %}Bearish Cross{% endif %}</span></div>
                            </div>
                        </div>
                    </div>

                    <div>
                        <div class="card" style="border-color: #30363d;">
                            <div style="font-size: 11px; color: #8b949e; font-weight: bold;">CONFLUENCE & FILTERS</div>
                            <div style="text-align: center; margin: 15px 0;">
                                <div style="font-size: 12px; color: #8b949e;">Confluence Score</div>
                                <div style="font-size: 32px; font-weight: bold; color: #d29922;">{{ confluence_score }}</div>
                            </div>
                            <hr style="border: 0; border-top: 1px solid #21262d; margin: 15px 0;">
                            <div style="font-size: 12px; margin-bottom: 8px;"><b>Spot Entry Level:</b> ₹{{ spot_entry }}</div>
                            <div style="font-size: 12px; margin-bottom: 8px;"><b>Spot Stop-Loss:</b> ₹{{ spot_sl }}</div>
                            <div style="font-size: 12px; margin-bottom: 8px;"><b>Spot Target:</b> ₹{{ spot_target }}</div>
                            <div style="font-size: 12px; color: #3fb950; font-weight: bold; margin-top: 10px;">Risk : Reward $\rightarrow$ 1 : 2.0</div>
                        </div>

                        <div class="card" style="border: 1px solid #1f6feb;">
                            <div style="font-size: 11px; color: #58a6ff; font-weight: bold;">🔒 LOCKED OPTION RECOMMENDATION</div>
                            <div style="margin-top: 12px;">
                                <div style="font-size: 12px; color: #8b949e;">Recommended Strike</div>
                                <div style="font-size: 18px; font-weight: bold; color: #f0f6fc; margin-top: 2px;">{{ recommended_strike }}</div>
                            </div>
                            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 15px;">
                                <div style="background: #161b22; padding: 8px; border-radius: 6px;">
                                    <div style="font-size: 10px; color: #8b949e;">Option Stop-Loss</div>
                                    <div style="font-size: 13px; font-weight: bold; color: #f85149; margin-top: 2px;">{% if sl_points > 0 %}-{{ sl_points }} pts{% else %}N/A{% endif %}</div>
                                </div>
                                <div style="background: #161b22; padding: 8px; border-radius: 6px;">
                                    <div style="font-size: 10px; color: #8b949e;">Option Target</div>
                                    <div style="font-size: 13px; font-weight: bold; color: #3fb950; margin-top: 2px;">{% if target_points > 0 %}+{{ target_points }} pts{% else %}N/A{% endif %}</div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        
        p_change_str = f"+{round(price_change, 2)}" if price_change >= 0 else f"{round(price_change, 2)}"
        p_change_pct_str = f"+{round(price_change_pct, 2)}" if price_change_pct >= 0 else f"{round(price_change_pct, 2)}"

        return render_template_string(html_template, 
                                     tf=tf,
                                     spot_price=round(spot_price, 2),
                                     price_change=price_change,
                                     price_change_formatted=p_change_str,
                                     price_change_pct_formatted=p_change_pct_str,
                                     htf_trend=htf_trend,
                                     signal_type=signal_type,
                                     recommended_strike=recommended_strike,
                                     spot_entry=round(spot_entry, 2),
                                     spot_target=round(spot_target, 2),
                                     spot_sl=round(spot_sl, 2),
                                     sl_points=sl_points,
                                     target_points=target_points,
                                     confluence_score=confluence_score,
                                     rsi=round(rsi, 2),
                                     macd=round(macd, 4),
                                     atr=
