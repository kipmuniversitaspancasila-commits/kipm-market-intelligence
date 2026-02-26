import discord
from discord.ext import commands
import yfinance as yf
import pandas as pd
import mplfinance as mpf
import numpy as np
import os

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Bot aktif sebagai {bot.user}")


# =============================
# RSI
# =============================
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# =============================
# STOCHASTIC 8,3,3
# =============================
def calculate_stochastic(df, k_period=8, d_period=3, smooth=3):
    low_min = df['Low'].rolling(window=k_period).min()
    high_max = df['High'].rolling(window=k_period).max()
    k = 100 * ((df['Close'] - low_min) / (high_max - low_min))
    k_smooth = k.rolling(window=smooth).mean()
    d = k_smooth.rolling(window=d_period).mean()
    return k_smooth, d


# =============================
# SWING LEVEL
# =============================
def find_levels(df):
    window = 5
    highs = df['High']
    lows = df['Low']
    swing_highs = []
    swing_lows = []

    for i in range(window, len(df) - window):
        if highs.iloc[i] == highs.iloc[i - window:i + window].max():
            swing_highs.append(highs.iloc[i])
        if lows.iloc[i] == lows.iloc[i - window:i + window].min():
            swing_lows.append(lows.iloc[i])

    return swing_highs, swing_lows


def round_level(value):
    if value >= 10000:
        return round(value / 100) * 100
    elif value >= 1000:
        return round(value / 50) * 50
    else:
        return round(value / 10) * 10


# =============================
# FREQUENCY ANALYZER
# =============================
def calculate_frequency_series(df, bins=25):

    df = df.copy()
    df["Typical"] = (df["High"] + df["Low"] + df["Close"]) / 3

    prices = df["Typical"].values
    volumes = df["Volume"].values

    hist, bin_edges = np.histogram(prices, bins=bins, weights=volumes)

    freq_series = pd.Series(0.0, index=df.index)

    for i in range(len(hist)):
        if hist[i] > 0:
            mid_price = (bin_edges[i] + bin_edges[i + 1]) / 2
            idx = (df["Close"] - mid_price).abs().idxmin()
            freq_series.loc[idx] = hist[i]

    return freq_series


@bot.command()
async def chart(ctx, ticker: str):

    try:
        ticker = ticker.upper()
        if ".JK" not in ticker:
            ticker += ".JK"

        await ctx.send(f"📥{ticker}")

        df_full = yf.download(ticker, period="max", interval="1d")

        if isinstance(df_full.columns, pd.MultiIndex):
            df_full.columns = df_full.columns.get_level_values(0)

        df_full.dropna(inplace=True)

        df = df_full.tail(500).copy()

        last_price = df["Close"].iloc[-1]
        last_price_text = f"{float(last_price):,.0f}"

        def filter_relevant_levels(levels, current_price, max_distance_percent=60):
            filtered = []
            for lvl in levels:
                dist = abs(lvl - current_price) / current_price * 100
                if dist <= max_distance_percent:
                    filtered.append(lvl)
            return filtered

        window = 5
        swing_highs = []
        swing_lows = []

        for i in range(window, len(df) - window):
            high_slice = df["High"].iloc[i - window:i + window]
            low_slice = df["Low"].iloc[i - window:i + window]

            if df["High"].iloc[i] == high_slice.max():
                swing_highs.append(float(df["High"].iloc[i]))

            if df["Low"].iloc[i] == low_slice.min():
                swing_lows.append(float(df["Low"].iloc[i]))

        current_price = float(df["Close"].iloc[-1])

        swing_highs = filter_relevant_levels(swing_highs, current_price)
        swing_lows = filter_relevant_levels(swing_lows, current_price)

        if current_price < 2000:
            bins = 20
        elif current_price < 5000:
            bins = 25
        else:
            bins = 30

        freq_series = calculate_frequency_series(df, bins=bins)

        # RSI
        delta = df["Close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss
        df["RSI"] = 100 - (100 / (1 + rs))
        rsi_now = float(df["RSI"].iloc[-1])

        # STOCH
        low_min = df["Low"].rolling(8).min()
        high_max = df["High"].rolling(8).max()
        stoch_k = 100 * ((df["Close"] - low_min) / (high_max - low_min))
        stoch_d = stoch_k.rolling(3).mean()
        stoch_now = float(stoch_k.iloc[-1])

        # SUPPORT RESIST
        def filter_levels(levels, min_gap_percent=3):
            filtered = []
            for level in sorted(levels):
                if not filtered:
                    filtered.append(level)
                else:
                    if abs(level - filtered[-1]) / filtered[-1] * 100 > min_gap_percent:
                        filtered.append(level)
            return filtered

        swing_highs = filter_levels(swing_highs)
        swing_lows = filter_levels(swing_lows)

        supports = sorted([l for l in swing_lows if l < current_price], reverse=True)
        resistances = sorted([h for h in swing_highs if h > current_price])

        supports = [s for s in supports if (current_price - s) / current_price * 100 > 2]
        resistances = [r for r in resistances if (r - current_price) / current_price * 100 > 2]

        support1 = supports[0] if len(supports) > 0 else None
        support2 = supports[1] if len(supports) > 1 else None

        resistance1 = resistances[0] if len(resistances) > 0 else None
        resistance2 = resistances[1] if len(resistances) > 1 else None

        def clean_round(x):
            if x is None:
                return "N/A"
            return int(round(x / 10) * 10)

        support1 = clean_round(support1)
        support2 = clean_round(support2)
        resistance1 = clean_round(resistance1)
        resistance2 = clean_round(resistance2)

        # FUNDAMENTAL
        stock = yf.Ticker(ticker)
        info = stock.info

        pbv = info.get("priceToBook", None)
        equity = info.get("bookValue", None)

        pbv_text = f"{float(pbv):.2f}" if pbv else "N/A"
        equity_text = f"{float(equity):.2f}" if equity else "N/A"

        # =============================
        # BANDARMOLOGY ENGINE (FIX)
        # =============================
        def bandarmology_period(data):

            buy_value = (data["Close"] * data["Volume"]).sum()
            sell_value = buy_value * 0.5
            net = buy_value - sell_value

            if net > 0:
                status = "Akumulasi"
            else:
                status = "Distribusi"

            avg_price = buy_value / data["Volume"].sum()

            return buy_value, sell_value, net, avg_price, status

        def format_value(v):
            if v >= 1_000_000_000_000:
                return f"{v/1_000_000_000_000:.2f} T"
            elif v >= 1_000_000_000:
                return f"{v/1_000_000_000:.2f} B"
            elif v >= 1_000_000:
                return f"{v/1_000_000:.2f} M"
            else:
                return f"{v:.0f}"

        # INI YANG TADI ERROR
        bandar3 = bandarmology_period(df.tail(3))
        bandar1m = bandarmology_period(df.tail(22))
        bandar3m = bandarmology_period(df.tail(66))

        # STYLE
        mc = mpf.make_marketcolors(up="#3a7bd5", down="white", edge="inherit", wick="inherit", volume="inherit")

        style = mpf.make_mpf_style(
            base_mpf_style="default",
            marketcolors=mc,
            facecolor="#0f1116",
            figcolor="#0f1116",
            gridstyle="",
            y_on_right=True
        )

        apds = [
            mpf.make_addplot(freq_series, panel=2, type='line', width=1.5),
            mpf.make_addplot(df["RSI"], panel=3, width=1)
        ]

        file_path = f"{ticker}_chart.png"

        fig, axes = mpf.plot(
            df,
            type="candle",
            style=style,
            volume=True,
            addplot=apds,
            panel_ratios=(3, 1, 1, 1),
            figsize=(14, 8),
            returnfig=True
        )

        for ax in axes:
            ax.grid(False)
            ax.yaxis.tick_right()

        fig.savefig(file_path)

        caption = (
            f"💰 Last Price : {last_price_text}\n\n"
            f"🟢 R1 : {resistance1}\n"
            f"🟢 R2 : {resistance2}\n\n"
            f"🔴 S1 : {support1}\n"
            f"🔴 S2 : {support2}\n\n"
            f"📈 RSI : {rsi_now:.2f}\n"
            f"📊 Stochastic 8,3,3 : {stoch_now:.2f}\n\n"
            f"📚 PBV : {pbv_text}\n"
            f"🏛️ Equity / Share : {equity_text}\n\n"
            f"🏦 Bandarmology\n"
            f"3 Hari Terakhir\n"
            f"Buy : {format_value(bandar3[0])}\n"
            f"Sell: {format_value(bandar3[1])}\n"
            f"Net : {format_value(bandar3[2])} ({bandar3[4]})\n"
            f"Avg : {bandar3[3]:.0f}\n\n"
            "#DYOR\n"
            "#DisclaimerOn\n"
            "by @marketnmocha"
        )

        file = discord.File(file_path)
        await ctx.send(file=file, content=caption)

    except Exception as e:
        await ctx.send(f"❌ Error: {e}")


bot.run(TOKEN)
