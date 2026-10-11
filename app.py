import os
import requests
import pandas as pd
import yfinance as yf
from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

def send_telegram_alert(message):
    """Sends alerts to Telegram channel/group."""
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        try:
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            print(f"Telegram Alert Error: {e}")

def fetch_market_data(ticker="^NSEI"):
    """Fetches multi-timeframe market data for Nifty 50."""
    try:
        df_15m = yf.download(ticker, period="5d", interval="15m", progress=False)
        df_3m  = yf.download(ticker, period="2d", interval="3m", progress=False)
        if df_15m.empty or df_3m.empty:
            return None, None
        return df_15m, df_3m
    except Exception as e:
        print(f"Data Fetch Error: {e}")
        return None, None

def analyze_institutional_engine():
    df_15m, df_3m = fetch_market_data("^NSEI")
    
    if df_15m is None or df_3m is None:
        return {"status": "Error", "message": "Market Data Unavailable"}

    # 1. Higher Timeframe Trend (15m 200 EMA)
    df_15m['EMA_200'] = df_15m['Close'].ewm(span=200, adjust=False).mean()
    close_15m = float(df_15m['Close'].iloc[-1])
    ema_15m   = float(df_15m['EMA_200'].iloc[-1])
    htf_trend = "BULLISH" if close_15m > ema_15m else "BEARISH"

    # 2. Lower Timeframe Execution (3m Indicators)
    df_3m['EMA_200'] = df_3m['Close'].ewm(span=200, adjust=False).mean()
    df_3m['Vol_SMA'] = df_3m['Volume'].rolling(window=20).mean()
    
    latest_3m = df_3m.iloc[-1]
    close_3m  = float(latest_3m['Close'])
    ema_3m    = float(latest_3m['EMA_200'])
    vol_3m    = float(latest_3m['Volume'])
    vol_avg   = float(latest_3m['Vol_SMA'])
    
    high_volume = vol_3m > (vol_avg * 2.5) if vol_avg > 0 else False

    # 3. Hard-Lock Gate Logic
    signal = None
    sl = 0.0
    target = 0.0

    if htf_trend == "BULLISH" and close_3m > ema_3m and high_volume:
        signal = "INSTITUTIONAL BUY 🚀"
        sl = round(float(latest_3m['Low']) - 10, 2)
        target = round(close_3m + ((close_3m - sl) * 2), 2)
        
    elif htf_trend == "BEARISH" and close_3m < ema_3m and high_volume:
        signal = "INSTITUTIONAL SELL 📉"
        sl = round(float(latest_3m['High']) + 10, 2)
        target = round(close_3m - ((sl - close_3m) * 2), 2)

    # 4. Telegram Alert Trigger
    if signal:
        msg = (
            f"🚨 *NIFTY 50 INSTITUTIONAL SIGNAL* 🚨\n\n"
            f"⚡ *Signal:* `{signal}`\n"
            f"📊 *Entry Price:* `{close_3m:.2f}`\n"
            f"🛡️ *Stop Loss:* `{sl}`\n"
            f"🎯 *Target (1:2):* `{target}`\n\n"
            f"🔍 *Filter Check:* 15m Trend: `{htf_trend}` | Volume Spike: `Confirmed`"
        )
        send_telegram_alert(msg)

    return {
        "price": close_3m,
        "htf_trend": htf_trend,
        "signal": signal if signal else "NO SIGNAL (ALIGNMENT WAIT)",
        "volume_spike": "YES" if high_volume else "NORMAL",
        "stop_loss": sl,
        "target": target
    }

# --- ROUTES ---
@app.route('/')
def home():
    # Renders the HTML terminal from templates folder
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    result = analyze_institutional_engine()
    return jsonify(result)

@app.route('/cron-check', methods=['GET', 'POST'])
def cron_trigger():
    result = analyze_institutional_engine()
    return jsonify({"status": "executed", "data": result})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
