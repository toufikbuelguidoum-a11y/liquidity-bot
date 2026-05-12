import ccxt
import pandas as pd
from datetime import datetime, timedelta
import telegram
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler
import logging

logging.basicConfig(level=logging.INFO)

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
        logging.error(f"Failed to fetch OHLCV for {symbol}: {e}")
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
    except Exception as e:
        logging.error(f"Failed to analyze order book for {symbol}: {e}")
        return None


def check_signals():
    global last_signal_time, bot_running

    if not bot_running:
        return

    if last_signal_time and datetime.now() - last_signal_time < timedelta(minutes=COOLDOWN_MINUTES):
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    signal_sent = False

    # BTC
    try:
        df1h = fetch_ohlcv("BTC/USDT", "1h")
        df4h = fetch_ohlcv("BTC/USDT", "4h")

        if df1h is not None and df4h is not None:
            rsi1h = rsi(df1h['close']).iloc[-1]
            rsi4h = rsi(df4h['close']).iloc[-1]
            stoch1h, _ = stoch_rsi(df1h['close'])
            stoch4h, _ = stoch_rsi(df4h['close'])

            if (rsi1h > BTC_RSI_THRESHOLD and rsi4h > BTC_RSI_THRESHOLD and
                    stoch1h.iloc[-1] > BTC_STOCH_THRESHOLD and stoch4h.iloc[-1] > BTC_STOCH_THRESHOLD):
                ob = analyze_order_book("BTC/USDT")
                if ob:
                    msg = f"🔴 <b>BTC SELL SIGNAL</b>\nBTC @ ${ob['current']:,.2f}\n"
                    msg += f"RSI: {rsi1h:.1f}/{rsi4h:.1f} | StochRSI: {stoch1h.iloc[-1]:.1f}\n"
                    if ob['best_sell']:
                        msg += f"🎯 Best Sell: ${ob['best_sell']:,}\n"
                    msg += f"Time: {timestamp}\n→ Reduce alts"
                    send_message(msg)
                    signal_sent = True
    except Exception as e:
        logging.error(f"BTC signal check failed: {e}")

    # PAXG
    try:
        df1h_p = fetch_ohlcv("PAXG/USDT", "1h")
        df4h_p = fetch_ohlcv("PAXG/USDT", "4h")

        if df1h_p is not None and df4h_p is not None:
            rsi1h_p = rsi(df1h_p['close']).iloc[-1]
            rsi4h_p = rsi(df4h_p['close']).iloc[-1]
            stoch1h_p, _ = stoch_rsi(df1h_p['close'])
            stoch4h_p, _ = stoch_rsi(df4h_p['close'])

            if (rsi1h_p > PAXG_RSI_THRESHOLD and rsi4h_p > PAXG_RSI_THRESHOLD and
                    stoch1h_p.iloc[-1] > PAXG_STOCH_THRESHOLD and stoch4h_p.iloc[-1] > PAXG_STOCH_THRESHOLD):
                ob_p = analyze_order_book("PAXG/USDT")
                if ob_p:
                    msg = f"🟡 <b>PAXG SELL SIGNAL</b>\nPAXG @ ${ob_p['current']:,.2f}\n"
                    msg += f"RSI: {rsi1h_p:.1f}/{rsi4h_p:.1f} | StochRSI: {stoch1h_p.iloc[-1]:.1f}\n"
                    if ob_p['best_sell']:
                        msg += f"🎯 Best Sell: ${ob_p['best_sell']:,}\n"
                    msg += f"Time: {timestamp}\n→ Reduce altcoins"
                    send_message(msg)
                    signal_sent = True
    except Exception as e:
        logging.error(f"PAXG signal check failed: {e}")

    if signal_sent:
        last_signal_time = datetime.now()


# Schedule the signal checks
scheduler.add_job(check_signals, 'interval', minutes=CHECK_INTERVAL_MIN)

def main():
    try:
        scheduler.start()
        logging.info("Scheduler started.")
        # Keep the script running
        import time
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logging.info("Scheduler stopped.")


if __name__ == "__main__":
    main()