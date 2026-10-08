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
        
        if data is None or data.empty or len(data) < 3:
            return "WAIT / NO TRADE", 0.0, 0.0, "+0.00", "+0.00%", 50.0, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, ""

        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        required_cols = ['Open', 'High', 'Low', 'Close']
        if not all(col in data.columns for col in required_cols):
            return "WAIT / NO TRADE", 0.0, 0.0, "+0.00", "+0.00%", 50.0, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, ""

        c1_open = float(data['Open'].iloc[-3])
        c1_close = float(data['Close'].iloc[-3])
        
        c2_open = float(data['Open'].iloc[-2])
        c2_close = float(data['Close'].iloc[-2])
        c2_high = float(data['High'].iloc[-2])
        c2_low = float(data['Low'].iloc[-2])
        
        c3_open = float(data['Open'].iloc[-1])
        c3_close = float(data['Close'].iloc[-1])
        
        spot_price = c3_close
        current_time = str(data.index[-1])

        prev_close = float(data['Close'].iloc[-2])
        price_change = spot_price - prev_close
        price_change_pct = (price_change / prev_close) * 100
        
        p_change_
