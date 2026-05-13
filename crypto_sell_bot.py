import ccxt
import pandas as pd
from datetime import datetime, timedelta
import telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler
import logging
import asyncio

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
scheduler = BackgroundScheduler()
last_signal_time = None
bot_running = True

# Create bot instance
bot = telegram.Bot(token=TELEGRAM_TOKEN)

def send_message(text):
    try:
        asyncio.run(bot.send_message(chat_id=CHAT_ID, text=text, parse_mode='HTML'))
        logging.info("Message sent successfully")
    except Exception as e:
        logging.error(f"Failed to send message: {e}")

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

def fetch_ohlcv(symbol, timeframe, limit=150):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df
    except Exception as e:
        logging.error(f"Fetch error {symbol}: {e}")
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

def check_signals():
    global last_signal_time
    if not bot_running:
        return
    if last_signal_time and datetime.now() - last_signal_time < timedelta(minutes=COOLDOWN_MINUTES):
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # BTC
    try:
        df1h = fetch_ohlcv("BTC/USDT", "1h")
        df4h = fetch_ohlcv("BTC/USDT", "4h")
        if df1h and df4h:
            rsi1h = rsi(df1h['close']).iloc[-1]
            rsi4h = rsi(df4h['close']).iloc[-1]
            stoch1h, _ = stoch_rsi(df1h['close'])
            stoch4h, _ = stoch_rsi(df4h['close'])
            
            if (rsi1h > BTC_RSI_THRESHOLD and rsi4h > BTC_RSI_THRESHOLD and
                stoch1h.iloc[-1] > BTC_STOCH_THRESHOLD and stoch4h.iloc[-1] > BTC_STOCH_THRESHOLD):
                ob = analyze_order_book("BTC/USDT")
                msg = f"🔴 <b>BTC SELL SIGNAL</b>\nBTC @ ${ob['current']:,.2f}\n"
                msg += f"RSI: {rsi1h:.1f}/{rsi4h:.1f} | StochRSI: {stoch1h.iloc[-1]:.1f}\n"
                if ob.get('best_sell'):
                    msg += f"🎯 Best Sell: ${ob['best_sell']:,}\n"
                msg += f"Time: {timestamp}\n→ Reduce alts"
                send_message(msg)
                last_signal_time = datetime.now()
    except Exception as e:
        logging.error(f"BTC signal error: {e}")

    # PAXG
    try:
        df1h_p = fetch_ohlcv("PAXG/USDT", "1h")
        df4h_p = fetch_ohlcv("PAXG/USDT", "4h")
        if df1h_p and df4h_p:
            rsi1h_p = rsi(df1h_p['close']).iloc[-1]
            rsi4h_p = rsi(df4h_p['close']).iloc[-1]
            stoch1h_p, _ = stoch_rsi(df1h_p['close'])
            stoch4h_p, _ = stoch_rsi(df4h_p['close'])
            
            if (rsi1h_p > PAXG_RSI_THRESHOLD and rsi4h_p > PAXG_RSI_THRESHOLD and
                stoch1h_p.iloc[-1] > PAXG_STOCH_THRESHOLD and stoch4h_p.iloc[-1] > PAXG_STOCH_THRESHOLD):
                ob_p = analyze_order_book("PAXG/USDT")
                msg = f"🟡 <b>PAXG SELL SIGNAL</b>\nPAXG @ ${ob_p['current']:,.2f}\n"
                msg += f"RSI: {rsi1h_p:.1f}/{rsi4h_p:.1f} | StochRSI: {stoch1h_p.iloc[-1]:.1f}\n"
                if ob_p.get('best_sell'):
                    msg += f"🎯 Best Sell: ${ob_p['best_sell']:,}\n"
                msg += f"Time: {timestamp}\n→ Take profit on PAXG"
                send_message(msg)
                last_signal_time = datetime.now()
    except Exception as e:
        logging.error(f"PAXG signal error: {e}")

# Commands
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

async def check_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Fetching current conditions...")
    # For now, just trigger check_signals
    check_signals()

def main():
    scheduler.add_job(check_signals, 'interval', minutes=CHECK_INTERVAL_MIN)
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