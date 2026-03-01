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
        # BANDAR & FOREIGN FORMAT (DISPLAY ONLY)
        # =========================
        
        def flow_state(net):
            return "Akumulasi" if net > 0 else "Distribusi"
        
        def format_net(v):
            sign = "+" if v > 0 else ""
            return f"{sign}{format_value(v)}"
        
        bandar_text = (
            "📊 BANDARMOLOGY\n"
            f"3D // {format_net(b3_net)}  @{int(b3_avg)} ({flow_state(b3_net)})\n"
            f"1W // {format_net(b1_net)} @{int(b1_avg)} ({flow_state(b1_net)})\n"
            f"1M // {format_net(bM_net)} @{int(bM_avg)} ({flow_state(bM_net)})"
        )
        
        foreign_text = (
            "🌍 FOREIGN FLOW\n"
            f"3D // {format_net(f3_net)}  @{int(f3_avg)} ({flow_state(f3_net)})\n"
            f"1W // {format_net(f1_net)} @{int(f1_avg)} ({flow_state(f1_net)})\n"
            f"1M // {format_net(fM_net)} @{int(fM_avg)} ({flow_state(fM_net)})"
        )
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
        # TRADE PLAN (STRUCTURE BASED)
        # =========================
        
        entry_low = entry_high = "N/A"
        target1 = target2 = "N/A"
        invalidation = "N/A"
        plan_note = ""
        
        # Guard condition
        if not merged_demand or is_ath or is_atl:
            plan_note = "No valid structure for trade"
        else:
            best_demand = merged_demand[0]
            entry_low = price_tick(best_demand[0])
            entry_high = price_tick(best_demand[1])
            invalidation = price_tick(entry_low * 0.98)
        
            # === TARGET LOGIC ===
        
            # Priority 1: Supply
            if merged_supply:
                target1 = price_tick(merged_supply[0][0])
            # Priority 2: Resistance
            elif resistance1 != "N/A":
                target1 = int(resistance1.split(" - ")[0].replace(",", ""))
            else:
                target1 = "N/A"
        
            # Target 2 hanya kalau Weekly Bullish
            if weekly_bias == "Bullish Macro" and resistance2 != "N/A":
                target2 = int(resistance2.split(" - ")[0].replace(",", ""))
            else:
                target2 = "N/A"
        
            # Note berdasarkan Weekly Bias
            if weekly_bias == "Macro Range":
                plan_note = "Range market: focus reaction, not continuation"
            elif weekly_bias == "Bullish Macro":
                plan_note = "Bullish macro: continuation possible"
            elif weekly_bias == "Bearish Macro":
                plan_note = "Bearish macro: aggressive buy not recommended"
        
        # =========================
        # SWING QUALITY VALIDATOR
        # =========================
        
        swing_quality = "N/A"
        swing_status = "❌ NO TRADE"
        quality_note = ""
        
        if entry_low != "N/A" and target1 != "N/A" and invalidation != "N/A":
        
            risk = abs(entry_low - invalidation)
            reward = abs(target1 - entry_high)
        
            if risk <= 0 or reward <= 0:
                swing_quality = "Low"
                quality_note = "Invalid structure measurement"
            else:
                efficiency = reward / risk
        
                if efficiency >= 2:
                    swing_quality = "High"
                    swing_status = "✅ VALID SETUP"
                    quality_note = "Clean swing: open liquidity & space to target"
        
                elif efficiency >= 1.3:
                    swing_quality = "Medium"
                    swing_status = "⚠️ CONDITIONAL"
                    quality_note = "Acceptable swing but watch supply reaction"
        
                else:
                    swing_quality = "Low"
                    quality_note = "Target too close / risk too wide"
        
        else:
            quality_note = "No valid swing structure"
            
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
        
        caption += (
            f"📈 RSI : {rsi_now:.2f}\n"
            f"📊 Stochastic 8,3,3 : {stoch_now:.2f}\n"
            "══════════════════\n"
            "📚 FUNDAMENTAL\n"
            f"PBV : {pbv_text}\n"
            f"Equity / Share : {book_value_text}\n"
            "══════════════════\n"
            f"{bandar_text}\n\n"
            f"{foreign_text}\n"
            "══════════════════\n"
            "🎯 TRADE PLAN\n"
            f"💰 Last Price : {price_tick(last_price):,}\n"
            f"📌 Entry : {entry_low} - {entry_high}\n"
            f"🎯 Target 1 : {target1}\n"
            f"🎯 Target 2 : {target2}\n"
            f"🛑 Invalidation : {invalidation}\n"
            "══════════════════\n"
            f"\nWeekly Bias : {weekly_bias}\n"
            f"📐 Swing Quality : {swing_quality}\n"
            f"📊 Status : {swing_status}\n"
            f"🧠 Insight : {quality_note}\n"
            f"📝 Note : {plan_note}\n"
            "#DYOR | #DisclaimerOn\n"
            "by @marketnmocha\n"
            "══════════════════\n"
        )

        if file_path:
            await ctx.send(
                file=discord.File(file_path),
                content=caption
            )
        else:
            await ctx.send(caption)

    except Exception as e:
        await ctx.send(f"❌ Error: {e}")


bot.run(TOKEN)
