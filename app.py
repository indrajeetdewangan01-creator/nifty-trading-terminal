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
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        try:
            response = requests.post(url, json=payload, timeout=5)
            print(f"Telegram API Response Status: {response.status_code}")
            print(f"Telegram API Response Body: {response.text}")
        except Exception as e:
            print(f"Telegram Alert Exception: {e}")

def fetch_market_data(ticker="^NSEI"):
    try:
        # Fetching intraday data (5m and 15m) with auto_adjust
        df_15m = yf.download(ticker, period="5d", interval="15m", progress=False, auto_adjust=True)
        df_5m  = yf.download(ticker, period="2d", interval="5m", progress=False, auto_adjust=True)
        
        # Fallback for weekends / closed market when intraday is empty
        if df_15m is None or df_5m is None or df_15m.empty or df_5m.empty:
            df_daily = yf.download(ticker, period="10d", interval="1d", progress=False, auto_adjust=True)
            return df_daily, df_daily
            
        return df_15m, df_5m
    except Exception as e:
        print(f"Data Fetch Error: {e}")
        return None, None

def analyze_institutional_engine():
    df_15m, df_5m = fetch_market_data("^NSEI")
    
    if df_15m is None or df_5m is None or df_5m.empty:
        return {"status": "Error", "message": "Market Data Unavailable"}

    # Properly flatten MultiIndex columns if returned by yfinance
    if isinstance(df_15m.columns, pd.MultiIndex):
        df_15m.columns = df_15m.columns.get_level_values(0)
    if isinstance(df_5m.columns, pd.MultiIndex):
        df_5m.columns = df_5m.columns.get_level_values(0)

    close_15m_series = df_15m['Close'].squeeze()
    close_5m_series = df_5m['Close'].squeeze()
    vol_5m_series = df_5m['Volume'].squeeze()

    # Ensure series format
    if isinstance(close_15m_series, pd.DataFrame):
        close_15m_series = close_15m_series.iloc[:, 0]
    if isinstance(close_5m_series, pd.DataFrame):
        close_5m_series = close_5m_series.iloc[:, 0]
    if isinstance(vol_5m_series, pd.DataFrame):
        vol_5m_series = vol_5m_series.iloc[:, 0]

    # 1. Higher Timeframe Trend (15m EMA)
    ema_15m = close_15m_series.ewm(span=min(200, len(close_15m_series)), adjust=False).mean()
    close_15m = float(close_15m_series.iloc[-1])
    ema_15m_val = float(ema_15m.iloc[-1])
    htf_trend = "BULLISH" if close_15m > ema_15m_val else "BEARISH"

    # 2. Lower Timeframe Execution (5m EMA & Volume)
    ema_5m = close_5m_series.ewm(span=min(50, len(close_5m_series)), adjust=False).mean()
    vol_avg = vol_5m_series.rolling(window=min(20, len(vol_5m_series))).mean()
    
    close_5m = float(close_5m_series.iloc[-1])
    ema_5m_val = float(ema_5m.iloc[-1])
    vol_5m = float(vol_5m_series.iloc[-1])
    vol_avg_val = float(vol_avg.iloc[-1]) if not vol_avg.empty else 0
    
    high_volume = vol_5m > (vol_avg_val * 1.5) if vol_avg_val > 0 else True

    # 3. Hard-Lock Gate Logic
    signal = None
    sl = 0.0
    target = 0.0

    if htf_trend == "BULLISH" and close_5m > ema_5m_val and high_volume:
        signal = "INSTITUTIONAL BUY 🚀"
        sl = round(close_5m - 50, 2)
        target = round(close_5m + 100, 2)
    elif htf_trend == "BEARISH" and close_5m < ema_5m_val and high_volume:
        signal = "INSTITUTIONAL SELL 📉"
        sl = round(close_5m + 50, 2)
        target = round(close_5m - 100, 2)

    # Trigger Telegram Alert if signal is active
    if signal:
        msg = (
            f"🚨 *NIFTY 50 INSTITUTIONAL SIGNAL* 🚨\n\n"
            f"⚡ *Signal:* `{signal}`\n"
            f"📊 *Entry Price:* `{close_5m:.2f}`\n"
            f"🛡️ *Stop Loss:* `{sl}`\n"
            f"🎯 *Target (1:2):* `{target}`\n\n"
            f"🔍 *Filter Check:* 15m Trend: `{htf_trend}` | Volume Spike: `Confirmed`"
        )
        send_telegram_alert(msg)

    return {
        "price": close_5m,
        "htf_trend": htf_trend,
        "signal": signal if signal else "NO SIGNAL (MARKET CONSOLIDATION)",
        "volume_spike": "YES" if high_volume else "NORMAL",
        "stop_loss": sl if sl > 0 else '-',
        "target": target if target > 0 else '-'
    }

@app.route('/')
def home():
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
