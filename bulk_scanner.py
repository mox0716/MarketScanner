import yfinance as yf
import pandas as pd
import numpy as np
import os
import time
import smtplib
from email.message import EmailMessage

def calculate_vpt(df):
    """Calculates Volume Price Trend (VPT) to confirm accumulation."""
    vpt = ((df['Close'] - df['Close'].shift(1)) / df['Close'].shift(1)) * df['Volume']
    return vpt.cumsum()

def run_pro_swing_analyzer(ticker_file="tickers.txt"):
    if not os.path.exists(ticker_file): return pd.DataFrame()

    with open(ticker_file, 'r') as f:
        tickers = [line.strip().upper() for line in f if line.strip()]

    all_results = []

    for symbol in tickers:
        try:
            t = yf.Ticker(symbol)
            
            # --- 1. THE "GARBAGE" FILTERS (Market Cap & Price) ---
            info = t.info
            market_cap = info.get('marketCap', 0)
            current_price = info.get('previousClose', 0) # Faster than full history for initial check
            
            if market_cap < 100_000_000: continue  # Filter: Cap > $100M
            if current_price < 1.00: continue     # Filter: Price > $1

            df = t.history(period="100d")
            if len(df) < 30: continue

            # --- 2. LIQUIDITY FILTER (Avg Volume) ---
            avg_vol_30d = df['Volume'].tail(30).mean()
            if avg_vol_30d < 300_000: continue    # Filter: Vol > 300k shares

            # --- 3. TREND & MOMENTUM ---
            df['SMA10'] = df['Close'].rolling(10).mean()
            df['SMA20'] = df['Close'].rolling(20).mean()
            df['VPT'] = calculate_vpt(df)
            
            today = df.iloc[-1]
            prev = df.iloc[-2]
            
            # Swing Rules: Price > 10SMA > 20SMA AND Money Flowing In (VPT)
            is_trending = today['Close'] > today['SMA10'] > today['SMA20']
            is_accumulating = today['VPT'] > prev['VPT']
            
            # ATR Volatility check (Not exhausted)
            tr = pd.concat([df['High']-df['Low'], np.abs(df['High']-df['Close'].shift()), np.abs(df['Low']-df['Close'].shift())], axis=1).max(axis=1)
            atr = tr.rolling(14).mean().iloc[-1]
            atr_multiple = (today['High'] - today['Low']) / atr

            if is_trending and is_accumulating and atr_multiple < 2.2:
                all_results.append({
                    "Ticker": symbol,
                    "Price": round(today['Close'], 2),
                    "Mkt_Cap_M": f"{market_cap/1e6:.1f}M",
                    "Avg_Vol_K": f"{avg_vol_30d/1e3:.0f}K",
                    "Stop_Loss": round(today['SMA20'], 2),
                    "Target_TP": round(today['Close'] * 1.05, 2), # 5% Swing Target
                    "VPT_Trend": "Upward"
                })
            
            time.sleep(0.05) 
        except: continue

    return pd.DataFrame(all_results)

def send_swing_email(df):
    if df.empty:
        subject = "Swing Report: No Quality Setups"
        content = "Market conditions did not meet the liquidity or trend requirements today."
    else:
        # Sort by Market Cap so you see the biggest, safest companies first
        df_sorted = df.sort_values(by="Price", ascending=False)
        subject = f"🚀 Swing Report: {len(df)} Institutional-Grade Setups"
        content = f"""
        <html>
        <head>
        <style>
            table {{ border-collapse: collapse; width: 100%; font-family: sans-serif; }}
            th, td {{ text-align: left; padding: 10px; border-bottom: 1px solid #ddd; }}
            th {{ background-color: #0d47a1; color: white; }}
            tr:nth-child(even) {{ background-color: #f2f2f2; }}
        </style>
        </head>
        <body>
            <h2 style="color: #0d47a1;">Professional 2-3 Day Swing Targets</h2>
            <p>Filtered for <b>Cap > $100M</b>, <b>Price > $1</b>, and <b>Vol > 300k</b>.</p>
            {df_sorted.to_html(index=False)}
            <br>
            <p><b>Rules:</b> Exit if Price < Stop Loss. Profit Target is +5%.</p>
        </body>
        </html>
        """
    
    msg = EmailMessage()
    msg.add_alternative(content, subtype='html')
    msg['Subject'] = subject
    msg['From'] = os.environ.get('EMAIL_USER')
    msg['To'] = os.environ.get('EMAIL_RECEIVER')

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(os.environ.get('EMAIL_USER'), os.environ.get('EMAIL_PASS'))
        smtp.send_message(msg)

if __name__ == "__main__":
    results = run_pro_swing_analyzer()
    send_swing_email(results)
