import os
import sys
from datetime import datetime
import requests

try:
    from flask import Flask, jsonify, send_file, request, render_template
    import yfinance as yf
    import pandas as pd
    import numpy as np
except ImportError:
    os.system(f"{sys.executable} -m pip install flask yfinance pandas numpy requests")
    from flask import Flask, jsonify, send_file, request, render_template
    import yfinance as yf
    import pandas as pd
    import numpy as np
    import requests

app = Flask(__name__, template_folder='.')

# ==========================================
# 🚀 TELEGRAM BOT CONFIGURATION
# ==========================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8993766701:AAEVS6cCjvVOX23YpoZxzT_nk72ghd9Hn-Y")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8637158829")

def send_telegram_alert(message):
    """Utility function to send instant notifications to Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")

# --- GLOBAL STATE FOR LOCKING & TRADE HISTORY TRACKING ---
trade_state = {
    'active': False,
    'action': 'WAIT / NO TRADE',
    'entry': 0.0,
    'sl': 0.0,
    'tp': 0.0,
    'opt_strike': '--',
    'opt_buy': '--',
    'opt_sl': '--',
    'opt_tp': '--',
    'cooldown_until': 0
}

trade_stats = {
    'total_trades': 0,
    'target_hits': 0,
    'sl_hits': 0,
    'win_rate': 0.0,
    'history': []
}

@app.route('/')
def home():
    try:
        return render_template("nifty_50_trading_terminal.html")
    except Exception as e:
        return f"Trading Terminal HTML file error: {str(e)}"

@app.route('/pdf-tool')
def pdf_tool():
    try:
        return render_template("pdf_to_excel.html")
    except Exception as e:
        return f"PDF Tool HTML file error: {str(e)}"

@app.route('/api/data')
def get_data():
    global trade_state, trade_stats
    try:
        tf = request.args.get('tf', '5m')
        fetch_tf = '1m' if tf == '3m' else tf
        
        # RAM optimization: 1m/3m ke liye sirf 1 din ka data fetch hoga taaki memory limit cross na ho
        period = '1d' if fetch_tf in ['1m', '3m'] else ('7d' if fetch_tf == '15m' else '30d')

        df = yf.download(tickers='^NSEI', period=period, interval=fetch_tf, progress=False)
        
        if df is None or df.empty:
            ticker = yf.Ticker('^NSEI')
            df = ticker.history(period=period, interval=fetch_tf)

        if df is None or df.empty:
            df = yf.download(tickers='^NSEI', period='1mo', interval='1d', progress=False)

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.dropna()

        if df.empty:
            return jsonify({'error': 'Data fetch failed from Yahoo Finance'})

        close = df['Close'].squeeze()
        high = df['High'].squeeze()
        low = df['Low'].squeeze()
        volume = df['Volume'].squeeze() if 'Volume' in df.columns else pd.Series(0, index=df.index)

        if tf == '3m' and not df.empty:
            df_resampled = df.resample('3min').agg({
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum'
            }).dropna()
            if not df_resampled.empty:
                df = df_resampled
                close = df['Close'].squeeze()
                high = df['High'].squeeze()
                low = df['Low'].squeeze()
                volume = df['Volume'].squeeze()

        # Fetch 15M HTF Data (optimized period)
        df_15m = yf.download(tickers='^NSEI', period='2d', interval='15m', progress=False)
        if isinstance(df_15m.columns, pd.MultiIndex):
            df_15m.columns = df_15m.columns.get_level_values(0)
        df_15m = df_15m.dropna()
        if df_15m.empty:
            df_15m = df.copy()
        
        close_15m = df_15m['Close'].squeeze()
        htf_ema50 = close_15m.ewm(span=50, adjust=False).mean().iloc[-1] if len(close_15m) >= 50 else close_15m.iloc[-1]
        htf_close = float(close_15m.iloc[-1])
        htf_trend = "BULLISH" if htf_close >= htf_ema50 else "BEARISH"

        latest_price = float(close.iloc[-1])
        prev_close = float(close.iloc[-2]) if len(close) > 1 else latest_price
        
        change = round(latest_price - prev_close, 2)
        change_pct = round((change / prev_close) * 100, 2)

        tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
        atr = float(tr.tail(14).mean()) if len(tr) >= 14 else 18.0
        
        sl_points = max(18.0, round(atr * 2.0, 1))
        tp_points = round(sl_points * 1.5, 1)

        ema9 = close.ewm(span=9, adjust=False).mean()
        ema21 = close.ewm(span=21, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()
        
        v_ema9 = float(ema9.iloc[-1])
        v_ema21 = float(ema21.iloc[-1])
        v_ema50 = float(ema50.iloc[-1])

        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        v_rsi = float(rsi.iloc[-1]) if not np.isnan(rsi.iloc[-1]) else 50.0

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        macd_signal = macd.ewm(span=9, adjust=False).mean()
        v_macd = float(macd.iloc[-1])
        v_macd_sig = float(macd_signal.iloc[-1])

        recent_20_high = float(high.tail(20).max())
        recent_20_low = float(low.tail(20).min())
        fib_range = recent_20_high - recent_20_low
        fib_50 = recent_20_high - (0.50 * fib_range)
        fib_618 = recent_20_high - (0.618 * fib_range)

        if latest_price >= fib_618 and latest_price <= fib_50:
            fib_status = "Golden Zone (High Prob)"
            fib_score = 20
        elif latest_price > fib_50:
            fib_status = "Bullish Zone"
            fib_score = 10
        else:
            fib_status = "Bearish Zone"
            fib_score = -10

        v_curr = float(volume.iloc[-1]) if len(volume) > 0 else 0
        v_sma20 = float(volume.tail(20).mean()) if len(volume) >= 20 else v_curr
        if v_curr > (1.5 * v_sma20) and v_sma20 > 0:
            vol_status = "High Volume Spike"
            vol_score = 20 if latest_price >= prev_close else -20
        elif v_curr > v_sma20 and v_sma20 > 0:
            vol_status = "Above Avg Volume"
            vol_score = 10 if latest_price >= prev_close else -10
        else:
            vol_status = "Low Volume (Sideways)"
            vol_score = -15

        score = 0
        score += 20 if latest_price > v_ema50 else -20
        ema_status = "9 EMA > 21 EMA" if v_ema9 > v_ema21 else "9 EMA < 21 EMA"
        score += 20 if v_ema9 > v_ema21 else -20

        if 55 <= v_rsi <= 70:
            rsi_status = f"{v_rsi:.1f} (Bullish Momentum)"
            score += 20
        elif 30 <= v_rsi <= 45:
            rsi_status = f"{v_rsi:.1f} (Bearish Momentum)"
            score -= 20
        else:
            rsi_status = f"{v_rsi:.1f} (Neutral/Overbought)"
            score += 0

        macd_status = "Bullish Cross" if v_macd > v_macd_sig else "Bearish Cross"
        score += 20 if v_macd > v_macd_sig else -20

        score += fib_score + vol_score
        score = max(-100, min(100, score))

        current_time_obj = df.index[-1]
        current_time_str = current_time_obj.strftime('%H:%M')
        time_minutes = current_time_obj.hour * 60 + current_time_obj.minute
        is_no_trade_zone = (555 <= time_minutes <= 565) or (810 <= time_minutes <= 840)

        # --- POSITION LOCKING, EXIT & TELEGRAM ALERT ENGINE ---
        if trade_state['active']:
            if "CALL" in trade_state['action']:
                if latest_price >= trade_state['tp']:
                    trade_stats['total_trades'] += 1
                    trade_stats['target_hits'] += 1
                    trade_stats['history'].insert(0, {
                        'time': current_time_str, 'type': 'BUY CE', 'strike': trade_state['opt_strike'],
                        'entry': trade_state['entry'], 'exit': latest_price, 'result': 'TARGET HIT 🎯', 'color': '#089981'
                    })
                    
                    msg = f"🎯 *TARGET HIT ALERT! (NIFTY 50)*\n\nTrade: BUY CE ({trade_state['opt_strike']})\nEntry: ₹{trade_state['entry']}\nExit Price: ₹{latest_price}\nResult: TARGET REACHED 🚀\nTime: {current_time_str}"
                    send_telegram_alert(msg)

                    trade_state['active'] = False
                    trade_state['cooldown_until'] = 3

                elif latest_price <= trade_state['sl']:
                    trade_stats['total_trades'] += 1
                    trade_stats['sl_hits'] += 1
                    trade_stats['history'].insert(0, {
                        'time': current_time_str, 'type': 'BUY CE', 'strike': trade_state['opt_strike'],
                        'entry': trade_state['entry'], 'exit': latest_price, 'result': 'STOP LOSS HIT ❌', 'color': '#f23645'
                    })
                    
                    msg = f"❌ *STOP LOSS HIT ALERT! (NIFTY 50)*\n\nTrade: BUY CE ({trade_state['opt_strike']})\nEntry: ₹{trade_state['entry']}\nExit Price: ₹{latest_price}\nResult: STOP LOSS HIT\nTime: {current_time_str}"
                    send_telegram_alert(msg)

                    trade_state['active'] = False
                    trade_state['cooldown_until'] = 3

            elif "PUT" in trade_state['action']:
                if latest_price <= trade_state['tp']:
                    trade_stats['total_trades'] += 1
                    trade_stats['target_hits'] += 1
                    trade_stats['history'].insert(0, {
                        'time': current_time_str, 'type': 'BUY PE', 'strike': trade_state['opt_strike'],
                        'entry': trade_state['entry'], 'exit': latest_price, 'result': 'TARGET HIT 🎯', 'color': '#089981'
                    })
                    
                    msg = f"🎯 *TARGET HIT ALERT! (NIFTY 50)*\n\nTrade: BUY PE ({trade_state['opt_strike']})\nEntry: ₹{trade_state['entry']}\nExit Price: ₹{latest_price}\nResult: TARGET REACHED 🚀\nTime: {current_time_str}"
                    send_telegram_alert(msg)

                    trade_state['active'] = False
                    trade_state['cooldown_until'] = 3

                elif latest_price >= trade_state['sl']:
                    trade_stats['total_trades'] += 1
                    trade_stats['sl_hits'] += 1
                    trade_stats['history'].insert(0, {
                        'time': current_time_str, 'type': 'BUY PE', 'strike': trade_state['opt_strike'],
                        'entry': trade_state['entry'], 'exit': latest_price, 'result': 'STOP LOSS HIT ❌', 'color': '#f23645'
                    })
                    
                    msg = f"❌ *STOP LOSS HIT ALERT! (NIFTY 50)*\n\nTrade: BUY PE ({trade_state['opt_strike']})\nEntry: ₹{trade_state['entry']}\nExit Price: ₹{latest_price}\nResult: STOP LOSS HIT\nTime: {current_time_str}"
                    send_telegram_alert(msg)

                    trade_state['active'] = False
                    trade_state['cooldown_until'] = 3

        if not trade_state['active'] and trade_state['cooldown_until'] > 0:
            trade_state['cooldown_until'] -= 1

        if not trade_state['active']:
            atm_strike = int(round(latest_price / 50.0) * 50)
            est_option_premium = round(latest_price * 0.008, 1)
            option_sl_pts = round(sl_points * 0.50, 1)
            option_tp_pts = round(tp_points * 0.50, 1)

            if is_no_trade_zone:
                trade_state['action'] = "WAIT / NO TRADE ZONE"
                trade_state['entry'] = round(latest_price, 2)
                trade_state['sl'] = round(latest_price - sl_points, 2)
                trade_state['tp'] = round(latest_price + tp_points, 2)
                trade_state['opt_strike'] = f"{atm_strike} (Session Rest)"
                trade_state['opt_buy'] = "N/A"
                trade_state['opt_sl'] = "N/A"
                trade_state['opt_tp'] = "N/A"

            elif trade_state['cooldown_until'] > 0:
                trade_state['action'] = f"WAIT / COOLDOWN ({trade_state['cooldown_until']} BAR)"
                trade_state['entry'] = round(latest_price, 2)
                trade_state['sl'] = round(latest_price - sl_points, 2)
                trade_state['tp'] = round(latest_price + tp_points, 2)
                trade_state['opt_strike'] = f"{atm_strike} CE/PE"
                trade_state['opt_buy'] = "N/A"

            elif score >= 60 and htf_trend == "BULLISH":
                trade_state['active'] = True
                trade_state['action'] = "BUY CE / CALL"
                trade_state['entry'] = round(latest_price, 2)
                trade_state['sl'] = round(latest_price - sl_points, 2)
                trade_state['tp'] = round(latest_price + tp_points, 2)
                trade_state['opt_strike'] = f"{atm_strike} CE"
                trade_state['opt_buy'] = f"₹{round(est_option_premium - 5, 1)} - ₹{round(est_option_premium + 5, 1)}"
                trade_state['opt_sl'] = f"₹{round(max(5, est_option_premium - option_sl_pts), 1)} (-{option_sl_pts} pts)"
                trade_state['opt_tp'] = f"₹{round(est_option_premium + option_tp_pts, 1)} (+{option_tp_pts} pts)"

                msg = (f"🚀 *NEW TRADE SIGNAL LOCKED! (BUY CALL)*\n\n"
                       f"📈 *Instrument:* NIFTY 50 ({atm_strike} CE)\n"
                       f"🎯 *Spot Entry:* ₹{trade_state['entry']}\n"
                       f"🛡️ *Spot StopLoss:* ₹{trade_state['sl']}\n"
                       f"🏆 *Spot Target:* ₹{trade_state['tp']}\n"
                       f"📊 *Confluence Score:* +{score}/100\n"
                       f"⏰ *Time:* {current_time_str}")
                send_telegram_alert(msg)

            elif score <= -60 and htf_trend == "BEARISH":
                trade_state['active'] = True
                trade_state['action'] = "BUY PE / PUT"
                trade_state['entry'] = round(latest_price, 2)
                trade_state['sl'] = round(latest_price + sl_points, 2)
                trade_state['tp'] = round(latest_price - tp_points, 2)
                trade_state['opt_strike'] = f"{atm_strike} PE"
                trade_state['opt_buy'] = f"₹{round(est_option_premium - 5, 1)} - ₹{round(est_option_premium + 5, 1)}"
                trade_state['opt_sl'] = f"₹{round(max(5, est_option_premium - option_sl_pts), 1)} (-{option_sl_pts} pts)"
                trade_state['opt_tp'] = f"₹{round(est_option_premium + option_tp_pts, 1)} (+{option_tp_pts} pts)"

                msg = (f"🔻 *NEW TRADE SIGNAL LOCKED! (BUY PUT)*\n\n"
                       f"📉 *Instrument:* NIFTY 50 ({atm_strike} PE)\n"
                       f"🎯 *Spot Entry:* ₹{trade_state['entry']}\n"
                       f"🛡️ *Spot StopLoss:* ₹{trade_state['sl']}\n"
                       f"🏆 *Spot Target:* ₹{trade_state['tp']}\n"
                       f"📊 *Confluence Score:* {score}/100\n"
                       f"⏰ *Time:* {current_time_str}")
                send_telegram_alert(msg)

            else:
                trade_state['action'] = "WAIT / LOW CONFLUENCE (<60)"
                trade_state['entry'] = round(latest_price, 2)
                trade_state['sl'] = round(latest_price - sl_points, 2)
                trade_state['tp'] = round(latest_price + tp_points, 2)
                trade_state['opt_strike'] = f"{atm_strike} CE/PE"
                trade_state['opt_buy'] = "N/A"
                trade_state['opt_sl'] = "N/A"
                trade_state['opt_tp'] = "N/A"

        if trade_stats['total_trades'] > 0:
            trade_stats['win_rate'] = round((trade_stats['target_hits'] / trade_stats['total_trades']) * 100, 1)

        recent_df = df.tail(30).copy()
        recent_df['Time'] = recent_df.index.strftime('%H:%M')
        
        chart_data = []
        for idx, row in recent_df.iterrows():
            chart_data.append({
                'time': row['Time'],
                'close': round(float(row['Close']), 2),
                'ema9': round(float(ema9.loc[idx]), 2),
                'ema21': round(float(ema21.loc[idx]), 2)
            })

        return jsonify({
            'tf': tf,
            'price': round(latest_price, 2),
            'change': change,
            'change_pct': change_pct,
            'score': score,
            'htf_trend': htf_trend,
            'atr': round(atr, 1),
            'trade': {
                'action': trade_state['action'],
                'entry': trade_state['entry'],
                'sl': trade_state['sl'],
                'tp': trade_state['tp'],
                'rr': "1 : 1.5",
                'is_locked': trade_state['active']
            },
            'option_trade': {
                'strike': trade_state['opt_strike'],
                'buy_price': trade_state['opt_buy'],
                'sl': trade_state['opt_sl'],
                'target': trade_state['opt_tp']
            },
            'stats': {
                'total': trade_stats['total_trades'],
                'targets': trade_stats['target_hits'],
                'sls': trade_stats['sl_hits'],
                'win_rate': trade_stats['win_rate'],
                'history': trade_stats['history'][:10]
            },
            'indicators': {
                '15M HTF Trend': {'status': htf_trend, 'score': 0},
                '50 EMA Trend': {'status': "Above 50 EMA" if latest_price > v_ema50 else "Below 50 EMA", 'score': 20 if latest_price > v_ema50 else -20},
                'EMA 9/21': {'status': ema_status, 'score': 20 if v_ema9 > v_ema21 else -20},
                'RSI Quality': {'status': rsi_status, 'score': 20 if 55 <= v_rsi <= 70 else (-20 if 30 <= v_rsi <= 45 else 0)},
                'MACD Cross': {'status': macd_status, 'score': 20 if v_macd > v_macd_sig else -20},
                'Fibonacci': {'status': fib_status, 'score': fib_score},
                'Volume Filter': {'status': vol_status, 'score': vol_score}
            },
            'chart': chart_data
        })
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'details': traceback.format_exc()})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
