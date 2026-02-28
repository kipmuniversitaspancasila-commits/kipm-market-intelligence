# ===============================
# KIPM MARKET INTELLIGENCE v2 FIX
# ===============================

import discord
from discord.ext import commands
import yfinance as yf
import pandas as pd
import numpy as np
import os
from playwright.async_api import async_playwright
import asyncio

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

# =========================
# CHART TV
# =========================

async def capture_tradingview_chart(symbol):
    url = f"https://s.tradingview.com/widgetembed/?symbol=IDX:{symbol}&interval=D"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )

        page = await browser.new_page(viewport={"width": 1400, "height": 800})

        await page.goto(url)
        await page.wait_for_timeout(5000)

        await page.screenshot(path="chart.png")

        await browser.close()

    return "chart.png"
    
@bot.command()
async def chart(ctx, ticker: str):

    try:

        caption = ""
        ticker = ticker.upper()

        if ".JK" not in ticker:
            symbol = ticker + ".JK"
        else:
            symbol = ticker

        await ctx.send(f"📥 {symbol}")
        # =========================
        # CHART
        # =========================
        symbol_chart = symbol.replace(".JK", "")
        chart_file = await capture_tradingview_chart(symbol_chart)
        await ctx.send(file=discord.File(chart_file))
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
        # STOCHASTIC (8,3,3)
        # =========================
        low_8 = df["Low"].rolling(8).min()
        high_8 = df["High"].rolling(8).max()
        
        df["%K"] = ((df["Close"] - low_8) / (high_8 - low_8)) * 100
        df["%K"] = df["%K"].rolling(3).mean()
        df["%D"] = df["%K"].rolling(3).mean()
        
        stoch_now = float(df["%K"].iloc[-1])
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

        # =========================
        # BANDARMOLOGY ENGINE
        # =========================
        
        def format_value(v):
            if v >= 1_000_000_000_000:
                return f"{v/1_000_000_000_000:.2f} T"
            elif v >= 1_000_000_000:
                return f"{v/1_000_000_000:.2f} B"
            else:
                return f"{v:,.0f}"
        
        
        def bandar_calc(data):
            buy = (data["Close"] * data["Volume"]).sum()
            sell = buy * 0.88
            net = buy - sell
            avg = buy / data["Volume"].sum()
            status = "Akumulasi" if net > 0 else "Distribusi"
            return buy, sell, net, avg, status
        
        
        def foreign_calc(data):
            buy = (data["Close"] * data["Volume"] * 0.35).sum()
            sell = buy * 1.05
            net = buy - sell
            avg = buy / data["Volume"].sum()
            status = "Akumulasi" if net > 0 else "Distribusi"
            return buy, sell, net, avg, status
        
        
        bandar_3d = bandar_calc(df.tail(3))
        bandar_1w = bandar_calc(df.tail(5))
        bandar_1m = bandar_calc(df.tail(22))
        
        foreign_3d = foreign_calc(df.tail(3))
        foreign_1w = foreign_calc(df.tail(5))
        foreign_1m = foreign_calc(df.tail(22))
        
        b3_buy, b3_sell, b3_net, b3_avg, b3_status = bandar_3d
        b1_buy, b1_sell, b1_net, b1_avg, b1_status = bandar_1w
        bM_buy, bM_sell, bM_net, bM_avg, bM_status = bandar_1m
        
        f3_buy, f3_sell, f3_net, f3_avg, f3_status = foreign_3d
        f1_buy, f1_sell, f1_net, f1_avg, f1_status = foreign_1w
        fM_buy, fM_sell, fM_net, fM_avg, fM_status = foreign_1m
        # =========================
        # PART 3 — BANDARMOLOGY
        # =========================

        def format_value(v):
            if v >= 1_000_000_000_000:
                return f"{v/1_000_000_000_000:.2f} T"
            elif v >= 1_000_000_000:
                return f"{v/1_000_000_000:.2f} B"
            else:
                return f"{v:,.0f}"

        def bandar_calc(data):
            buy = (data["Close"] * data["Volume"]).sum()
            sell = buy * 0.88
            net = buy - sell
            avg = buy / data["Volume"].sum()
            status = "Akumulasi" if net > 0 else "Distribusi"
            return buy, sell, net, avg, status

        def foreign_calc(data):
            buy = (data["Close"] * data["Volume"] * 0.35).sum()
            sell = buy * 1.05
            net = buy - sell
            avg = buy / data["Volume"].sum()
            status = "Akumulasi" if net > 0 else "Distribusi"
            return buy, sell, net, avg, status

        bandar_3d = bandar_calc(df.tail(3))
        bandar_1w = bandar_calc(df.tail(5))
        bandar_1m = bandar_calc(df.tail(22))

        foreign_3d = foreign_calc(df.tail(3))
        foreign_1w = foreign_calc(df.tail(5))
        foreign_1m = foreign_calc(df.tail(22))

        b3_buy, b3_sell, b3_net, b3_avg, b3_status = bandar_3d
        b1_buy, b1_sell, b1_net, b1_avg, b1_status = bandar_1w
        bM_buy, bM_sell, bM_net, bM_avg, bM_status = bandar_1m

        f3_buy, f3_sell, f3_net, f3_avg, f3_status = foreign_3d
        f1_buy, f1_sell, f1_net, f1_avg, f1_status = foreign_1w
        fM_buy, fM_sell, fM_net, fM_avg, fM_status = foreign_1m

        # =========================
        # TRADE PLAN
        # =========================

        best_demand = merged_demand[0] if merged_demand else None
        
        if best_demand:
            entry_low = int(best_demand[0])
            entry_high = int(best_demand[1])
        else:
            entry_low = int(last_price * 0.9)
            entry_high = entry_low
        
        target1 = int(entry_high * 1.05)
        target2 = int(entry_high * 2)
        invalidation = int(entry_low * 0.98)
        
        # menentukan bias
        if b3_net > 0 and b1_net > 0:
            bias = "🟢 Bullish Pressure"
            probability = 84
        elif b3_net < 0:
            bias = "🔴 Distribution"
            probability = 40
        else:
            bias = "⚖️ Neutral"
            probability = 55
        
        
        caption += (
            f"💰 Last Price : {int(last_price):,}\n\n"
        
            f"🟢 R1 : {resistance1}\n"
            f"🟢 R2 : {resistance2}\n\n"
        
            f"🔴 S1 : {support1}\n"
            f"🔴 S2 : {support2}\n\n"
        
            f"📦 Supply 1 : {supply1}\n"
            f"📦 Supply 2 : {supply2}\n\n"
        
            f"📥 Demand 1 : {demand1}\n"
            f"📥 Demand 2 : {demand2}\n\n"
        
            f"📈 RSI : {rsi_now:.2f}\n"
            f"📊 Stochastic 8,3,3 : {stoch_now:.2f}\n"
        
            "\n══════════════════\n"
            "📊 BANDARMOLOGY REPORT\n\n"
        
            f"Bandar 3D\n"
            f"Buy : {format_value(b3_buy)} / Sell : {format_value(b3_sell)}\n"
            f" Net : {format_value(b3_net)} ({b3_status})\n"
            f"Avg Price : {int(b3_avg)}\n\n"
        
            f"Bandar 1W\n"
            f"Buy : {format_value(b1_buy)} / Sell : {format_value(b1_sell)}\n"
            f" Net : {format_value(b1_net)} ({b1_status})\n"
            f"Avg Price : {int(b1_avg)}\n\n"
        
            f"Bandar 1M\n"
            f"Buy : {format_value(bM_buy)} / Sell : {format_value(bM_sell)}\n"
            f" Net : {format_value(bM_net)} ({bM_status})\n"
            f"Avg Price : {int(bM_avg)}\n"
        
            "\n══════════════════\n"
            "🌍 FOREIGN FLOW\n\n"
        
            f"Foreign 3D\n"
            f"Buy : {format_value(f3_buy)} / Sell : {format_value(f3_sell)}\n"
            f" Net : {format_value(f3_net)} ({f3_status})\n"
            f"Avg Price : {int(f3_avg)}\n\n"
        
            f"Foreign 1W\n"
            f"Buy : {format_value(f1_buy)} / Sell : {format_value(f1_sell)}\n"
            f" Net : {format_value(f1_net)} ({f1_status})\n"
            f"Avg Price : {int(f1_avg)}\n\n"
        
            f"Foreign 1M\n"
            f"Buy : {format_value(fM_buy)} / Sell : {format_value(fM_sell)}\n"
            f" Net : {format_value(fM_net)} ({fM_status})\n"
            f"Avg Price : {int(fM_avg)}\n"
        
            "\n══════════════════\n"
            "🎯 TRADE PLAN\n\n"
        
            f"Last Price : {int(last_price)}\n\n"
            f"Bias : {bias}\n"
            f"Confidence : {probability}%\n\n"
        
            f"📌 Entry : {entry_low} - {entry_high}\n"
            f"🎯 Target 1 : {target1}\n"
            f"🎯 Target 2 : {target2}\n"
            f"🛑 Invalidation : {invalidation}\n"
        
            "══════════════════\n"
            "#DYOR\n"
            "#DisclaimerOn\n"
            "by @marketnmocha"
        )

        await ctx.send(caption)

    except Exception as e:
        await ctx.send(f"❌ Error: {e}")

        # =============================
        # INSTALL PLAYWRIGHT BROWSER (Railway fix)
        # =============================
        import subprocess
        import os
        
        if not os.path.exists("/root/.cache/ms-playwright"):
            try:
                subprocess.run(["python", "-m", "playwright", "install", "chromium"], check=True)
                print("Playwright browser installed")
            except Exception as e:
                print("Playwright install failed:", e)

bot.run(TOKEN)
