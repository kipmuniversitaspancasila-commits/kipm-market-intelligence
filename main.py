import discord
from discord.ext import commands
import yfinance as yf
import pandas as pd
import mplfinance as mpf
import numpy as np
import os

# =========================================
# CONFIG
# =========================================
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Bot aktif sebagai {bot.user}")


# =========================================
# INDICATORS
# =========================================

# ---------------- RSI ----------------
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# ---------------- STOCHASTIC 8,3,3 ----------------
def calculate_stochastic(df, k_period=8, d_period=3, smooth=3):
    low_min = df["Low"].rolling(window=k_period).min()
    high_max = df["High"].rolling(window=k_period).max()
    k = 100 * ((df["Close"] - low_min) / (high_max - low_min))
    k_smooth = k.rolling(window=smooth).mean()
    d = k_smooth.rolling(window=d_period).mean()
    return k_smooth, d


# ---------------- FREQUENCY ANALYZER ----------------
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

        def score_zone(zone):
            score = 0
            
            if zone["type"] in ["supply", "demand"]:
                score += 2
            if zone.get("has_sr", False):
                score += 2
            if zone.get("has_fvg", False):
                score += 1
            if zone.get("fresh", False):
                score += 1
            if zone.get("multi_tf", False):
                score += 2
        
            return score

        def classify_zone(score):
            if score >= 6:
                return "🔥 Major Institutional Zone"
            elif score >= 4:
                return "⚡ Strong Reaction Zone"
            elif score >= 2:
                return "🟡 Moderate Zone"
            else:
                return "⚪ Weak Zone"

        def estimate_probability(score):
            if score >= 6:
                return "≈ 75% reaction probability"
            elif score >= 4:
                return "≈ 60% reaction probability"
            elif score >= 2:
                return "≈ 45% reaction probability"
            else:
                return "Low probability"

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

            return supply_zones[:2], demand_zones[:2]


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
        report = f"""

BANDARMOLOGY REPORT — {ticker.replace(".JK","")}

3 Hari Terakhir

Bandar
Buy : {format_value(bandar_3d[0])}
Sell : {format_value(bandar_3d[1])}
Net : {format_value(bandar_3d[2])} ({bandar_3d[4]})
Avg Price : {bandar_3d[3]:,.0f}

Foreign
Buy : {format_value(foreign_3d[0])}
Sell : {format_value(foreign_3d[1])}
Net : {format_value(foreign_3d[2])} ({foreign_3d[4]})
Avg Price : {foreign_3d[3]:,.0f}

1 Week Terakhir

Bandar
Buy : {format_value(bandar_1w[0])}
Sell : {format_value(bandar_1w[1])}
Net : {format_value(bandar_1w[2])} ({bandar_1w[4]})
Avg Price : {bandar_1w[3]:,.0f}

Foreign
Buy : {format_value(foreign_1w[0])}
Sell : {format_value(foreign_1w[1])}
Net : {format_value(foreign_1w[2])} ({foreign_1w[4]})
Avg Price : {foreign_1w[3]:,.0f}

1 Month Terakhir

Bandar
Buy : {format_value(bandar_1m[0])}
Sell : {format_value(bandar_1m[1])}
Net : {format_value(bandar_1m[2])} ({bandar_1m[4]})
Avg Price : {bandar_1m[3]:,.0f}

Foreign
Buy : {format_value(foreign_1m[0])}
Sell : {format_value(foreign_1m[1])}
Net : {format_value(foreign_1m[2])} ({foreign_1m[4]})
Avg Price : {foreign_1m[3]:,.0f}
"""

        # =============================
        # SUPPORT RESISTANCE RESULT
        # =============================
        current_price = float(last_price)

        res_zones, sup_zones = calculate_sr_zones(df, current_price)
        supply_zones, demand_zones = calculate_supply_demand(df, current_price)
        upper_fvg, lower_fvg = calculate_fvg(df, current_price)

        def format_zone(zone):
            if zone:
                return f"{int(zone[0]//10*10)} - {int(zone[1]//10*10)} (x{zone[2]})"
            return "N/A"

        resistance1 = format_zone(res_zones[0]) if len(res_zones) > 0 else "N/A"
        resistance2 = format_zone(res_zones[1]) if len(res_zones) > 1 else "N/A"

        support1 = format_zone(sup_zones[0]) if len(sup_zones) > 0 else "N/A"
        support2 = format_zone(sup_zones[1]) if len(sup_zones) > 1 else "N/A"


        def format_simple_zone(zone):
            if not zone:
                return "N/A"
            return f"{int(zone[0]//10*10)} - {int(zone[1]//10*10)}"
            
        supply1 = format_simple_zone(supply_zones[0]) if len(supply_zones)>0 else "N/A"
        supply2 = format_simple_zone(supply_zones[1]) if len(supply_zones)>1 else "N/A"
        
        demand1 = format_simple_zone(demand_zones[0]) if len(demand_zones)>0 else "N/A"
        demand2 = format_simple_zone(demand_zones[1]) if len(demand_zones)>1 else "N/A"

        def format_fvg(zone):
            if not zone:
                return "N/A"
            return f"{int(zone[0]//10*10)} - {int(zone[1]//10*10)}"
        
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
                "multi_tf": False
            }

            zone["score"] = score_zone(zone)
            zone["label"] = classify_zone(zone["score"])
            final_supply_zones.append(zone)

        for low, high in merged_demand:
            zone = {
                "low": low,
                "high": high,
                "type": "demand",
                "has_sr": False,
                "has_fvg": False,
                "fresh": True,
                "multi_tf": False
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


        def detect_bias(supply_zones, demand_zones, rsi_value):
            supply_score = max([z["score"] for z in supply_zones], default=0)
            demand_score = max([z["score"] for z in demand_zones], default=0)
        
            if demand_score > supply_score and rsi_value < 30:
                return "🟢 Bullish Reversal Potential"
        
            elif supply_score > demand_score and rsi_value > 70:
                return "🔴 Bearish Rejection Potential"
        
            else:
                return "⚖️ Neutral / Wait Confirmation"
        
        
        def liquidity_magnet(last_price, upper_fvg, lower_fvg):
            if upper_fvg and last_price < upper_fvg[0]:
                return "🎯 Price attracted to Upper FVG"
        
            if lower_fvg and last_price > lower_fvg[1]:
                return "🎯 Price attracted to Lower FVG"
        
            return "No strong liquidity magnet"
        
                
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
            f"{summary_text}\n"
            "#DYOR\n"
            "#DisclaimerOn\n"
            "by @marketnmocha"
        )

        file = discord.File(file_path)
        await ctx.send(file=file, content=caption)

    except Exception as e:
        await ctx.send(f"❌ Error: {e}")

bot.run(TOKEN)
