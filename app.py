from flask import Flask, render_template, jsonify
import yfinance as yf
import pandas as pd
import requests
import os
import threading
import time

app = Flask(__name__)

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")

last_alert_time = None

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

def analyze_market():
    global last_alert_time
    try:
        ticker = "^NSEI"
        data = yf.download(ticker, period="1d", interval="1m", progress=False)
        
        if data.empty or len(data) < 3:
            return "WAIT / NO TRADE", 0.0, ""

        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        # Last 3 candles analysis for 1-minute timeframe
        c1_open, c1_close = data['Open'].iloc[-3], data['Close'].iloc[-3]
        c2_open, c2_close, c2_high, c2_low = data['Open'].iloc[-2], data['Close'].iloc[-2], data['High'].iloc[-2], data['Low'].iloc[-2]
        c3_open, c3_close = data['Open'].iloc[-1], data['Close'].iloc[-1]
        
        current_time = str(data.index[-1])
        spot_price = float(c3_close)

        # 1. Bearish Pattern: Red -> Green -> Red (Below Green Low)
        is_bear_c1 = c1_close < c1_open
        is_bear_c2 = c2_close > c2_open
        is_bear_c3 = c3_close < c3_open
        is_bear_below = c3_close < c2_low
        bearish_matched = is_bear_c1 and is_bear_c2 and is_bear_c3 and is_bear_below

        # 2. Bullish Pattern: Green -> Red -> Green (Above Red High)
        is_bull_c1 = c1_close > c1_open
        is_bull_c2 = c2_close < c2_open
        is_bull_c3 = c3_close > c3_open
        is_bull_above = c3_close > c2_high
        bullish_matched = is_bull_c1 and is_bull_c2 and is_bull_c3 and is_bull_above

        signal_type = "WAIT / NO TRADE"

        if bearish_matched:
            signal_type = "BEARISH PATTERN (BUY PE)"
            if last_alert_time != current_time:
                last_alert_time = current_time
                msg = f"🚨 *NIFTY 1M BEARISH ALERT* 🚨\nSetup: Red ➔ Green ➔ Red (Below Green)\nSpot Price: ₹{round(spot_price, 2)}\nTime: {current_time}"
                send_telegram_message(msg)
        elif bullish_matched:
            signal_type = "BULLISH PATTERN (BUY CE)"
            if last_alert_time != current_time:
                last_alert_time = current_time
                msg = f"🚨 *NIFTY 1M BULLISH ALERT* 🚨\nSetup: Green ➔ Red ➔ Green (Above Red)\nSpot Price: ₹{round(spot_price, 2)}\nTime: {current_time}"
                send_telegram_message(msg)

        return signal_type, spot_price, current_time

    except Exception as e:
        print("Analysis Error:", e)
        return "ERROR", 0.0, ""

def background_scanner():
    while True:
        analyze_market()
        time.sleep(60) # Har 1 minute mein automatic check karega

# Background thread jo bina site khole background mein chalta rahega
threading.Thread(target=background_scanner, daemon=True).start()

@app.route('/')
def index():
    signal_type, spot_price, current_time = analyze_market()
    return render_template('index.html', 
                           spot_price=spot_price,
                           signal_type=signal_type,
                           current_time=current_time)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
