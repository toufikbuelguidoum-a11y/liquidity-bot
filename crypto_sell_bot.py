import time
import logging
from datetime import datetime, timedelta

import ccxt
import pandas as pd
import requests
from apscheduler.schedulers.background import BackgroundScheduler

# =========================================================
# TELEGRAM CONFIG
# =========================================================

TELEGRAM_TOKEN = "8716377272:AAGJAaCKwgS8z9yRAXB7_m6glYHr99VCPtA"
CHAT_ID = "8771579075"

# =========================================================
# BOT SETTINGS
# =========================================================

CHECK_INTERVAL_MIN = 5
COOLDOWN_MINUTES = 60

ENABLE_BTC = True
ENABLE_PAXG = True

BTC_RSI_THRESHOLD = 70
BTC_STOCH_THRESHOLD = 85

PAXG_RSI_THRESHOLD = 75
PAXG_STOCH_THRESHOLD = 90

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# =========================================================
# EXCHANGE
# =========================================================

exchange = ccxt.binance({
    "enableRateLimit": True,
    "options": {
        "defaultType": "spot"
    }
})

# =========================================================
# GLOBAL STATE
# =========================================================

scheduler = BackgroundScheduler()

last_signal_times = {
    "BTC": None,
    "PAXG": None
}

# =========================================================
# TELEGRAM MESSAGE
# =========================================================

def send_message(text):

    try:

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

        payload = {
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML"
        }

        response = requests.post(
            url,
            json=payload,
            timeout=10
        )

        if response.status_code == 200:
            logging.info("Telegram message sent.")
        else:
            logging.error(
                f"Telegram error: {response.text}"
            )

    except Exception as e:
        logging.error(
            f"Failed to send Telegram message: {e}"
        )

# =========================================================
# RSI
# =========================================================

def rsi(series, period=14):

    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))

# =========================================================
# STOCH RSI
# =========================================================

def stoch_rsi(
    close,
    rsi_period=14,
    stoch_period=14,
    k_period=3,
    d_period=3
):

    rsi_values = rsi(close, rsi_period)

    lowest_rsi = rsi_values.rolling(
        stoch_period
    ).min()

    highest_rsi = rsi_values.rolling(
        stoch_period
    ).max()

    denominator = (
        highest_rsi - lowest_rsi
    ).replace(0, 1e-9)

    stoch = (
        100 *
        (rsi_values - lowest_rsi) /
        denominator
    )

    k_line = stoch.rolling(k_period).mean()
    d_line = k_line.rolling(d_period).mean()

    return k_line, d_line

# =========================================================
# EMA
# =========================================================

def ema(series, period):

    return series.ewm(
        span=period,
        adjust=False
    ).mean()

# =========================================================
# FETCH OHLCV
# =========================================================

def fetch_ohlcv(
    symbol,
    timeframe,
    limit=300
):

    try:

        data = exchange.fetch_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            limit=limit
        )

        df = pd.DataFrame(
            data,
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume"
            ]
        )

        df["timestamp"] = pd.to_datetime(
            df["timestamp"],
            unit="ms"
        )

        df.set_index(
            "timestamp",
            inplace=True
        )

        return df

    except Exception as e:

        logging.error(
            f"{symbol} {timeframe} fetch failed: {e}"
        )

        return None

# =========================================================
# ORDER BOOK ANALYSIS
# =========================================================

def analyze_order_book(symbol):

    try:

        ob = exchange.fetch_order_book(
            symbol,
            limit=100
        )

        bids = pd.DataFrame(
            ob["bids"],
            columns=["price", "amount"]
        )

        asks = pd.DataFrame(
            ob["asks"],
            columns=["price", "amount"]
        )

        best_bid = bids.iloc[0]["price"]
        best_ask = asks.iloc[0]["price"]

        current_price = (
            best_bid + best_ask
        ) / 2

        bid_volume = bids["amount"].sum()
        ask_volume = asks["amount"].sum()

        imbalance = round(
            bid_volume / max(ask_volume, 1e-9),
            2
        )

        asks["cum"] = asks[
            "amount"
        ].cumsum()

        resistance = None

        large_wall = asks[
            asks["cum"] >= 50
        ]

        if not large_wall.empty:

            resistance = float(
                large_wall.iloc[0]["price"]
            )

        return {
            "price": round(current_price, 2),
            "resistance": resistance,
            "imbalance": imbalance
        }

    except Exception as e:

        logging.error(
            f"Order book error {symbol}: {e}"
        )

        return None

# =========================================================
# COOLDOWN CHECK
# =========================================================

def cooldown_active(asset):

    last_time = last_signal_times.get(asset)

    if last_time is None:
        return False

    return (
        datetime.now() - last_time
        < timedelta(
            minutes=COOLDOWN_MINUTES
        )
    )

# =========================================================
# SIGNAL CHECK
# =========================================================

def check_asset_signal(
    asset_name,
    symbol,
    rsi_threshold,
    stoch_threshold,
    emoji
):

    global last_signal_times

    if cooldown_active(asset_name):

        logging.info(
            f"{asset_name} cooldown active."
        )

        return

    logging.info(
        f"Checking {symbol}"
    )

    df_1h = fetch_ohlcv(
        symbol,
        "1h"
    )

    df_4h = fetch_ohlcv(
        symbol,
        "4h"
    )

    if df_1h is None or df_4h is None:
        return

    # =====================================================
    # INDICATORS
    # =====================================================

    rsi_1h = rsi(
        df_1h["close"]
    ).iloc[-1]

    rsi_4h = rsi(
        df_4h["close"]
    ).iloc[-1]

    stoch_1h, _ = stoch_rsi(
        df_1h["close"]
    )

    stoch_4h, _ = stoch_rsi(
        df_4h["close"]
    )

    stoch_1h_val = stoch_1h.iloc[-1]
    stoch_4h_val = stoch_4h.iloc[-1]

    ema200_1h = ema(
        df_1h["close"],
        200
    ).iloc[-1]

    current_price = df_1h[
        "close"
    ].iloc[-1]

    avg_volume = df_1h[
        "volume"
    ].rolling(20).mean().iloc[-1]

    current_volume = df_1h[
        "volume"
    ].iloc[-1]

    # =====================================================
    # FILTERS
    # =====================================================

    trend_bullish = (
        current_price > ema200_1h
    )

    high_volume = (
        current_volume > avg_volume
    )

    conditions_met = (

        rsi_1h > rsi_threshold and
        rsi_4h > rsi_threshold and

        stoch_1h_val > stoch_threshold and
        stoch_4h_val > stoch_threshold and

        trend_bullish and
        high_volume
    )

    if not conditions_met:

        logging.info(
            f"No signal for {asset_name}"
        )

        return

    # =====================================================
    # ORDER BOOK
    # =====================================================

    ob = analyze_order_book(symbol)

    if ob is None:
        return

    # =====================================================
    # SIGNAL STRENGTH
    # =====================================================

    strength = 0

    if rsi_1h > rsi_threshold:
        strength += 1

    if rsi_4h > rsi_threshold:
        strength += 1

    if stoch_1h_val > stoch_threshold:
        strength += 1

    if stoch_4h_val > stoch_threshold:
        strength += 1

    if high_volume:
        strength += 1

    if strength >= 5:
        signal_strength = "EXTREME"
    elif strength >= 4:
        signal_strength = "STRONG"
    else:
        signal_strength = "MODERATE"

    # =====================================================
    # MESSAGE
    # =====================================================

    timestamp = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    msg = (
        f"{emoji} <b>{asset_name} SELL SIGNAL</b>\n\n"
        f"💰 Price: ${ob['price']:,.2f}\n"
        f"📉 RSI 1H: {rsi_1h:.2f}\n"
        f"📉 RSI 4H: {rsi_4h:.2f}\n"
        f"⚡ Stoch RSI 1H: {stoch_1h_val:.2f}\n"
        f"⚡ Stoch RSI 4H: {stoch_4h_val:.2f}\n"
        f"📊 Order Book Imbalance: {ob['imbalance']}\n"
        f"🔥 Strength: {signal_strength}\n"
    )

    if ob["resistance"]:

        msg += (
            f"🎯 Resistance: "
            f"${ob['resistance']:,.2f}\n"
        )

    msg += (
        f"\n⏰ {timestamp}\n"
        f"⚠️ Consider reducing exposure."
    )

    send_message(msg)

    last_signal_times[
        asset_name
    ] = datetime.now()

    logging.info(
        f"{asset_name} signal sent."
    )

# =========================================================
# RUN ENGINE
# =========================================================

def run_signal_engine():

    try:

        if ENABLE_BTC:

            check_asset_signal(
                asset_name="BTC",
                symbol="BTC/USDT",
                rsi_threshold=BTC_RSI_THRESHOLD,
                stoch_threshold=BTC_STOCH_THRESHOLD,
                emoji="🔴"
            )

        if ENABLE_PAXG:

            check_asset_signal(
                asset_name="PAXG",
                symbol="PAXG/USDT",
                rsi_threshold=PAXG_RSI_THRESHOLD,
                stoch_threshold=PAXG_STOCH_THRESHOLD,
                emoji="🟡"
            )

    except Exception as e:

        logging.error(
            f"Signal engine failure: {e}"
        )

# =========================================================
# MAIN
# =========================================================

def main():

    logging.info(
        "Starting trading signal bot..."
    )

    scheduler.add_job(
        run_signal_engine,
        trigger="interval",
        minutes=CHECK_INTERVAL_MIN,
        max_instances=1
    )

    scheduler.start()

    logging.info(
        "Scheduler started."
    )

    # First run immediately
    run_signal_engine()

    try:

        while True:
            time.sleep(60)

    except (
        KeyboardInterrupt,
        SystemExit
    ):

        logging.info(
            "Shutting down..."
        )

        scheduler.shutdown()

        logging.info(
            "Bot stopped."
        )

# =========================================================

if __name__ == "__main__":
    main()