import ccxt
import pandas as pd
from datetime import datetime, timedelta
import telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler
import logging
import numpy as np

logging.basicConfig(level=logging.INFO)

# ================== CONFIG ==================
TELEGRAM_TOKEN = "8716377272:AAGJAaCKwgS8z9yRAXB7_m6glYHr99VCPtA"
CHAT_ID = 8771579075

# Assets
BTC_ALTS = ["ETH/USDT", "BNB/USDT", "SOL/USDT", "AVAX/USDT", "ADA/USDT", "LTC/USDT", "LINK/USDT"]
PAXG_SYMBOL = "PAXG/USDT"

# BTC Strategy Settings (Unchanged)
STOCH_1H_OB = 80
STOCH_4H_OB = 78
RSI_MIN = 68
CHECK_INTERVAL_MIN = 15
COOLDOWN_MINUTES = 180

# PAXG Strategy Settings (Gold)
PAXG_STOCH_1H = 83
PAXG_STOCH_4H = 80
PAXG_RSI_MIN = 70
# ===========================================

exchange = ccxt.binance({'enableRateLimit': True})
bot = telegram.Bot(token=TELEGRAM_TOKEN)
scheduler = BackgroundScheduler()
last_signal_time = None
bot_running = True

def send_message(text):
    try:
        bot.send_message(chat_id=CHAT_ID, text=text, parse_mode='HTML')
    except:
        pass

# ================== INDICATORS ==================
def rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def stoch_rsi(close, rsi_period=14, stoch_period=14, k=3, d=3):
    rsi_val = rsi(close, rsi_period)
    rsi_low = rsi_val.rolling(window=stoch_period).min()
    rsi_high = rsi_val.rolling(window=stoch_period).max()
    stoch = 100 * (rsi_val - rsi_low) / (rsi_high - rsi_low)
    k_line = stoch.rolling(window=k).mean()
    d_line = k_line.rolling(window=d).mean()
    return k_line, d_line

def calculate_obv(close, volume):
    df = pd.DataFrame({'close': close, 'volume': volume})
    df['obv'] = (np.sign(df['close'].diff()) * df['volume']).cumsum().fillna(0)
    return df['obv']

def fetch_ohlcv(symbol, timeframe, limit=300):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df
    except:
        return None

def analyze_order_book(symbol="BTC/USDT"):
    try:
        ob = exchange.fetch_order_book(symbol, limit=50)
        bids = pd.DataFrame(ob['bids'], columns=['price', 'amount'])
        asks = pd.DataFrame(ob['asks'], columns=['price', 'amount'])
        current = (bids['price'].iloc[0] + asks['price'].iloc[0]) / 2
        asks['cum'] = asks['amount'].cumsum()
        best_sell = asks[asks['cum'] > 30]['price'].iloc[0] if len(asks[asks['cum'] > 30]) > 0 else None
        return {'current': round(current, 2), 'best_sell': round(best_sell, 2) if best_sell else None}
    except:
        return None

# ================== MAIN LOGIC ==================
def check_signals():
    global last_signal_time
    if not bot_running:
        return
    if last_signal_time and datetime.now() - last_signal_time < timedelta(minutes=COOLDOWN_MINUTES):
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ================== BTC STRATEGY (Unchanged) ==================
    try:
        df1h = fetch_ohlcv("BTC/USDT", "1h")
        df4h = fetch_ohlcv("BTC/USDT", "4h")
        if df1h is not None and df4h is not None:
            k1h, d1h = stoch_rsi(df1h['close'])
            k4h, d4h = stoch_rsi(df4h['close'])
            price = df1h['close'].iloc[-1]
            rsi1h_val = rsi(df1h['close']).iloc[-1]
            rsi4h_val = rsi(df4h['close']).iloc[-1]

            over_1h = k1h.iloc[-1] > STOCH_1H_OB and d1h.iloc[-1] > STOCH_1H_OB
            over_4h = k4h.iloc[-1] > STOCH_4H_OB and d4h.iloc[-1] > STOCH_4H_OB
            rsi_ok = rsi1h_val >= RSI_MIN and rsi4h_val >= RSI_MIN
            bearish_cross = (k1h.iloc[-2] >= d1h.iloc[-2]) and (k1h.iloc[-1] < d1h.iloc[-1])

            if over_1h and over_4h and rsi_ok and bearish_cross:
                last_signal_time = datetime.now()
                ob = analyze_order_book("BTC/USDT")
                msg = f"🔴 <b>BTC STRONG SELL SIGNAL</b>\nBTC @ ${price:,.2f}\n"
                if ob and ob['best_sell']:
                    msg += f"🎯 Best Sell: ${ob['best_sell']:,}\n"
                msg += f"Time: {timestamp}\n→ Reduce on alts"
                send_message(msg)
    except:
        pass

    # ================== PAXG STRATEGY (New - Independent) ==================
    try:
        df1h_p = fetch_ohlcv(PAXG_SYMBOL, "1h")
        df4h_p = fetch_ohlcv(PAXG_SYMBOL, "4h")
        if df1h_p is not None and df4h_p is not None:
            k1h_p, d1h_p = stoch_rsi(df1h_p['close'])
            k4h_p, d4h_p = stoch_rsi(df4h_p['close'])
            paxg_price = df1h_p['close'].iloc[-1]
            rsi1h_p = rsi(df1h_p['close']).iloc[-1]
            rsi4h_p = rsi(df4h_p['close']).iloc[-1]

            if (k1h_p.iloc[-1] > PAXG_STOCH_1H and d1h_p.iloc[-1] > PAXG_STOCH_1H and
                k4h_p.iloc[-1] > PAXG_STOCH_4H and d4h_p.iloc[-1] > PAXG_STOCH_4H and
                rsi1h_p >= PAXG_RSI_MIN and rsi4h_p >= PAXG_RSI_MIN):
                
                last_signal_time = datetime.now()
                ob_p = analyze_order_book(PAXG_SYMBOL)
                msg = f"🟡 <b>PAXG SELL SIGNAL (Gold)</b>\nPAXG @ ${paxg_price:,.2f}\n"
                if ob_p and ob_p['best_sell']:
                    msg += f"🎯 Best Sell Zone: ${ob_p['best_sell']:,}\n"
                msg += f"Time: {timestamp}\n→ Consider taking profit on PAXG"
                send_message(msg)
    except:
        pass

# ================== COMMANDS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot Started!\nMonitoring BTC + PAXG independently", parse_mode='HTML')

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = "🟢 Running" if bot_running else "⭕ Paused"
    await update.message.reply_text(f"Bot Status: {state}\nMonitoring: BTC Strategy + PAXG Strategy")

# ... (stop, startbot, help commands remain the same)

def main():
    scheduler.add_job(check_signals, 'interval', minutes=CHECK_INTERVAL_MIN)
    scheduler.start()
    send_message("🤖 <b>LiquidityExtractionbot Online</b>\nBTC Full Strategy + Independent PAXG Monitoring Active.")

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("stop", stop_bot))
    application.add_handler(CommandHandler("startbot", start_bot))

    application.run_polling()

if __name__ == "__main__":
    main()