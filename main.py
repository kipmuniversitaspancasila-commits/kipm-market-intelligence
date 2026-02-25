import discord
from discord.ext import commands
import yfinance as yf
import pandas as pd
import mplfinance as mpf
import numpy as np
import os

TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)

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
# BANDAR FLOW
# =============================
def calculate_money_flow_detail(df):
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3
    money_flow = typical_price * df['Volume']

    positive_flow = []
    negative_flow = []

    for i in range(1, len(df)):
        if typical_price.iloc[i] > typical_price.iloc[i - 1]:
            positive_flow.append(money_flow.iloc[i])
            negative_flow.append(0)
        else:
            positive_flow.append(0)
            negative_flow.append(money_flow.iloc[i])

    positive_mf = pd.Series(positive_flow).sum()
    negative_mf = pd.Series(negative_flow).sum()

    net_flow = positive_mf - negative_mf
    total_flow = positive_mf + negative_mf

    strength = 0
    if total_flow != 0:
        strength = abs(net_flow) / total_flow * 100

    return net_flow, strength


def flow_interpretation(net_flow, strength):
    if net_flow > 0:
        direction = "Accumulation 🟢"
    elif net_flow < 0:
        direction = "Distribution 🔴"
    else:
        direction = "Neutral"

    if strength > 70:
        level = "Strong"
    elif strength > 40:
        level = "Moderate"
    else:
        level = "Weak"

    return direction, level


# =============================
# FREQUENCY ANALYZER (PRICE DISTRIBUTION)
# =============================
def calculate_frequency_series(df, bins=25):

    df = df.copy()

    # Typical price
    df["Typical"] = (df["High"] + df["Low"] + df["Close"]) / 3

    prices = df["Typical"].values
    volumes = df["Volume"].values

    # Histogram berbobot volume
    hist, bin_edges = np.histogram(prices, bins=bins, weights=volumes)

    # Buat series kosong sepanjang df
    freq_series = pd.Series(0.0, index=df.index)

    # Masukkan volume weight ke index terdekat
    for i in range(len(hist)):
        if hist[i] > 0:
            mid_price = (bin_edges[i] + bin_edges[i + 1]) / 2
            idx = (df["Close"] - mid_price).abs().idxmin()
            freq_series.loc[idx] = hist[i]

    return freq_series


@bot.command()
async def chart(ctx, ticker: str):

    try:
        import yfinance as yf
        import mplfinance as mpf
        import pandas as pd
        import numpy as np
        import discord

        ticker = ticker.upper()
        if ".JK" not in ticker:
            ticker += ".JK"

        await ctx.send(f"📥{ticker}")

        df_full = yf.download(ticker, period="max", interval="1d")

        if isinstance(df_full.columns, pd.MultiIndex):
            df_full.columns = df_full.columns.get_level_values(0)

        df_full.dropna(inplace=True)

        # === DATA UNTUK CHART (2 TAHUN) ===
        df = df_full.tail(500).copy()

        last_price = df["Close"].iloc[-1]
        last_price_text = f"{float(last_price):,.0f}"

        # =========================
        # FREQUENCY SERIES
        # =========================

        def filter_relevant_levels(levels,
                                   current_price,
                                   max_distance_percent=60):
            filtered = []
            for lvl in levels:
                dist = abs(lvl - current_price) / current_price * 100
                if dist <= max_distance_percent:
                    filtered.append(lvl)
            return filtered

    # =========================
    # SWING HIGH & LOW
    # =========================

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
        # =========================
        # RSI
        # =========================
        delta = df["Close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss
        df["RSI"] = 100 - (100 / (1 + rs))
        rsi_now = float(df["RSI"].iloc[-1])

        # =========================
        # STOCHASTIC 8,3,3
        # =========================
        low_min = df["Low"].rolling(8).min()
        high_max = df["High"].rolling(8).max()
        stoch_k = 100 * ((df["Close"] - low_min) / (high_max - low_min))
        stoch_d = stoch_k.rolling(3).mean()
        stoch_now = float(stoch_k.iloc[-1])

        # =========================
        # SUPPORT RESIST REALISTIC SWING FILTERED
        # =========================

        current_price = float(df["Close"].iloc[-1])

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

        # =========================
        # FILTER NOISE (hapus level terlalu dekat)
        # =========================

        def filter_levels(levels, min_gap_percent=3):
            filtered = []
            for level in sorted(levels):
                if not filtered:
                    filtered.append(level)
                else:
                    if abs(level - filtered[-1]
                           ) / filtered[-1] * 100 > min_gap_percent:
                        filtered.append(level)
            return filtered

        swing_highs = filter_levels(swing_highs)
        swing_lows = filter_levels(swing_lows)

        # =========================
        # PILIH SUPPORT & RESIST
        # =========================

        supports = sorted([l for l in swing_lows if l < current_price],
                          reverse=True)
        resistances = sorted([h for h in swing_highs if h > current_price])

        # Pastikan tidak terlalu dekat dengan harga (<2%)
        supports = [
            s for s in supports
            if (current_price - s) / current_price * 100 > 2
        ]
        resistances = [
            r for r in resistances
            if (r - current_price) / current_price * 100 > 2
        ]

        support1 = supports[0] if len(supports) > 0 else None
        support2 = supports[1] if len(supports) > 1 else None

        resistance1 = resistances[0] if len(resistances) > 0 else None
        resistance2 = resistances[1] if len(resistances) > 1 else None

        # =========================
        # PEMBULATAN TANPA DESIMAL
        # =========================

        def clean_round(x):
            if x is None:
                return "N/A"
            return int(round(x / 10) * 10)

        support1 = clean_round(support1)
        support2 = clean_round(support2)
        resistance1 = clean_round(resistance1)
        resistance2 = clean_round(resistance2)

        # =========================
        # FUNDAMENTAL
        # =========================

        stock = yf.Ticker(ticker)
        info = stock.info

        pbv = info.get("priceToBook", None)
        equity = info.get("bookValue", None)

        if pbv is not None and not pd.isna(pbv):
            pbv_text = f"{float(pbv):.2f}"
        else:
            pbv_text = "N/A"

        if equity is not None and not pd.isna(equity):
            equity_text = f"{float(equity):.2f}"
        else:
            equity_text = "N/A"

        # =========================
        # BANDARMOLOGY (SIMPLE FLOW)
        # =========================
        def flow_check(days):
            data = df.tail(days)

            if len(data) < 2:
                return "Neutral"

            first = float(data["Close"].iloc[0])
            last = float(data["Close"].iloc[-1])

            if last > first:
                return "Akumulasi"
            else:
                return "Distribusi"

        flow3 = flow_check(3)
        flow7 = flow_check(7)
        flow30 = flow_check(22)

        # =========================
        # STYLE (NO GRID FIXED)
        # =========================
        mc = mpf.make_marketcolors(up="#3a7bd5",
                                   down="white",
                                   edge="inherit",
                                   wick="inherit",
                                   volume="inherit")

        style = mpf.make_mpf_style(base_mpf_style="default",
                                   marketcolors=mc,
                                   facecolor="#0f1116",
                                   figcolor="#0f1116",
                                   gridstyle="",
                                   y_on_right=True,
                                   rc={
                                       "xtick.color": "white",
                                       "ytick.color": "white",
                                       "axes.labelcolor": "white",
                                       "axes.edgecolor": "white",
                                       "text.color": "white"
                                   })

        # =========================
        # RSI PANEL
        # =========================
        apds = [
            mpf.make_addplot(freq_series, panel=2, type='line', width=1.5),
            mpf.make_addplot(df["RSI"], panel=3, width=1)
        ]

        file_path = f"{ticker}_chart.png"
        # =========================
        # FREQUENCY PANEL DATA
        # =========================

        # selalu inisialisasi dulu
        freq_series = pd.Series(0, index=df.index)

        fig, axes = mpf.plot(df,
                             type="candle",
                             style=style,
                             volume=True,
                             addplot=apds,
                             panel_ratios=(3, 1, 1, 1),
                             figsize=(14, 8),
                             returnfig=True)

        max_idx = freq_series.idxmax()
        max_price = df.loc[max_idx, "Close"]

        fig.text(0.89,
                 0.87,
                 "@marketnmocha",
                 ha='right',
                 va='top',
                 fontsize=12,
                 alpha=0.6)
        # Hapus grid manual
        for ax in axes:
            ax.grid(False)
            ax.yaxis.tick_right()
            ax.yaxis.set_label_position("right")

        fig.savefig(file_path)

        freq_text = ""
        rank = 1

        # =========================
        # CAPTION
        # =========================
        caption = (f"💰 Last Price : {last_price_text}\n\n"
                   f"🟢 Support 1 (Weekly) : {support1}\n"
                   f"🟢 Support 2 (Monthly): {support2}\n\n"
                   f"🔴 Resistance 1 (Weekly) : {resistance1}\n"
                   f"🔴 Resistance 2 (Monthly): {resistance2}\n\n"
                   f"📈 RSI : {rsi_now:.2f}\n"
                   f"📊 Stochastic 8,3,3 : {stoch_now:.2f}\n\n"
                   f"📚 PBV : {pbv_text}\n"
                   f"🏛️ Equity / Share : {equity_text}\n\n"
                   f"🏦 Bandarmology\n"
                   f"• 3 Hari  : {flow3}\n"
                   f"• 1 Minggu: {flow7}\n"
                   f"• 1 Bulan : {flow30}\n\n"
                   "#DYOR\n"
                   "#DisclaimerOn\n"
                   "by @marketnmocha")

        file = discord.File(file_path)
        await ctx.send(file=file, content=caption)

    except Exception as e:
        await ctx.send(f"❌ Error: {e}")


bot.run(TOKEN)
