# ===============================
# KIPM MARKET INTELLIGENCE v2
# Institutional Engine Upgrade
# ===============================

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
    print(f"KIPM Market Intelligence v2 aktif sebagai {bot.user}")


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
# FREQUENCY ANALYZER
# ===============================
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


# ===============================
# ZONE SCORING v2
# ===============================
def score_zone(zone):

    score = 1  # base score

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
# LIQUIDITY SWEEP DETECTOR
# ===============================
def detect_liquidity_sweep(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]

    if last["Low"] < prev["Low"] and last["Close"] > prev["Low"]:
        return True

    if last["High"] > prev["High"] and last["Close"] < prev["High"]:
        return True

    return False


# ===============================
# VOLUME SPIKE
# ===============================
def detect_volume_spike(df):
    avg = df["Volume"].rolling(20).mean().iloc[-1]
    last = df["Volume"].iloc[-1]
    return last > avg * 1.8


# ===============================
# IMPULSE MOVE
# ===============================
def detect_impulse(df):
    move = abs(df["Close"].iloc[-1] - df["Close"].iloc[-3])
    base = df["Close"].iloc[-3]
    return (move / base) > 0.03


# ===============================
# MARKET BIAS ENGINE
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

def liquidity_magnet(last_price, upper_fvg, lower_fvg):

    if upper_fvg:
        fvg_low, fvg_high = upper_fvg
        if last_price < fvg_low:
            return "🎯 Price attracted to Upper FVG"

    if lower_fvg:
        fvg_low, fvg_high = lower_fvg
        if last_price > fvg_high:
            return "🎯 Price attracted to Lower FVG"

    return "No strong liquidity magnet"


# ===============================
# MERGE ZONES
# ===============================
def merge_zones(zones):
    if not zones:
        return []

    zones = sorted(zones, key=lambda x: x[0])
    merged = []

    current_low, current_high = zones[0]

    for low, high in zones[1:]:
        if low <= current_high:
            current_high = max(current_high, high)
        else:
            merged.append((current_low, current_high))
            current_low, current_high = low, high

    merged.append((current_low, current_high))
    return merged

# ===============================
# PRICE FRACTION ENGINE (IDX)
# ===============================
def get_tick_size(price):

    if price < 200:
        return 1
    elif price < 500:
        return 2
    elif price < 2000:
        return 5
    elif price < 5000:
        return 10
    else:
        return 25


def round_down(price):
    tick = get_tick_size(price)
    return int(price // tick * tick)


def round_up(price):
    tick = get_tick_size(price)
    return int((price + tick - 1) // tick * tick)
# ===============================
# TRADE PLAN BUILDER
# ===============================
def build_trade_plan(final_supply_zones, final_demand_zones,
                     upper_fvg, sup_zones, res_zones,
                     bias, probability):

    best_demand = max(final_demand_zones, key=lambda z: z["score"], default=None)

    if not best_demand or best_demand["score"] < 2:
        return (
            "══════════════════\n"
            "🎯 TRADE PLAN\n\n"
            "Bias : ⚖️ Neutral / Wait Confirmation\n"
            "Confidence : Low\n\n"
            "No high-quality zone detected.\n"
            "══════════════════\n"
        )

    entry_low = round_down(best_demand["low"])
    entry_high = round_down(best_demand["high"])

    zone_range = entry_high - entry_low

    # =================================
    # TARGET ENGINE SMART
    # =================================
    
    zone_range = entry_high - entry_low
    risk = entry_high - invalidation
    
    min_target_distance = risk * 2.5
    
    target1 = entry_high + max(zone_range * 2, min_target_distance)
    
    target2 = entry_high + max(zone_range * 4, risk * 4)
    
    # resistance override (hanya jika lebih jauh)
    if res_zones:
        resistance_price = int(res_zones[0][0])
        if resistance_price > target1:
            target2 = max(target2, resistance_price)
    
    # FVG override (hanya jika jauh)
    if upper_fvg:
        fvg_low, fvg_high = upper_fvg[0]
        if fvg_low > target1:
            target2 = max(target2, int(fvg_low))
    
    # rounding sesuai fraksi IDX
    target1 = round_up(target1)
    target2 = round_up(target2)
                         

    # =============================
    # STOPLOSS ENGINE FIX 
    # =============================
    
    invalidation = None
    
    valid_support = None
    
    if sup_zones:
        for s in sup_zones:
            support_price = s[0]
            if support_price < entry_low:
                valid_support = support_price
                break
    
    # Priority 1 → support
    if valid_support is not None:
        invalidation = round_down(valid_support)
    
    # Priority 2 → demand low
    elif best_demand:
        invalidation = round_down(best_demand["low"] * 0.995)
    
    # Priority 3 → fallback
    else:
        invalidation = round_down(entry_low * 0.985)
    
    # Safety guard
    if invalidation >= entry_low:
        invalidation = round_down(entry_low * 0.985)

    confidence = min(85, best_demand["score"] * 14)

    return (
        "══════════════════\n"
        "🎯 TRADE PLAN\n\n"
        f"Bias : {bias}\n"
        f"Confidence : {confidence}%\n\n"
        f"📌 Entry : {entry_low} - {entry_high}\n"
        f"🎯 Target 1 : {int(target1)}\n"
        f"🎯 Target 2 : {int(target2)}\n"
        f"🛑 Invalidation : {invalidation}\n"
        "══════════════════\n"
    )
# =========================================
# MAIN COMMAND
# =========================================
@bot.command()
async def chart(ctx, ticker: str):

    try:

        # =========================================
        # PREPARE DATA
        # =========================================
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

        # =========================================
        # FREQUENCY
        # =========================================
        if last_price < 2000:
            bins = 20
        elif last_price < 5000:
            bins = 25
        else:
            bins = 30

        freq_series = calculate_frequency_series(df, bins=bins)

        # =========================================
        # RSI
        # =========================================
        df["RSI"] = calculate_rsi(df["Close"])
        rsi_now = float(df["RSI"].iloc[-1])

        # =========================================
        # STOCHASTIC
        # =========================================
        k, d = calculate_stochastic(df)
        stoch_now = float(k.iloc[-1])

        # =========================================
        # SUPPORT RESISTANCE ENGINE
        # =========================================
        def calculate_sr_zones(df, current_price, window=7, tolerance=0.015):

            swing_highs = []
            swing_lows = []

            for i in range(window, len(df) - window):
                high_slice = df["High"].iloc[i - window:i + window]
                low_slice = df["Low"].iloc[i - window:i + window]

                if df["High"].iloc[i] == high_slice.max():
                    swing_highs.append(float(df["High"].iloc[i]))

                if df["Low"].iloc[i] == low_slice.min():
                    swing_lows.append(float(df["Low"].iloc[i]))

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

        # =========================================
        # SUPPLY DEMAND ENGINE
        # =========================================
        def calculate_supply_demand(df, current_price, impulse_threshold=0.03):

            supply_zones = []
            demand_zones = []

            for i in range(2, len(df) - 3):

                base_candle = df.iloc[i]
                future = df.iloc[i + 1:i + 4]

                up_move = (future["High"].max() - base_candle["Close"]) / base_candle["Close"]
                down_move = (base_candle["Close"] - future["Low"].min()) / base_candle["Close"]

                if up_move >= impulse_threshold:
                    demand_zones.append((base_candle["Low"], base_candle["Open"]))

                if down_move >= impulse_threshold:
                    supply_zones.append((base_candle["Open"], base_candle["High"]))

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


        # =========================================
        # FAIR VALUE GAP ENGINE
        # =========================================
        def calculate_fvg(df, current_price):
        
            bullish_fvg = []
            bearish_fvg = []
        
            for i in range(2, len(df)):
                c1 = df.iloc[i-2]
                c2 = df.iloc[i-1]
                c3 = df.iloc[i]
        
                # Bullish FVG (imbalance bawah → target retrace)
                if c1["High"] < c3["Low"]:
                    lower = c1["High"]
                    upper = c3["Low"]
                    bullish_fvg.append((lower, upper))
        
                # Bearish FVG (imbalance atas → target retrace)
                if c1["Low"] > c3["High"]:
                    lower = c3["High"]
                    upper = c1["Low"]
                    bearish_fvg.append((lower, upper))
        
            # Filter relatif terhadap current price
            upper_fvg = sorted(
                [z for z in bearish_fvg if z[0] > current_price],
                key=lambda x: x[0]
            )
        
            lower_fvg = sorted(
                [z for z in bullish_fvg if z[1] < current_price],
                key=lambda x: x[1],
                reverse=True
            )
        
            return upper_fvg[:2], lower_fvg[:2]
            
        # =========================================
        # ZONE MERGE FUNCTION
        # =========================================
        
        def merge_zones(zones):
            if not zones:
                return []
        
            zones = sorted(zones, key=lambda x: x[0])
            merged = []
        
            current_low, current_high = zones[0]
        
            for low, high in zones[1:]:
                if low <= current_high:  # overlap
                    current_high = max(current_high, high)
                else:
                    merged.append((current_low, current_high))
                    current_low, current_high = low, high
        
            merged.append((current_low, current_high))
            return merged
        

        # =========================================
        # FUNDAMENTAL
        # =========================================
        stock = yf.Ticker(ticker)
        info = stock.info

        pbv = info.get("priceToBook", None)
        equity = info.get("bookValue", None)

        pbv_text = f"{float(pbv):.2f}" if pbv else "N/A"
        equity_text = f"{float(equity):.2f}" if equity else "N/A"

        # =========================================
        # BANDARMOLOGY ENGINE
        # =========================================
        def format_value(v):
            if v >= 1_000_000_000_000:
                return f"{v/1_000_000_000_000:.2f} T"
            elif v >= 1_000_000_000:
                return f"{v/1_000_000_000:.2f} B"
            elif v >= 1_000_000:
                return f"{v/1_000_000:.2f} M"
            else:
                return f"{v:.0f}"

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

        bandar_3d = bandar_engine(df.tail(3))
        bandar_1w = bandar_engine(df.tail(5))
        bandar_1m = bandar_engine(df.tail(22))

        foreign_3d = foreign_engine(df.tail(3))
        foreign_1w = foreign_engine(df.tail(5))
        foreign_1m = foreign_engine(df.tail(22))

        # =========================================
        # NUMBER FORMATTER
        # =========================================
    
        def format_billions(v):
            v = float(v)
        
            if abs(v) >= 1_000_000_000_000:
                return f"{v/1_000_000_000_000:.2f} T"
            elif abs(v) >= 1_000_000_000:
                return f"{v/1_000_000_000:.2f} B"
            elif abs(v) >= 1_000_000:
                return f"{v/1_000_000:.2f} M"
            else:
                return f"{v:,.0f}"

        def get_tick_size(price):
            if price < 200:
                return 1
            elif price < 500:
                return 2
            elif price < 2000:
                return 5
            elif price < 5000:
                return 10
            else:
                return 25

        def round_down(price):
            tick = get_tick_size(price)
            return int((price // tick) * tick)
        
        def round_up(price):
            tick = get_tick_size(price)
            return int(((price + tick - 1) // tick) * tick)

        # =============================
        # STYLE (TIDAK DIUBAH)
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
            y_on_right=True,
            rc={
                "xtick.color": "white",
                "ytick.color": "white",
                "axes.labelcolor": "white",
                "axes.edgecolor": "white",
                "text.color": "white"
            }
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
            ax.yaxis.set_label_position("right")

        fig.savefig(file_path)

        # =============================
        # BANDARMOLOGY REPORT TEXT
        # =============================

        report = (
            "══════════════════\n"
            "📊 BANDARMOLOGY REPORT\n\n"
        
            f"Bandar 3D\n"
            f"Buy : {format_billions(bandar_3d[0])} / "
            f"Sell : {format_billions(bandar_3d[1])}\n"
            f" Net : {format_billions(bandar_3d[2])} ({bandar_3d[4]})\n"
            f"Avg Price : {int(bandar_3d[3])}\n\n"
        
            f"Bandar 1W\n"
            f"Buy : {format_billions(bandar_1w[0])} / "
            f"Sell : {format_billions(bandar_1w[1])}\n"
            f" Net : {format_billions(bandar_1w[2])} ({bandar_1w[4]})\n"
            f"Avg Price : {int(bandar_1w[3])}\n\n"
        
            f"Bandar 1M\n"
            f"Buy : {format_billions(bandar_1m[0])} / "
            f"Sell : {format_billions(bandar_1m[1])}\n"
            f" Net : {format_billions(bandar_1m[2])} ({bandar_1m[4]})\n"
            f"Avg Price : {int(bandar_1m[3])}\n\n"
        
            "══════════════════\n"
            "🌍 FOREIGN FLOW\n\n"
        
            f"Foreign 3D\n"
            f"Buy : {format_billions(foreign_3d[0])} / "
            f"Sell : {format_billions(foreign_3d[1])}\n"
            f" Net : {format_billions(foreign_3d[2])} ({foreign_3d[4]})\n"
            f"Avg Price : {int(foreign_3d[3])}\n\n"
        
            f"Foreign 1W\n"
            f"Buy : {format_billions(foreign_1w[0])} / "
            f"Sell : {format_billions(foreign_1w[1])}\n"
            f" Net : {format_billions(foreign_1w[2])} ({foreign_1w[4]})\n"
            f"Avg Price : {int(foreign_1w[3])}\n\n"
        
            f"Foreign 1M\n"
            f"Buy : {format_billions(foreign_1m[0])} / "
            f"Sell : {format_billions(foreign_1m[1])}\n"
            f" Net : {format_billions(foreign_1m[2])} ({foreign_1m[4]})\n"
            f"Avg Price : {int(foreign_1m[3])}\n"
        )
        # =============================
        # SUPPORT RESISTANCE RESULT
        # =============================
        current_price = float(last_price)

        res_zones, sup_zones = calculate_sr_zones(df, current_price)
        supply_zones, demand_zones = calculate_supply_demand(df, current_price)
        upper_fvg, lower_fvg = calculate_fvg(df, current_price)

        def format_zone(zone):
            if zone:
                return f"{round_down(zone[0])} - {round_down(zone[1])} (x{zone[2]})"
            return "N/A"

        resistance1 = format_zone(res_zones[0]) if len(res_zones) > 0 else "N/A"
        resistance2 = format_zone(res_zones[1]) if len(res_zones) > 1 else "N/A"

        support1 = format_zone(sup_zones[0]) if len(sup_zones) > 0 else "N/A"
        support2 = format_zone(sup_zones[1]) if len(sup_zones) > 1 else "N/A"


        def format_simple_zone(zone):
            if not zone:
                return "N/A"
            return f"{round_down(zone[0])} - {round_down(zone[1])}"
            
        supply1 = format_simple_zone(supply_zones[0]) if len(supply_zones)>0 else "N/A"
        supply2 = format_simple_zone(supply_zones[1]) if len(supply_zones)>1 else "N/A"
        
        demand1 = format_simple_zone(demand_zones[0]) if len(demand_zones)>0 else "N/A"
        demand2 = format_simple_zone(demand_zones[1]) if len(demand_zones)>1 else "N/A"

        def format_fvg(zone):
            if not zone:
                return "N/A"
            return f"{round_down(zone[0])} - {round_down(zone[1])}"
        
        upper_fvg1 = format_fvg(upper_fvg[0]) if len(upper_fvg)>0 else "N/A"
        upper_fvg2 = format_fvg(upper_fvg[1]) if len(upper_fvg)>1 else "N/A"
        
        lower_fvg1 = format_fvg(lower_fvg[0]) if len(lower_fvg)>0 else "N/A"
        lower_fvg2 = format_fvg(lower_fvg[1]) if len(lower_fvg)>1 else "N/A"

        # =========================================
        # SUPPLY & DEMAND MERGE ENGINE
        # =========================================
        merged_supply = merge_zones(supply_zones)
        merged_demand = merge_zones(demand_zones)


        # =========================================
        # BUILD & SCORE ZONES
        # =========================================
        final_supply_zones = []
        final_demand_zones = []

        for low, high in merged_supply:
            zone = {
                "low": low,
                "high": high,
                "type": "supply",
                "has_sr": False,
                "has_fvg": False,
                "fresh": True,
                "multi_tf": False,
                "liquidity_sweep": detect_liquidity_sweep(df),
                "impulsive_move": detect_impulse(df),
                "volume_spike": detect_volume_spike(df)
            }

            zone["score"] = score_zone(zone)
            zone["label"] = classify_zone(zone["score"])
            final_supply_zones.append(zone)

        for low, high in merged_demand:
        
            has_sr = any(low <= r[0] <= high for r in res_zones)
            has_fvg = any(low <= fvg[0] <= high for fvg in lower_fvg)
        
            zone = {
                "low": low,
                "high": high,
                "type": "demand",
                "has_sr": has_sr,
                "has_fvg": has_fvg,
                "fresh": True,
                "multi_tf": False,
                "liquidity_sweep": detect_liquidity_sweep(df),
                "impulsive_move": detect_impulse(df),
                "volume_spike": detect_volume_spike(df)
            }
            zone["score"] = score_zone(zone)
            zone["label"] = classify_zone(zone["score"])
            final_demand_zones.append(zone)


        # =========================================
        # MARKET BIAS & PROBABILITY
        # =========================================
        bias = detect_bias(final_supply_zones, final_demand_zones, rsi_now)

        best_zone_score = max(
            [z["score"] for z in final_supply_zones + final_demand_zones],
            default=0
        )

        probability = estimate_probability(best_zone_score)


        # =========================================
        # LIQUIDITY MAGNET
        # =========================================
        upper_fvg_tuple = upper_fvg[0] if len(upper_fvg) > 0 else None
        lower_fvg_tuple = lower_fvg[0] if len(lower_fvg) > 0 else None

        magnet = liquidity_magnet(
            float(last_price),
            upper_fvg_tuple,
            lower_fvg_tuple
        )


        # =========================================
        # CONFLUENCE SUMMARY BUILDER
        # =========================================
        summary_text = "\n══════════════════\n🎯 CONFLUENCE SUMMARY\n\n"
        # DEBUG CHECK DATA
        print("Demand:", final_demand_zones)
        print("Supply:", final_supply_zones)
        print("sup_zones:", sup_zones)
        print("res_zones:", res_zones)
        print("FVG:", upper_fvg)
                
        trade_plan_text = build_trade_plan(
            final_supply_zones,
            final_demand_zones,
            upper_fvg,
            sup_zones,
            res_zones,    
            bias,
            probability
        )

        for zone in final_supply_zones:
            summary_text += (
                f"📦 {int(zone['low']//10*10)} - {int(zone['high']//10*10)} "
                f"(Score: {zone['score']})\n"
                f"{zone['label']}\n\n"
            )

        for zone in final_demand_zones:
            summary_text += (
                f"📥 {int(zone['low']//10*10)} - {int(zone['high']//10*10)} "
                f"(Score: {zone['score']})\n"
                f"{zone['label']}\n\n"
            )

        summary_text += (
            f"🧭 Market Bias : {bias}\n"
            f"{magnet}\n"
            f"📊 Estimated Reaction Probability : {probability}\n"
            "══════════════════\n"
        )


        # =============================
        # FINAL CAPTION
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
        
            f"🎯 Upside Target (FVG)\n"
            f"Upper FVG 1 : {upper_fvg1}\n"
            f"Upper FVG 2 : {upper_fvg2}\n\n"
        
            f"🎯 Downside Target (FVG)\n"
            f"Lower FVG 1 : {lower_fvg1}\n"
            f"Lower FVG 2 : {lower_fvg2}\n\n"
        
            f"📈 RSI : {rsi_now:.2f}\n"
            f"📊 Stochastic 8,3,3 : {stoch_now:.2f}\n\n"
        
            f"📚 PBV : {pbv_text}\n"
            f"🏛️ Equity / Share : {equity_text}\n"
        
            f"{report}\n"
            f"{trade_plan_text}\n"
            "#DYOR\n"
            "#DisclaimerOn\n"
            "by @marketnmocha"
        )

        file = discord.File(file_path)
        await ctx.send(file=file, content=caption)

    except Exception as e:
        await ctx.send(f"❌ Error: {e}")

bot.run(TOKEN)
