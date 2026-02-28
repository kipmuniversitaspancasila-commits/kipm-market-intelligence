# ===============================
# KIPM MARKET INTELLIGENCE v2 FIX
# ===============================

import discord
from discord.ext import commands
import yfinance as yf
import pandas as pd
import numpy as np
import os

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"KIPM Market Intelligence aktif sebagai {bot.user}")

# ===============================
# RSI
# ===============================
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# ===============================
# STOCHASTIC
# ===============================
def calculate_stochastic(df, k_period=8, d_period=3, smooth=3):
    low_min = df["Low"].rolling(window=k_period).min()
    high_max = df["High"].rolling(window=k_period).max()
    k = 100 * ((df["Close"] - low_min) / (high_max - low_min))
    k_smooth = k.rolling(window=smooth).mean()
    d = k_smooth.rolling(window=d_period).mean()
    return k_smooth, d

    
# ===============================
# MERGE ZONES (INI YANG HILANG)
# ===============================
def merge_zones(zones, tolerance=0.02):
    if not zones:
        return []

    zones = sorted(zones, key=lambda x: x[0])
    merged = [zones[0]]

    for current in zones[1:]:
        prev_low, prev_high = merged[-1]
        cur_low, cur_high = current

        if abs(cur_low - prev_high) / prev_high <= tolerance:
            merged[-1] = (
                min(prev_low, cur_low),
                max(prev_high, cur_high)
            )
        else:
            merged.append(current)

    return merged


# ===============================
# LIQUIDITY SWEEP
# ===============================
def detect_liquidity_sweep(df):
    if len(df) < 3:
        return False

    last = df.iloc[-1]
    prev = df.iloc[-2]

    if last["Low"] < prev["Low"] and last["Close"] > prev["Low"]:
        return True

    if last["High"] > prev["High"] and last["Close"] < prev["High"]:
        return True

    return False


# ===============================
# VOLUME SPIKE (SEBELUMNYA ERROR)
# ===============================
def detect_volume_spike(df):
    avg = df["Volume"].rolling(20).mean().iloc[-1]
    now = df["Volume"].iloc[-1]

    if pd.isna(avg):
        return False

    return now > avg * 1.7


# ===============================
# IMPULSE MOVE
# ===============================
def detect_impulse(df):
    if len(df) < 4:
        return False

    move = abs(df["Close"].iloc[-1] - df["Close"].iloc[-3])
    base = df["Close"].iloc[-3]

    return (move / base) > 0.03

# ===============================
# ZONE SCORING
# ===============================
def score_zone(zone):

    score = 1

    if zone["has_sr"]:
        score += 2

    if zone["has_fvg"]:
        score += 2

    if zone["fresh"]:
        score += 1

    if zone["liquidity_sweep"]:
        score += 2

    if zone["impulsive_move"]:
        score += 2

    if zone["volume_spike"]:
        score += 1

    return score


def classify_zone(score):
    if score >= 7:
        return "🔥 Institutional Zone"
    elif score >= 5:
        return "⚡ Strong Reaction Zone"
    elif score >= 3:
        return "🟡 Tradable Zone"
    else:
        return "⚪ Weak Zone"


def estimate_probability(score):
    return min(90, score * 12)


# ===============================
# MARKET BIAS
# ===============================
def detect_bias(supply_zones, demand_zones, rsi):

    supply_score = sum(z["score"] for z in supply_zones)
    demand_score = sum(z["score"] for z in demand_zones)

    if demand_score > supply_score and rsi < 45:
        return "🟢 Smart Money Long Bias"

    if supply_score > demand_score and rsi > 55:
        return "🔴 Smart Money Short Bias"

    if demand_score > supply_score:
        return "🟢 Bullish Pressure"

    if supply_score > demand_score:
        return "🔴 Bearish Pressure"

    return "⚖️ Neutral"
    
@bot.command()
async def chart(ctx, ticker: str):

    try:

        caption = ""
        ticker = ticker.upper()

        if ".JK" not in ticker:
            symbol = ticker + ".JK"
        else:
            symbol = ticker

        await ctx.send(f"📥{symbol}")

        # =========================
        # DOWNLOAD DATA
        # =========================
        df = yf.download(symbol, period="6mo", interval="1d")

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        for col in ["Open", "High", "Low", "Close", "Volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna()

        if df.empty:
            await ctx.send("Data tidak ditemukan.")
            return

        # =========================
        # INDICATOR
        # =========================
        rsi = calculate_rsi(df["Close"])
        rsi_now = float(rsi.iloc[-1])

        k, d = calculate_stochastic(df)
        stoch_now = float(k.iloc[-1])

        close_series = df["Close"]

        if isinstance(close_series, pd.DataFrame):
            close_series = close_series.iloc[:, 0]

        last_price = float(close_series.iloc[-1])

        # =========================================
        # SUPPORT RESISTANCE ENGINE
        # =========================================
        def calculate_sr_zones(df, current_price, window=7, tolerance=0.015):

            swing_highs = []
            swing_lows = []

            for i in range(window, len(df) - window):
                high_slice = df["High"].iloc[i-window:i+window]
                low_slice = df["Low"].iloc[i-window:i+window]

                if df["High"].iloc[i] == high_slice.max():
                    swing_highs.append(float(df["High"].iloc[i]))

                if df["Low"].iloc[i] == low_slice.min():
                    swing_lows.append(float(df["Low"].iloc[i]))

            resistance = sorted([x for x in swing_highs if x > current_price])[:2]
            support = sorted([x for x in swing_lows if x < current_price], reverse=True)[:2]

            res_zones = [(x, x+30, 2) for x in resistance]
            sup_zones = [(x-30, x, 2) for x in support]

            return res_zones, sup_zones


        # =========================================
        # SUPPLY DEMAND ENGINE
        # =========================================
        def calculate_supply_demand(df, current_price):

            supply_zones = []
            demand_zones = []

            for i in range(2, len(df) - 3):

                base = df.iloc[i]
                future = df.iloc[i+1:i+4]

                up_move = (future["High"].max() - base["Close"]) / base["Close"]
                down_move = (base["Close"] - future["Low"].min()) / base["Close"]

                if up_move >= 0.03:
                    demand_zones.append((base["Low"], base["Open"]))

                if down_move >= 0.03:
                    supply_zones.append((base["Open"], base["High"]))

            supply_zones = sorted(
                [z for z in supply_zones if z[0] > current_price],
                key=lambda x: x[0]
            )

            demand_zones = sorted(
                [z for z in demand_zones if z[1] < current_price],
                key=lambda x: x[1],
                reverse=True
            )

            return supply_zones[:5], demand_zones[:5]


        # HITUNG ZONE
        res_zones, sup_zones = calculate_sr_zones(df, last_price)
        supply_zones, demand_zones = calculate_supply_demand(df, last_price)

        merged_supply = merge_zones(supply_zones)
        merged_demand = merge_zones(demand_zones)

        # =============================
        # FORMAT ZONE
        # =============================
        def format_zone(zone):
            if zone:
                return f"{int(zone[0])} - {int(zone[1])} (x{zone[2]})"
            return "N/A"

        resistance1 = format_zone(res_zones[0]) if len(res_zones) > 0 else "N/A"
        resistance2 = format_zone(res_zones[1]) if len(res_zones) > 1 else "N/A"

        support1 = format_zone(sup_zones[0]) if len(sup_zones) > 0 else "N/A"
        support2 = format_zone(sup_zones[1]) if len(sup_zones) > 1 else "N/A"

        def format_simple(zone):
            if not zone:
                return "N/A"
            return f"{int(zone[0])} - {int(zone[1])}"

        supply1 = format_simple(supply_zones[0]) if len(supply_zones) > 0 else "N/A"
        supply2 = format_simple(supply_zones[1]) if len(supply_zones) > 1 else "N/A"

        demand1 = format_simple(demand_zones[0]) if len(demand_zones) > 0 else "N/A"
        demand2 = format_simple(demand_zones[1]) if len(demand_zones) > 1 else "N/A"

        last_price_text = f"{int(last_price):,}"

        # =============================
        # CAPTION (FORMAT ASLI KAMU)
        # =============================
        caption = (
            f"💰 Last Price : {last_price_text}\n\n"

            f"🟢 R1 : {resistance1}\n"
            f"🟢 R2 : {resistance2}\n\n"

            f"🔴 S1 : {support1}\n"
            f"🔴 S2 : {support2}\n\n"

            f"📦 Supply 1 : {supply1}\n"
            f"📦 Supply 2 : {supply2}\n\n"

            f"📥 Demand 1 : {demand1}\n"
            f"📥 Demand 2 : {demand2}\n\n"

            f"📈 RSI : {rsi_now:.2f}\n"
            f"📊 Stochastic 8,3,3 : {stoch_now:.2f}\n\n"

            f"📊 {ticker}\n"
            "#DYOR\n"
            "#DisclaimerOn\n"
            "by @marketnmocha"
        )

        await ctx.send(caption)

    except Exception as e:
        import traceback
        traceback.print_exc()
        await ctx.send(f"❌ Error: {e}")

bot.run(TOKEN)
