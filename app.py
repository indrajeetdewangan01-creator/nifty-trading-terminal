from flask import Flask, render_template_string, jsonify
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os

app = Flask(__name__)

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")

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
    # EMA Calculation
    df['EMA_9'] = df['Close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['Close'].ewm(span=21, adjust=False).mean()
    df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
    
    # RSI Calculation
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # MACD Calculation
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    # ATR (Average True Range) Calculation for Dynamic SL/Target
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df['ATR'] = true_range.rolling(14).mean()
    
    return df

@app.route('/')
def index():
    try:
        ticker = "^NSEI"
        data = yf.download(ticker, period="1d", interval="1m", progress=False)
        
        if data.empty or len(data) < 50:
            return "Fetching market data, please refresh..."

        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        data = calculate_indicators(data)
        latest = data.iloc[-1]
        
        spot_price = float(latest['Close'])
        ema_9 = float(latest['EMA_9'])
        ema_21 = float(latest['EMA_21'])
        ema_50 = float(latest['EMA_50'])
        rsi = float(latest['RSI'])
        macd = float(latest['MACD'])
        macd_signal = float(latest['MACD_Signal'])
        atr = float(latest['ATR']) if not np.isnan(latest['ATR']) else 25.0
        
        # Dynamic SL & Target buffer based on ATR (Volatility aware)
        sl_buffer = max(round(atr * 1.2, 2), 30.0)  # Minimum 30 points or 1.2x ATR
        target_buffer = round(sl_buffer * 2.0, 2)    # 1:2 Risk-Reward

        # Bi-directional Trend Filtering Logic with Enhanced Filters
        if spot_price > ema_50 and ema_9 > ema_21 and macd > macd_signal and rsi > 50:
            htf_trend = "BULLISH"
            signal_type = "BUY CE"
            recommended_strike = f"{round(spot_price / 50) * 50} CE"
            spot_entry = spot_price
            spot_sl = spot_price - sl_buffer
            spot_target = spot_price + target_buffer
        elif spot_price < ema_50 and ema_9 < ema_21 and macd < macd_signal and rsi < 50:
            htf_trend = "BEARISH"
            signal_type = "BUY PE"
            recommended_strike = f"{round(spot_price / 50) * 50} PE"
            spot_entry = spot_price
            spot_sl = spot_price + sl_buffer
            spot_target = spot_price - target_buffer
        else:
            htf_trend = "SIDEWAYS / CHOPPY"
            signal_type = "WAIT / LOW CONFLUENCE"
            recommended_strike = "N/A"
            spot_entry = spot_price
            spot_sl = 0
            spot_target = 0

        # Confluence Score calculation
        confluence_score = 50
        if htf_trend == "BULLISH":
            confluence_score += 30
        elif htf_trend == "BEARISH":
            confluence_score -= 30
            
        if rsi > 55:
            confluence_score += 20
        elif rsi < 45:
            confluence_score -= 20

        sl_points = round(abs(spot_entry - spot_sl), 2)
        target_points = round(abs(spot_target - spot_entry), 2)

        # Telegram Alert with Dynamic Points
        if "BUY" in signal_type:
            msg = (f"🚨 *SMART NIFTY SIGNAL* 🚨\n\n"
                   f"Signal: {signal_type}\n"
                   f"Strike: {recommended_strike}\n"
                   f"Spot Entry: ₹{round(spot_entry, 2)}\n"
                   f"Spot StopLoss: ₹{round(spot_sl, 2)} (-{sl_points} pts)\n"
                   f"Spot Target: ₹{round(spot_target, 2)} (+{target_points} pts)\n"
                   f"Confluence Score: {confluence_score}/100")
            send_telegram_message(msg)

        # HTML Dashboard Template
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Nifty 50 Pro Terminal - Smart Bi-Directional</title>
            <meta http-equiv="refresh" content="60">
            <style>
                body { background-color: #0d1117; color: #c9d1d9; font-family: Arial, sans-serif; margin: 0; padding: 20px; }
                .container { max-width: 1200px; margin: auto; }
                .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin-bottom: 20px; }
                .header { display: flex; justify-content: space-between; align-items: center; }
                .signal-ce { color: #3fb950; font-weight: bold; }
                .signal-pe { color: #f85149; font-weight: bold; }
                .grid { display: grid; grid-template-columns: 2fr 1fr; gap: 20px; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="card header">
                    <h2>NIFTY 50 SMART TERMINAL</h2>
                    <h3>Spot Price: ₹{{ spot_price }}</h3>
                </div>
                <div class="grid">
                    <div class="card">
                        <h3>Market & Trend Status</h3>
                        <p><b>HTF Trend:</b> {{ htf_trend }}</p>
                        <p><b>Action Signal:</b> <span class="{% if 'CE' in signal_type %}signal-ce{% elif 'PE' in signal_type %}signal-pe{% endif %}">{{ signal_type }}</span></p>
                        <p><b>Confluence Score:</b> {{ confluence_score }} / 100</p>
                        <p><b>RSI:</b> {{ rsi }} | <b>MACD:</b> {{ macd }} | <b>ATR:</b> {{ atr }}</p>
                    </div>
                    <div class="card">
                        <h3>Option Recommendation</h3>
                        <p><b>Strike:</b> {{ recommended_strike }}</p>
                        <p><b>Entry:</b> ₹{{ spot_entry }}</p>
                        <p><b>Target:</b> ₹{{ spot_target }} (+{{ target_points }} pts)</p>
                        <p><b>Stop-Loss:</b> ₹{{ spot_sl }} (-{{ sl_points }} pts)</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        return render_template_string(html_template, 
                                     spot_price=round(spot_price, 2),
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
                                     atr=round(atr, 2))

    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
