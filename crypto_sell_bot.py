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

# ================== YOUR CONFIG ==================
TELEGRAM_TOKEN = "8716377272:AAGJAaCKwgS8z9yRAXB7_m6glYHr99VCPtA"
CHAT_ID = 8771579075

# Strategy Settings
STOCH_1H_OB = 80
STOCH_4H_OB = 78
RSI_MIN = 68
CHECK_INTERVAL_MIN = 15
COOLDOWN_MINUTES = 180
# ================================================

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

# Indicators
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

def analyze_order_book():
    try:
        ob = exchange.fetch_order_book('BTC/USDT', limit=50)
        bids = pd.DataFrame(ob['bids'], columns=['price', 'amount'])
        asks = pd.DataFrame(ob['asks'], columns=['price', 'amount'])
        current = (bids['price'].iloc[0] + asks['price'].iloc[0]) / 2
        
        # Best Sell Zone
        asks['cum'] = asks['amount'].cumsum()
        best_sell = asks[asks['cum'] > 30]['price'].iloc[0] if len(asks[asks['cum'] > 30]) > 0 else None
        
        return {
            'current': round(current, 2),
            'best_sell': round(best_sell, 2) if best_sell else None
        }
    except:
        return None

def check_sell_signal():
    global last_signal_time
    if not bot_running or (last_signal_time and datetime.now() - last_signal_time < timedelta(minutes=COOLDOWN_MINUTES)):
        return

    try:
        df1h = fetch_ohlcv("BTC/USDT", "1h")
        df4h = fetch_ohlcv("BTC/USDT", "4h")
        if df1h is None or df4h is None:
            return

        k1h, d1h = stoch_rsi(df1h['close'])
        k4h, d4h = stoch_rsi(df4h['close'])
        
        price = df1h['close'].iloc[-1]
        rsi1h_val = rsi(df1h['close']).iloc[-1]
        rsi4h_val = rsi(df4h['close']).iloc[-1]

        obv1h = calculate_obv(df1h['close'], df1h['volume'])
        obv4h = calculate_obv(df4h['close'], df4h['volume'])

        over_1h = k1h.iloc[-1] > STOCH_1H_OB and d1h.iloc[-1] > STOCH_1H_OB
        over_4h = k4h.iloc[-1] > STOCH_4H_OB and d4h.iloc[-1] > STOCH_4H_OB
        rsi_ok = rsi1h_val >= RSI_MIN and rsi4h_val >= RSI_MIN
        bearish_cross = (k1h.iloc[-2] >= d1h.iloc[-2]) and (k1h.iloc[-1] < d1h.iloc[-1])
        obv_confirm = (obv1h.iloc[-1] < obv1h.iloc[-10]) or (obv4h.iloc[-1] < obv4h.iloc[-5])

        ema200 = df4h['close'].ewm(span=200, adjust=False).mean().iloc[-1]
        trend_ok = price <= ema200 * 1.04

        if over_1h and over_4h and rsi_ok and bearish_cross and trend_ok and obv_confirm:
            last_signal_time = datetime.now()
            ob = analyze_order_book()

            msg = f"🔴 <b>STRONG SELL SIGNAL</b> 🔥\n\nBTC @ ${price:,.2f}\n"
            msg += f"1H StochRSI: {round(k1h.iloc[-1],1)} | RSI: {round(rsi1h_val,1)}\n"
            msg += f"4H StochRSI: {round(k4h.iloc[-1],1)} | RSI: {round(rsi4h_val,1)}\n"
            if ob and ob['best_sell']:
                msg += f"🎯 Best Sell Zone: ${ob['best_sell']:,}\n"
            msg += f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            msg += "→ Reduce exposure on alts"

            send_message(msg)
    except:
        pass

# Telegram Commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot Started!", parse_mode='HTML')

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/status /stop /startbot /help", parse_mode='HTML')

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = "🟢 Running" if bot_running else "⭕ Paused"
    await update.message.reply_text(f"Status: {state}")

async def stop_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_running
    bot_running = False
    await update.message.reply_text("⭕ Signals paused.")

async def start_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_running
    bot_running = True
    await update.message.reply_text("✅ Signals resumed.")

def main():
    scheduler.add_job(check_sell_signal, 'interval', minutes=CHECK_INTERVAL_MIN)
    scheduler.start()
    send_message("🤖 LiquidityExtractionbot Online\nFull Strategy (StochRSI + OBV + Order Book) Active.")

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("stop", stop_bot))
    application.add_handler(CommandHandler("startbot", start_bot))

    application.run_polling()

if __name__ == "__main__":
    main()
