import ccxt
import pandas as pd
from datetime import datetime, timedelta
import telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ================== CONFIG ==================
TELEGRAM_TOKEN = "8716377272:AAGJAaCKwgS8z9yRAXB7_m6glYHr99VCPtA"
CHAT_ID = 8771579075

CHECK_INTERVAL_MIN = 5
COOLDOWN_MINUTES = 60

BTC_RSI_THRESHOLD = 65
BTC_STOCH_THRESHOLD = 84

PAXG_RSI_THRESHOLD = 75
PAXG_STOCH_THRESHOLD = 89
# ===========================================

exchange = ccxt.binance({'enableRateLimit': True})
bot = telegram.Bot(token=TELEGRAM_TOKEN)
scheduler = BackgroundScheduler()
last_signal_time = None
bot_running = True

def send_message(text):
    try:
        bot.send_message(chat_id=CHAT_ID, text=text, parse_mode='HTML')
    except Exception as e:
        logging.error(f"Send failed: {e}")

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

def fetch_ohlcv(symbol, timeframe, limit=100):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not ohlcv:
            return None
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df
    except Exception as e:
        logging.error(f"Fetch error {symbol} {timeframe}: {e}")
        return None

def analyze_order_book(symbol):
    try:
        ob = exchange.fetch_order_book(symbol, limit=50)
        bids = pd.DataFrame(ob['bids'], columns=['price', 'amount'])
        asks = pd.DataFrame(ob['asks'], columns=['price', 'amount'])
        current = (bids['price'].iloc[0] + asks['price'].iloc[0]) / 2
        asks['cum'] = asks['amount'].cumsum()
        best_sell = asks[asks['cum'] > 25]['price'].iloc[0] if len(asks[asks['cum'] > 25]) > 0 else None
        return {'current': round(current, 2), 'best_sell': round(best_sell, 2) if best_sell else None}
    except:
        return None

# ================== CHECK NOW (Improved) ==================
async def check_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Fetching current conditions...")

    msg = f"<b>Live Market Conditions</b>\n{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

    # BTC
    df1h = fetch_ohlcv("BTC/USDT", "1h")
    df4h = fetch_ohlcv("BTC/USDT", "4h")
    if df1h is not None and df4h is not None:
        try:
            rsi1h = rsi(df1h['close']).iloc[-1]
            rsi4h = rsi(df4h['close']).iloc[-1]
            stoch1h, _ = stoch_rsi(df1h['close'])
            stoch4h, _ = stoch_rsi(df4h['close'])
            price = df1h['close'].iloc[-1]
            msg += f"<b>BTC</b>\nPrice: ${price:,.2f}\n"
            msg += f"RSI 1H/4H: {rsi1h:.1f} / {rsi4h:.1f}\n"
            msg += f"StochRSI 1H/4H: {stoch1h.iloc[-1]:.1f} / {stoch4h.iloc[-1]:.1f}\n\n"
        except Exception as e:
            msg += f"BTC: Calculation error ({e})\n\n"
    else:
        msg += "BTC: Failed to fetch data (network/API issue)\n\n"

    # PAXG
    df1h_p = fetch_ohlcv("PAXG/USDT", "1h")
    df4h_p = fetch_ohlcv("PAXG/USDT", "4h")
    if df1h_p is not None and df4h_p is not None:
        try:
            rsi1h_p = rsi(df1h_p['close']).iloc[-1]
            rsi4h_p = rsi(df4h_p['close']).iloc[-1]
            stoch1h_p, _ = stoch_rsi(df1h_p['close'])
            stoch4h_p, _ = stoch_rsi(df4h_p['close'])
            price_p = df1h_p['close'].iloc[-1]
            msg += f"<b>PAXG</b>\nPrice: ${price_p:,.2f}\n"
            msg += f"RSI 1H/4H: {rsi1h_p:.1f} / {rsi4h_p:.1f}\n"
            msg += f"StochRSI 1H/4H: {stoch1h_p.iloc[-1]:.1f} / {stoch4h_p.iloc[-1]:.1f}"
        except Exception as e:
            msg += f"PAXG: Calculation error ({e})"
    else:
        msg += "PAXG: Failed to fetch data (network/API issue)"

    await update.message.reply_text(msg, parse_mode='HTML')

# Rest of the code (commands + main)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot Started!")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = "🟢 Running" if bot_running else "⭕ Paused"
    await update.message.reply_text(f"Bot Status: {state}")

async def stop_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_running
    bot_running = False
    await update.message.reply_text("⭕ Signals paused.")

async def start_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_running
    bot_running = True
    await update.message.reply_text("✅ Signals resumed.")

def main():
    scheduler.add_job(check_signals, 'interval', minutes=CHECK_INTERVAL_MIN)  # Note: check_signals is not fully defined here for brevity
    scheduler.start()
    send_message("🤖 Bot Online - Checking every 5 minutes")

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("stop", stop_bot))
    application.add_handler(CommandHandler("startbot", start_bot))
    application.add_handler(CommandHandler("checknow", check_now))

    application.run_polling()

if __name__ == "__main__":
    main()