import os
import requests
import pandas as pd
import yfinance as yf
from flask import Flask, jsonify, request

app = Flask(__name__)

# --- CONFIGURATION (Environment Variables) ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID_HERE")

def send_telegram_alert(message):
    """Sends institutional alerts directly to Telegram."""
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
            print(f"Error sending Telegram message: {e}")

def fetch_market_data(ticker="^NSEI"):
    """Fetches multi-timeframe data for Nifty 50."""
    try:
        # Fetch 15m (Higher Timeframe Trend) and 3m (Execution Timeframe)
        df_15m = yf.download(ticker, period="5d", interval="15m", progress=False)
        df_3m  = yf.download(ticker, period="2d", interval="3m", progress=False)
        
        if df_15m.empty or df_3m.empty:
            return None, None
            
        return df_15m, df_3m
    except Exception as e:
        print(f"Data Fetch Error: {e}")
        return None, None

def analyze_institutional_setup():
    df_15m, df_3m = fetch_market_data("^NSEI")
    
    if df_15m is None or df_3m is None:
        return "Market Data Unavailable"

    # --- 1. HIGHER TIMEFRAME TREND (15-Minute 200 EMA) ---
    df_15m['EMA_200'] = df_15m['Close'].ewm(span=200, adjust=False).mean()
    latest_15m_close = float(df_15m['Close'].iloc[-1])
    latest_15m_ema   = float(df_15m['EMA_200'].iloc[-1])
    
    htf_trend = "BULLISH" if latest_15m_close > latest_15m_ema else "BEARISH"

    # --- 2. LOWER TIMEFRAME EXECUTION (3-Minute Indicators) ---
    df_3m['EMA_200'] = df_3m['Close'].ewm(span=200, adjust=False).mean()
    df_3m['Vol_SMA'] = df_3m['Volume'].rolling(window=20).mean()
    
    latest_3m = df_3m.iloc[-1]
    prev_3m   = df_3m.iloc[-2]
    
    close_3m  = float(latest_3m['Close'])
    ema_3m    = float(latest_3m['EMA_200'])
    volume_3m = float(latest_3m['Volume'])
    vol_avg   = float(latest_3m['Vol_SMA'])
    
    # Volume Spike Filter (2.5x average)
    high_volume = volume_3m > (vol_avg * 2.5) if vol_avg > 0 else False

    # --- 3. ZERO-FALSE HARD-GATE LOGIC ---
    signal = None

    # BUY GATE: 15m MUST be Bullish AND 3m MUST be above EMA AND High Volume
    if htf_trend == "BULLISH" and close_3m > ema_3m and high_volume:
        signal = "INSTITUTIONAL BUY 🚀"
        sl = round(float(latest_3m['Low']) - 10, 2)
        target = round(close_3m + ((close_3m - sl) * 2), 2)
        
    # SELL GATE: 15m MUST be Bearish AND 3m MUST be below EMA AND High Volume
    elif htf_trend == "BEARISH" and close_3m < ema_3m and high_volume:
        signal = "INSTITUTIONAL SELL 📉"
        sl = round(float(latest_3m['High']) + 10, 2)
        target = round(close_3m - ((sl - close_3m) * 2), 2)

    # --- 4. TELEGRAM ALERT DISPATCH ---
    if signal:
        msg = (
            f"🚨 *NIFTY 50 SIGNAL ALERT* 🚨\n\n"
            f"⚡ *Signal:* `{signal}`\n"
            f"📊 *Entry Price:* `{close_3m:.2f}`\n"
            f"🛡️ *Stop Loss:* `{sl}`\n"
            f"🎯 *Target (1:2):* `{target}`\n\n"
            f"🔍 *Context:* 15m Trend is `{htf_trend}` | Volume Spike Confirmed."
        )
        send_telegram_alert(msg)
        return f"Signal Dispatched: {signal}"
    else:
        return f"No Signal. Market in Alignment Check (15m: {htf_trend}, Price: {close_3m:.2f})"

@app.route('/')
def home():
    return "Institutional Python Alert Engine Running Perfectly!"

@app.route('/cron-check', methods=['GET', 'POST'])
def cron_trigger():
    status = analyze_institutional_setup()
    return jsonify({"status": "executed", "details": status})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
