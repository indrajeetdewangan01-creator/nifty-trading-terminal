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
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            print(f"Telegram Alert Error: {e}")

def fetch_market_data(ticker="^NSEI"):
    try:
        # Try fetching intraday data
        df_15m = yf.download(ticker, period="5d", interval="15m", progress=False)
        df_3m  = yf.download(ticker, period="2d", interval="3m", progress=False)
        
        # Fallback for weekends / closed market when intraday is empty
        if df_15m.empty or df_3m.empty:
            df_daily = yf.download(ticker, period="10d", interval="1d", progress=False)
            return df_daily, df_daily
            
        return df_15m, df_3m
    except Exception as e:
        print(f"Data Fetch Error: {e}")
        return None, None

def analyze_institutional_engine():
    df_15m, df_3m = fetch_market_data("^NSEI")
    
    if df_15m is None or df_3m is None or df_3m.empty:
        return {"status": "Error", "message": "Market Data Unavailable"}

    # Handle multi-index columns if returned by yfinance
    if isinstance(df_15m.columns, pd.MultiIndex):
        df_15m.columns = df_15m.columns.get_level_0
    if isinstance(df_3m.columns, pd.MultiIndex):
        df_3m.columns = df_3m.columns.get_level_0

    # Extract Close series safely
    close_15m_series = df_15m['Close'].squeeze()
    close_3m_series = df_3m['Close'].squeeze()
    vol_3m_series = df_3m['Volume'].squeeze()

    # 1. Higher Timeframe Trend (200 EMA equivalent or simple mean for fallback)
    ema_15m = close_15m_series.ewm(span=min(200, len(close_15m_series)), adjust=False).mean()
    close_15m = float(close_15m_series.iloc[-1])
    ema_15m_val = float(ema_15m.iloc[-1])
    htf_trend = "BULLISH" if close_15m > ema_15m_val else "BEARISH"

    # 2. Lower Timeframe Execution
    ema_3m = close_3m_series.ewm(span=min(50, len(close_3m_series)), adjust=False).mean()
    vol_avg = vol_3m_series.rolling(window=min(20, len(vol_3m_series))).mean()
    
    close_3m = float(close_3m_series.iloc[-1])
    ema_3m_val = float(ema_3m.iloc[-1])
    vol_3m = float(vol_3m_series.iloc[-1])
    vol_avg_val = float(vol_avg.iloc[-1]) if not vol_avg.empty else 0
    
    high_volume = vol_3m > (vol_avg_val * 1.5) if vol_avg_val > 0 else True

    # 3. Hard-Lock Gate Logic
    signal = None
    sl = 0.0
    target = 0.0

    if htf_trend == "BULLISH" and close_3m > ema_3m_val and high_volume:
        signal = "INSTITUTIONAL BUY 🚀"
        sl = round(close_3m - 50, 2)
        target = round(close_3m + 100, 2)
    elif htf_trend == "BEARISH" and close_3m < ema_3m_val and high_volume:
        signal = "INSTITUTIONAL SELL 📉"
        sl = round(close_3m + 50, 2)
        target = round(close_3m - 100, 2)

    return {
        "price": close_3m,
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
