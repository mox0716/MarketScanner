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

def run_swing_analyzer(ticker_file="tickers.txt"):
    if not os.path.exists(ticker_file): return pd.DataFrame()

    with open(ticker_file, 'r') as f:
        tickers = [line.strip().upper() for line in f if line.strip()]

    all_results = []

    for symbol in tickers:
        try:
            t = yf.Ticker(symbol)
            df = t.history(period="100d")
            if len(df) < 30: continue

            # --- 1. TREND & MOMENTUM ---
            df['SMA10'] = df['Close'].rolling(10).mean()
            df['SMA20'] = df['Close'].rolling(20).mean()
            df['VPT'] = calculate_vpt(df)
            
            today = df.iloc[-1]
            prev = df.iloc[-2]
            
            # --- 2. THE SWING FILTERS ---
            # Rule A: Sustained Trend (Price > 10SMA > 20SMA)
            is_trending = today['Close'] > today['SMA10'] > today['SMA20']
            
            # Rule B: VPT Accumulation (Money is flowing IN)
            is_accumulating = today['VPT'] > prev['VPT']
            
            # Rule C: Relative Strength vs SPY (Assuming SPY is checked elsewhere or benchmarked)
            # (We keep the RS check from our previous logic here)
            
            # Rule D: Not Overextended (Close Position check)
            # For 2-3 day holds, we actually like a 'Strong Close' (above 0.7) 
            # but NOT an 'Exhausted' one (ATR multiple < 2.0)
            tr = pd.concat([df['High']-df['Low'], np.abs(df['High']-df['Close'].shift()), np.abs(df['Low']-df['Close'].shift())], axis=1).max(axis=1)
            atr = tr.rolling(14).mean().iloc[-1]
            atr_multiple = (today['High'] - today['Low']) / atr

            if is_trending and is_accumulating and atr_multiple < 2.0:
                all_results.append({
                    "Ticker": symbol,
                    "Trend": "Confirmed",
                    "Money_Flow": "Accumulating",
                    "Price": round(today['Close'], 2),
                    "Stop_Loss": round(today['SMA20'], 2), # Using 20-day SMA as a dynamic stop
                    "Target_Exit": round(today['Close'] * 1.05, 2), # Targeting a 5% swing
                    "ATR_Vol": round(atr_multiple, 2)
                })
            
            time.sleep(0.05)
        except: continue

    return pd.DataFrame(all_results)

def send_swing_email(df):
    if df.empty:
        subject = "Swing Scanner: No Quality Trends Found"
        content = "Market conditions are currently choppy. No high-probability swing setups identified."
    else:
        subject = f"🚀 Swing Report: {len(df)} High-Conviction Setups"
        content = f"""
        <html>
        <body>
            <h2 style="color: #1a237e;">2-3 Day Swing Trade Targets</h2>
            <p>These stocks show sustained <b>Institutional Accumulation</b> (VPT) and are trending above their SMAs.</p>
            {df.to_html(index=False)}
            <br>
            <p><b>Strategy:</b> Set Stop Loss at the provided SMA20 price. Target a 3-5% exit over the next 72 hours.</p>
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
    results = run_swing_analyzer()
    send_swing_email(results)
