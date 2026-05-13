import ccxt
import pandas as pd
from datetime import datetime
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler

logging.basicConfig(level=logging.INFO)

# Load these securely in production!
TELEGRAM_TOKEN = "YOUR_TELEGRAM_TOKEN"
CHAT_ID = 123456789

CHECK_INTERVAL_MIN = 5

exchange = ccxt.binance({'enableRateLimit': True})
scheduler = BackgroundScheduler()

def fetch_ohlcv(symbol, timeframe):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df
    except Exception as e:
        logging.error(f"Error fetching {symbol}: {e}")
        return None

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    return rsi

async def check_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Fetching current conditions...")

    msg = f"<b>Live Market Conditions</b>\n{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

    # BTC
    df1h = fetch_ohlcv("BTC/USDT", "1h")
    if df1h is not None and not df1h.empty:
        try:
            price = df1h['close'].iloc[-1]
            rsi_series = calculate_rsi(df1h['close'])
            if not rsi_series.dropna().empty:
                rsi_val = rsi_series.iloc[-1]
                msg += f"<b>BTC</b>\nPrice: ${price:,.2f}\nRSI: {rsi_val:.1f}\n\n"
            else:
                msg += f"<b>BTC</b>\nPrice: ${price:,.2f}\nRSI: Not available\n\n"
        except Exception as e:
            logging.error(f"BTC calc failed: {e}")
            msg += "BTC: Data fetched but calculation failed\n\n"
    else:
        msg += "BTC: No data\n\n"

    # PAXG
    df1h_p = fetch_ohlcv("PAXG/USDT", "1h")
    if df1h_p is not None and not df1h_p.empty:
        try:
            price_p = df1h_p['close'].iloc[-1]
            msg += f"<b>PAXG</b>\nPrice: ${price_p:,.2f}\n"
        except Exception as e:
            logging.error(f"PAXG calc failed: {e}")
            msg += "PAXG: Data fetched but calculation failed\n"
    else:
        msg += "PAXG: No data\n"

    await update.message.reply_text(msg, parse_mode='HTML')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot is running")

def main():
    scheduler.start()
    logging.info("Scheduler started")

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("checknow", check_now))
    application.add_handler(CommandHandler("start", start))

    application.run_polling()

if __name__ == "__main__":
    main()