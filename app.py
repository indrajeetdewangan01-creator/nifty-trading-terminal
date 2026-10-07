from flask import Flask, render_template, jsonify, request
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os

app = Flask(__name__)

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")

# Dictionary to manage independent trade locks for each timeframe
active_trades = {
    "1m": {"status": "IDLE", "signal_type": None, "strike": None, "entry": 0.0, "target": 0.0, "stop_loss": 0.0},
    "3m": {"status": "IDLE", "signal_type": None, "strike": None, "entry": 0.0, "target": 0.0, "stop_loss": 0.0},
    "5m": {"status": "IDLE", "signal_type": None, "strike": None, "entry": 0.0, "target": 0.0, "stop_loss": 0.0},
    "15m": {"status": "IDLE", "signal_type": None, "strike": None, "entry": 0.0, "target": 0.0, "stop_loss": 0.0}
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
    global active_trades
    try:
        tf = request.args.get('tf', '1m').lower()
        if tf not in active_trades:
            tf = '1m'
            
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
        atr = float(latest['ATR']) if not np.isnan(latest['ATR']) else 15.0
        
        # Adjust SL buffers tighter for 1m and 3m timeframes
        if tf == '1m':
            sl_buffer = max(round(atr * 0.8, 2), 12.0)
        elif tf == '3m':
            sl_buffer = max(round(atr * 1.0, 2), 18.0)
        else:
            sl_buffer = max(round(atr * 1.5, 2), 35.0)
            
        target_buffer = round(sl_buffer * 2.0, 2)

        current_trade = active_trades[tf]

        # --- MONITOR ACTIVE TRADE FOR THIS TIMEFRAME ---
        if current_trade["status"] == "ACTIVE":
            if current_trade["signal_type"] == "BUY CE":
                if spot_price >= current_trade["target"] or spot_price <= current_trade["stop_loss"]:
                    current_trade["status"] = "IDLE"
            elif current_trade["signal_type"] == "BUY PE":
                if spot_price <= current_trade["target"] or spot_price >= current_trade["stop_loss"]:
                    current_trade["status"] = "IDLE"

        if current_trade["status"] == "ACTIVE":
            htf_trend = f"LOCKED ({tf.upper()})"
            signal_type = current_trade["signal_type"]
            recommended_strike = current_trade["strike"]
            spot_entry = current_trade["entry"]
            spot_sl = current_trade["stop_loss"]
            spot_target = current_trade["target"]
            confluence_score = 85
        else:
            if spot_price > ema_50 and ema_9 > ema_21 and rsi > 50:
                htf_trend = "BULLISH"
                signal_type = "BUY CE"
                recommended_strike = f"{round(spot_price / 50) * 50} CE"
                spot_entry = spot_price
                spot_sl = spot_price - sl_buffer
                spot_target = spot_price + target_buffer
                confluence_score = 78
            elif spot_price < ema_50 and ema_9 < ema_21 and rsi < 50:
                htf_trend = "BEARISH"
                signal_type = "BUY PE"
                recommended_strike = f"{round(spot_price / 50) * 50} PE"
                spot_entry = spot_price
                spot_sl = spot_price + sl_buffer
                spot_target = spot_price - target_buffer
                confluence_score = 78
            else:
                htf_trend = "SIDEWAYS"
                signal_type = "WAIT / NO TRADE"
                recommended_strike = "N/A"
                spot_entry = spot_price
                spot_sl = 0
                spot_target = 0
                confluence_score = 40

            if "BUY" in signal_type and current_trade["status"] == "IDLE":
                current_trade["status"] = "ACTIVE"
                current_trade["signal_type"] = signal_type
                current_trade["strike"] = recommended_strike
                current_trade["entry"] = spot_entry
                current_trade["target"] = spot_target
                current_trade["stop_loss"] = spot_sl

                sl_pts = round(abs(spot_entry - spot_sl), 2)
                tgt_pts = round(abs(spot_target - spot_entry), 2)
                msg = (f"🚨 *NIFTY {tf.upper()} SIGNAL* 🚨\nSignal: {signal_type}\nStrike: {recommended_strike}\nEntry: ₹{round(spot_entry, 2)}\nSL: ₹{round(spot_sl, 2)} (-{sl_pts} pts)\nTarget: ₹{round(spot_target, 2)} (+{tgt_pts} pts)")
                send_telegram_message(msg)

        sl_points = round(abs(spot_entry - spot_sl), 2) if spot_sl > 0 else 0
        target_points = round(abs(spot_target - spot_entry), 2) if spot_target > 0 else 0
        
        p_change_str = f"+{round(price_change, 2)}" if price_change >= 0 else f"{round(price_change, 2)}"
        p_change_pct_str = f"+{round(price_change_pct, 2)}" if price_change_pct >= 0 else f"{round(price_change_pct, 2)}"

        return render_template('index.html', 
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
                                     atr=round(atr, 2),
                                     ema_50=round(ema_50, 2),
                                     ema_9=round(ema_9, 2),
                                     ema_21=round(ema_21, 2),
                                     macd_signal=round(macd_signal, 4))

    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
