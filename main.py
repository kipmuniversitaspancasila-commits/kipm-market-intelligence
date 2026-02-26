import discord
from discord.ext import commands
import yfinance as yf
import pandas as pd
import mplfinance as mpf
import numpy as np
import os

# =========================================================
# CONFIGURATION
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Bot aktif sebagai {bot.user}")


# =========================================================
# ===================== INDICATORS ========================
# =========================================================

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


# =========================================================
# ================= SUPPORT RESISTANCE ====================
# =========================================================

def calculate_sr_zones(df, current_price, window=7, tolerance=0.015):

    swing_highs = []
    swing_lows = []

    # 1️⃣ Detect Swing
    for i in range(window, len(df) - window):
        high_slice = df["High"].iloc[i - window:i + window]
        low_slice = df["Low"].iloc[i - window:i + window]

        if df["High"].iloc[i] == high_slice.max():
            swing_highs.append(float(df["High"].iloc[i]))

        if df["Low"].iloc[i] == low_slice.min():
            swing_lows.append(float(df["Low"].iloc[i]))

    # 2️⃣ Clustering
    def cluster_levels(levels):
        clusters = []
        levels = sorted(levels)

        for level in levels:
            placed = False
            for cluster in clusters:
                if abs(level - np.mean(cluster)) / np.mean(cluster) <= tolerance:
                    cluster.append(level)
                    placed = True
                    break
            if not placed:
                clusters.append([level])
        return clusters

    high_clusters = cluster_levels(swing_highs)
    low_clusters = cluster_levels(swing_lows)

    resistance_zones = []
    support_zones = []

    for cluster in high_clusters:
        if len(cluster) >= 2:
            resistance_zones.append(
                (min(cluster), max(cluster), len(cluster))
            )

    for cluster in low_clusters:
        if len(cluster) >= 2:
            support_zones.append(
                (min(cluster), max(cluster), len(cluster))
            )

    resistance_zones = sorted(
        [z for z in resistance_zones if z[0] > current_price],
        key=lambda x: x[0]
    )

    support_zones = sorted(
        [z for z in support_zones if z[1] < current_price],
        key=lambda x: x[1],
        reverse=True
    )

    return resistance_zones[:2], support_zones[:2]


# =========================================================
# ================= SUPPLY DEMAND ENGINE ==================
# =========================================================

def calculate_supply_demand(df, current_price, impulse_threshold=0.03):

    supply_zones = []
    demand_zones = []

    for i in range(2, len(df)-3):

        base_candle = df.iloc[i]
        future = df.iloc[i+1:i+4]

        up_move = (future["High"].max() - base_candle["Close"]) / base_candle["Close"]
        down_move = (base_candle["Close"] - future["Low"].min()) / base_candle["Close"]

        if up_move >= impulse_threshold:
            demand_zones.append(
                (base_candle["Low"], base_candle["Open"])
            )

        if down_move >= impulse_threshold:
            supply_zones.append(
                (base_candle["Open"], base_candle["High"])
            )

    supply_zones = sorted(
        [z for z in supply_zones if z[0] > current_price],
        key=lambda x: x[0]
    )

    demand_zones = sorted(
        [z for z in demand_zones if z[1] < current_price],
        key=lambda x: x[1],
        reverse=True
    )

    return supply_zones[:2], demand_zones[:2]


# =========================================================
# ================= BANDARMOLOGY ENGINE ===================
# =========================================================

def bandar_engine(data):

    buy = (data["Close"] * data["Volume"]).sum()
    sell = buy * 0.88
    net = buy - sell
    avg = buy / data["Volume"].sum()

    status = "Akumulasi" if net > 0 else "Distribusi"

    return buy, sell, net, avg, status


def foreign_engine(data):

    foreign_buy = (data["Volume"] * data["Close"] * 0.35).sum()
    foreign_sell = foreign_buy * 1.05
    net = foreign_buy - foreign_sell
    avg = foreign_buy / data["Volume"].sum()

    status = "Akumulasi" if net > 0 else "Distribusi"

    return foreign_buy, foreign_sell, net, avg, status


# =========================================================
# ====================== COMMAND ==========================
# =========================================================

@bot.command()
async def chart(ctx, ticker: str):

    try:

        ticker = ticker.upper()
        if ".JK" not in ticker:
            ticker += ".JK"

        await ctx.send(f"📥 {ticker}")

        df_full = yf.download(ticker, period="max", interval="1d")

        if isinstance(df_full.columns, pd.MultiIndex):
            df_full.columns = df_full.columns.get_level_values(0)

        df_full.dropna(inplace=True)
        df = df_full.tail(500).copy()

        last_price = df["Close"].iloc[-1]
        current_price = float(last_price)

        # =============================
        # FREQUENCY
        # =============================
        bins = 20 if last_price < 2000 else 25 if last_price < 5000 else 30
        freq_series = calculate_frequency_series(df, bins=bins)

        # =============================
        # RSI & STOCHASTIC
        # =============================
        df["RSI"] = calculate_rsi(df["Close"])
        k, d = calculate_stochastic(df)

        # =============================
        # SUPPORT RESISTANCE
        # =============================
        res_zones, sup_zones = calculate_sr_zones(df, current_price)

        # =============================
        # SUPPLY DEMAND
        # =============================
        supply_zones, demand_zones = calculate_supply_demand(df, current_price)

        # =============================
        # BANDAR DATA
        # =============================
        bandar_3d = bandar_engine(df.tail(3))
        bandar_1w = bandar_engine(df.tail(5))
        bandar_1m = bandar_engine(df.tail(22))

        foreign_3d = foreign_engine(df.tail(3))
        foreign_1w = foreign_engine(df.tail(5))
        foreign_1m = foreign_engine(df.tail(22))

        # =============================
        # PLOT STYLE
        # =============================
        mc = mpf.make_marketcolors(
            up="#3a7bd5",
            down="white",
            edge="inherit",
            wick="inherit",
            volume="inherit"
        )

        style = mpf.make_mpf_style(
            base_mpf_style="default",
            marketcolors=mc,
            facecolor="#0f1116",
            figcolor="#0f1116",
            gridstyle="",
            y_on_right=True
        )

        apds = [
            mpf.make_addplot(freq_series, panel=2, type='line'),
            mpf.make_addplot(df["RSI"], panel=3)
        ]

        file_path = f"{ticker}_chart.png"

        fig, axes = mpf.plot(
            df,
            type="candle",
            style=style,
            volume=True,
            addplot=apds,
            panel_ratios=(3,1,1,1),
            figsize=(14,8),
            returnfig=True
        )

        fig.savefig(file_path)
        await ctx.send(file=discord.File(file_path))

    except Exception as e:
        await ctx.send(f"Terjadi error: {e}")


# =========================================================
# RUN BOT
# =========================================================

bot.run(TOKEN)
