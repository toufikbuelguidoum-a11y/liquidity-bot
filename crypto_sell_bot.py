import ccxt
import pandas as pd
from datetime import datetime
import telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler
import logging

logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = "8716377272:AAGJAaCKwgS8z9yRAXB7_m6glYHr99VCPtA"
CHAT_ID = 8771579075

CHECK_INTERVAL_MIN = 5

exchange = ccxt.binance({'enableRateLimit': True})
bot = telegram.Bot(token=TELEGRAM_TOKEN)
scheduler = BackgroundScheduler()
bot_running = True

def send_message(text):
    try:
        bot.send_message(chat_id=CHAT_ID, text=text, parse_mode='HTML')
    except:
        pass

def fetch_ohlcv(symbol, timeframe):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df
    except Exception as e:
        return f"Error: {str(e)}"

async def check_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Fetching current conditions...")

    msg = f"<b>Live Market Conditions</b>\n{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

    # BTC Test
    df1h = fetch_ohlcv("BTC/USDT", "1h")
    if isinstance(df1h, str):
        msg += f"BTC: {df1h}\n\n"
    elif df1h is not None:
        try:
            price = df1h['close'].iloc[-1]
            rsi_val = 100 - (100 / (1 + (df1h['close'].diff().where(lambda x: x > 0, 0).rolling(14).mean() / 
                                         (-df1h['close'].diff().where(lambda x: x < 0, 0).rolling(14).mean()))))
            msg += f"<b>BTC</b>\nPrice: ${price:,.2f}\nRSI: {rsi_val.iloc[-1]:.1f}\n"
        except:
            msg += "BTC: Data fetched but calculation failed\n\n"
    else:
        msg += "BTC: No data\n\n"

    # PAXG Test
    df1h_p = fetch_ohlcv("PAXG/USDT", "1h")
    if isinstance(df1h_p, str):
        msg += f"PAXG: {df1h_p}"
    elif df1h_p is not None:
        try:
            price_p = df1h_p['close'].iloc[-1]
            msg += f"<b>PAXG</b>\nPrice: ${price_p:,.2f}"
        except:
            msg += "PAXG: Data fetched but calculation failed"
    else:
        msg += "PAXG: No data"

    await update.message.reply_text(msg, parse_mode='HTML')

def main():
    scheduler.start()
    send_message("🤖 Bot Online - Diagnostic Mode")

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("checknow", check_now))
    application.add_handler(CommandHandler("start", lambda u,c: u.message.reply_text("Bot is running")))

    application.run_polling()

if __name__ == "__main__":
    main()