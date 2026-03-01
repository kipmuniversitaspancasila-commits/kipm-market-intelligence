# ===============================
# KIPM MARKET INTELLIGENCE v2 FIX
# ===============================

import discord
from discord.ext import commands
import yfinance as yf
import pandas as pd
import numpy as np
import os
import mplfinance as mpf
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

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
# FAIR VALUE GAP (IPO CONTEXT)
# ===============================
def detect_fvg(df):
    fvg_zones = []

    for i in range(2, len(df)):
        prev = df.iloc[i-2]
        curr = df.iloc[i]

        # Bullish FVG
        if curr["Low"] > prev["High"]:
            fvg_zones.append(
                (prev["High"], curr["Low"], "Bullish")
            )

        # Bearish FVG
        if curr["High"] < prev["Low"]:
            fvg_zones.append(
                (curr["High"], prev["Low"], "Bearish")
            )

    return fvg_zones

# ===============================
# FRAKSI HARGA BEI
# ===============================
def price_tick(price: float) -> int:
    price = int(round(price))

    if price < 200:
        tick = 1
    elif price < 500:
        tick = 2
    elif price < 2000:
        tick = 5
    elif price < 5000:
        tick = 10
    else:
        tick = 25

    return int(round(price / tick) * tick)

# ===============================
# FUNDAMENTAL SANITIZER
# ===============================
def sanitize_pbv(pbv):
    try:
        pbv = float(pbv)
        if pbv <= 0 or pbv > 100 or pbv < -25:
            return "N/A"
        return f"{pbv:.2f}"
    except:
        return "N/A"


def sanitize_equity_per_share(eq):
    try:
        eq = float(eq)
        if eq <= 0 or eq < 10:
            return "N/A"
        return f"{eq:,.2f}"
    except:
        return "N/A"

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

        await ctx.send(f"📥 {symbol}")
        
        # =========================
        # MULTI TIMEFRAME DATA
        # =========================
        
        df_weekly = yf.download(symbol, period="max", interval="1wk")
        df_daily = yf.download(symbol, period="max", interval="1d")
        df_1h = yf.download(symbol, period="6mo", interval="1h")
        
        # Normalize columns (important)
        for df in [df_weekly, df_daily, df_1h]:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
        
        df_weekly = df_weekly.dropna()
        df_daily = df_daily.dropna()
        df_1h = df_1h.dropna()

        # =========================
        # WEEKLY STRUCTURE ENGINE
        # =========================
        
        def detect_swings(df, lookback=2):
            swing_highs = []
            swing_lows = []
        
            for i in range(lookback, len(df) - lookback):
                high = df["High"].iloc[i]
                low = df["Low"].iloc[i]
        
                if high == max(df["High"].iloc[i-lookback:i+lookback+1]):
                    swing_highs.append((i, high))
        
                if low == min(df["Low"].iloc[i-lookback:i+lookback+1]):
                    swing_lows.append((i, low))
        
            return swing_highs, swing_lows
        
        
        weekly_bias = "Undefined"
        
        if not df_weekly.empty and df_weekly.shape[0] > 20:
            swing_highs_w, swing_lows_w = detect_swings(df_weekly, lookback=2)
        
            if len(swing_highs_w) >= 2 and len(swing_lows_w) >= 2:
                last_high = swing_highs_w[-1][1]
                prev_high = swing_highs_w[-2][1]
        
                last_low = swing_lows_w[-1][1]
                prev_low = swing_lows_w[-2][1]
        
                if last_high > prev_high and last_low > prev_low:
                    weekly_bias = "Bullish Macro"
        
                elif last_high < prev_high and last_low < prev_low:
                    weekly_bias = "Bearish Macro"
        
                else:
                    weekly_bias = "Macro Range"
            else:
                weekly_bias = "Insufficient Structure"
        else:
            weekly_bias = "Not Enough Weekly Data"
        

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
        # FULL DATA (IPO)
        # =========================
        df_full = yf.download(symbol, period="max", interval="1d")
        
        if isinstance(df_full.columns, pd.MultiIndex):
            df_full.columns = df_full.columns.get_level_values(0)
        
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            df_full[col] = pd.to_numeric(df_full[col], errors="coerce")
        
        df_full = df_full.dropna()

        if df_full.empty:
            await ctx.send("Data historis penuh tidak tersedia.")
            return

        # =========================
        # CONTEXT ENGINE (SWING STRUCTURE)
        # =========================
        
        def detect_swings(df, lookback=3):
            swing_highs = []
            swing_lows = []
        
            for i in range(lookback, len(df)-lookback):
                high = df["High"].iloc[i]
                low = df["Low"].iloc[i]
        
                if high == max(df["High"].iloc[i-lookback:i+lookback+1]):
                    swing_highs.append((i, high))
        
                if low == min(df["Low"].iloc[i-lookback:i+lookback+1]):
                    swing_lows.append((i, low))
        
            return swing_highs, swing_lows
        
        
        swing_highs, swing_lows = detect_swings(df_full, lookback=3)
        
        last_price = float(df_full["Close"].iloc[-1])
        
        structure_bias = "Undefined"
        
        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            last_high = swing_highs[-1][1]
            prev_high = swing_highs[-2][1]
        
            last_low = swing_lows[-1][1]
            prev_low = swing_lows[-2][1]
        
            if last_high > prev_high and last_low > prev_low:
                structure_bias = "Bullish Structure"
        
            elif last_high < prev_high and last_low < prev_low:
                structure_bias = "Bearish Structure"
        
            else:
                structure_bias = "Range / Pullback"

            ath = df_full["High"].max()
            atl = df_full["Low"].min()
            
            if last_price >= ath * 0.98:
                market_location = "Near ATH"
            elif last_price <= atl * 1.02:
                market_location = "Near ATL"
            else:
                market_location = "Inside Range"
            
            context_summary = f"{market_location} | {structure_bias}"

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
        
        last_price = price_tick(close_series.iloc[-1])

        # =========================
        # ALL TIME HIGH / LOW
        # =========================
        all_time_high = price_tick(df_full["High"].max())
        all_time_low = price_tick(df_full["Low"].min())
        
        is_ath = last_price >= all_time_high * 0.995
        is_atl = last_price <= all_time_low * 1.005

        # =========================
        # FAIR VALUE GAP (IPO)
        # =========================
        fvg_zones = detect_fvg(df_full)
        
        valid_fvg = [
            z for z in fvg_zones
            if z[0] <= last_price <= z[1]
        ]
        
        if valid_fvg and not is_ath and not is_atl:
            fvg_text = f"{price_tick(valid_fvg[0][0])} - {price_tick(valid_fvg[0][1])}"
        else:
            fvg_text = "N/A"

        # =========================
        # FUNDAMENTAL DATA
        # =========================
        try:
            stock = yf.Ticker(symbol)
            info = stock.info
        
            pbv_raw = info.get("priceToBook", None)
            equity_raw = info.get("bookValue", None)
        
        except Exception:
            pbv_raw = None
            equity_raw = None
        
        pbv_text = sanitize_pbv(pbv_raw)
        book_value_text = sanitize_equity_per_share(equity_raw)
        
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
        res_zones, sup_zones = calculate_sr_zones(df_full, last_price)
        supply_zones, demand_zones = calculate_supply_demand(df_full, last_price)
        
        merged_supply = merge_zones(supply_zones)
        merged_demand = merge_zones(demand_zones)

        # =============================
        # FORMAT ZONE
        # =============================
        def format_zone(zone):
            if zone:
                return f"{price_tick(zone[0])} - {price_tick(zone[1])} (x{zone[2]})"
            return "N/A"
        
        resistance1 = format_zone(res_zones[0]) if len(res_zones) > 0 else "N/A"
        resistance2 = format_zone(res_zones[1]) if len(res_zones) > 1 else "N/A"
        
        support1 = format_zone(sup_zones[0]) if len(sup_zones) > 0 else "N/A"
        support2 = format_zone(sup_zones[1]) if len(sup_zones) > 1 else "N/A"

        # =========================
        # ATH / ATL FILTER (SR)
        # =========================
        if is_ath:
            resistance1 = resistance2 = "N/A"
        
        if is_atl:
            support1 = support2 = "N/A"
        
        def format_simple(zone):
            if not zone:
                return "N/A"
            return f"{price_tick(zone[0])} - {price_tick(zone[1])}"
        
        supply1 = format_simple(supply_zones[0]) if len(supply_zones) > 0 else "N/A"
        supply2 = format_simple(supply_zones[1]) if len(supply_zones) > 1 else "N/A"
        
        demand1 = format_simple(demand_zones[0]) if len(demand_zones) > 0 else "N/A"
        demand2 = format_simple(demand_zones[1]) if len(demand_zones) > 1 else "N/A"

        # =========================
        # ATH / ATL FILTER (SUPPLY DEMAND)
        # =========================
        if is_ath:
            supply1 = supply2 = "N/A"
        
        if is_atl:
            demand1 = demand2 = "N/A"



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
        # MARKET CONTEXT
        # =========================
        market_context = (
            "🚀 All Time High"
            if is_ath else
            "🧊 All Time Low"
            if is_atl else
            "📈 Range / Structure"
        )

        # =========================
        # TRADE PLAN
        # =========================

        if is_ath or is_atl or not merged_demand:
            entry_low = entry_high = "N/A"
            target1 = target2 = "N/A"
            invalidation = "N/A"
        else:
            best_demand = merged_demand[0]
        
            entry_low = price_tick(best_demand[0])
            entry_high = price_tick(best_demand[1])
        
            target1 = price_tick(entry_high * 1.05)
            target2 = price_tick(entry_high * 2)
            invalidation = price_tick(entry_low * 0.98)
        
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
            
        # =========================
        # CHART LAYOUT
        # =========================

        apds = []
        
        # RSI panel 2
        rsi_plot = mpf.make_addplot(
            df["RSI"],
            panel=2,
            color="blue",
            width=1.2
        )
        apds.append(rsi_plot)
        
        # STOCH panel 3
        k_plot = mpf.make_addplot(
            df["%K"],
            panel=3,
            color="green",
            width=1.2
        )
        
        d_plot = mpf.make_addplot(
            df["%D"],
            panel=3,
            color="red",
            width=1.2
        )
        
        apds.extend([k_plot, d_plot])
        
        file_path = f"{symbol}_chart.png"
        
        fig, axes = mpf.plot(
            df,
            type="candle",
            style="nightclouds",
            volume=True,              
            addplot=apds,
            panel_ratios=(4,1,1,1),
            figsize=(14,8),
            returnfig=True
        )
        
        # =========================
        # axes yang dipakai cuma index genap
        # karena mplfinance bikin twin axis
        # =========================
        
        main_axes = axes[::2]
        
        # 0 = price
        # 1 = volume
        # 2 = rsi
        # 3 = stoch
        
        # REMOVE GRID
        for ax in main_axes:
            ax.grid(False)
        
        # MOVE Y TO RIGHT
        for ax in main_axes:
            ax.yaxis.set_label_position("right")
            ax.yaxis.tick_right()
        
        # FIX LABEL
        main_axes[0].set_ylabel("Price")
        main_axes[1].set_ylabel("Vol")
        main_axes[2].set_ylabel("RSI")
        main_axes[3].set_ylabel("Stoch")
        
        # DATE FORMAT (horizontal)
        import matplotlib.dates as mdates
        main_axes[3].xaxis.set_major_formatter(mdates.DateFormatter('%d/%m/%y'))
        main_axes[3].tick_params(axis='x', rotation=0)

        # =========================
        # REFERENCE LINES (DI SINI!)
        # =========================
        # RSI
        main_axes[2].axhline(70, color="gray", linestyle="--", linewidth=1)
        main_axes[2].axhline(30, color="gray", linestyle="--", linewidth=1)
        
        # STOCH
        main_axes[3].axhline(80, color="gray", linestyle="--", linewidth=1)
        main_axes[3].axhline(20, color="gray", linestyle="--", linewidth=1)
        
        fig.savefig(file_path, bbox_inches="tight")
        plt.close(fig)
        
        await ctx.send(file=discord.File(file_path))
        
        caption += (
            f"💰 Last Price : {price_tick(last_price):,}\n\n"
        
            f"🟢 R1 : {resistance1}\n"
            f"🟢 R2 : {resistance2}\n\n"
        
            f"🔴 S1 : {support1}\n"
            f"🔴 S2 : {support2}\n"
            "══════════════════\n"
            f"📦 Supply : {supply1} | {supply2}\n"
            f"📥 Demand : {demand1} | {demand2}\n"
            "══════════════════\n"
            f"📈 RSI : {rsi_now:.2f}\n"
            f"📊 Stochastic 8,3,3 : {stoch_now:.2f}\n"

            "══════════════════\n"
            "📚 FUNDAMENTAL\n"
            f"PBV : {pbv_text}\n"
            f"Equity / Share : {book_value_text}\n"
        
            "══════════════════\n"
            "📊 BANDARMOLOGY\n"
        
            f"Bandar 3D // Buy : {format_value(b3_buy)} / Sell : {format_value(b3_sell)} "
            f"// Net : {format_value(b3_net)} ({b3_status}) Avg : {int(b3_avg)}\n"
        
            f"Bandar 1W // Buy : {format_value(b1_buy)} / Sell : {format_value(b1_sell)} "
            f"// Net : {format_value(b1_net)} ({b1_status}) Avg : {int(b1_avg)}\n"
        
            f"Bandar 1M // Buy : {format_value(bM_buy)} / Sell : {format_value(bM_sell)} "
            f"// Net : {format_value(bM_net)} ({bM_status}) Avg : {int(bM_avg)}\n\n"
        
            "🌍 FOREIGN FLOW\n"
        
            f"Foreign 3D // Buy : {format_value(f3_buy)} / Sell : {format_value(f3_sell)} "
            f"// Net : {format_value(f3_net)} ({f3_status}) Avg : {int(f3_avg)}\n"
        
            f"Foreign 1W // Buy : {format_value(f1_buy)} / Sell : {format_value(f1_sell)} "
            f"// Net : {format_value(f1_net)} ({f1_status}) Avg : {int(f1_avg)}\n"
        
            f"Foreign 1M // Buy : {format_value(fM_buy)} / Sell : {format_value(fM_sell)} "
            f"// Net : {format_value(fM_net)} ({fM_status}) Avg : {int(fM_avg)}\n"
        
            "══════════════════\n"
            f"\nWeekly Bias : {weekly_bias}"
            "🎯 TRADE PLAN\n\n"
        
            f"Bias : {bias}\n"
            f"Confidence : {probability}%\n\n"
        
            f"📌 Entry : {entry_low} - {entry_high}\n"
            f"🎯 Target 1 : {target1}\n"
            f"🎯 Target 2 : {target2}\n"
            f"🛑 Invalidation : {invalidation}\n\n"
        
            "#DYOR | #DisclaimerOn\n"
            "by @marketnmocha\n"
            "══════════════════\n"
        )

        await ctx.send(caption)

    except Exception as e:
        await ctx.send(f"❌ Error: {e}")


bot.run(TOKEN)
