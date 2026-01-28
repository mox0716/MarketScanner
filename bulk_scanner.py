import yfinance as yf
import pandas as pd
import numpy as np
import os
import time
import smtplib
from email.message import EmailMessage

def calculate_atr(df, period=14):
    """Calculates Average True Range to measure volatility quality."""
    high_low = df['High'] - df['Low']
    high_cp = np.abs(df['High'] - df['Close'].shift())
    low_cp = np.abs(df['Low'] - df['Close'].shift())
    tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def get_market_benchmarks():
    """Fetches SPY data to calculate Relative Strength."""
    spy = yf.Ticker("SPY").history(period="20d")
    spy_change = (spy['Close'].iloc[-1] - spy['Close'].iloc[-2]) / spy['Close'].iloc[-2]
    spy_is_healthy = spy['Close'].iloc[-1] > spy['Low'].iloc[-1] # Closing in upper half
    return spy_change, spy_is_healthy

def run_alpha_analyzer(ticker_file="tickers.txt"):
    if not os.path.exists(ticker_file): return pd.DataFrame()

    spy_change, market_is_healthy = get_market_benchmarks()
    
    # RISK GATE: If SPY is dumping, we stay in cash.
    if not market_is_healthy:
        print("Market (SPY) is showing weakness. Scanning aborted to protect capital.")
        return pd.DataFrame()

    with open(ticker_file, 'r') as f:
        tickers = [line.strip().upper() for line in f if line.strip()]

    all_results = []

    for symbol in tickers:
        try:
            t = yf.Ticker(symbol)
            df = t.history(period="50d")
            if len(df) < 20: continue

            # --- 1. CALCULATE VOLATILITY QUALITY (ATR) ---
            df['ATR'] = calculate_atr(df)
            today = df.iloc[-1]
            prev_day = df.iloc[-2]
            
            # Filter 5: Exhaustion Check
            # If today's range is > 2.5x the average, it's a 'blow-off top' risk.
            todays_range = today['High'] - today['Low']
            is_exhausted = todays_range > (today['ATR'] * 2.5)

            # --- 2. CALCULATE RELATIVE STRENGTH (RS) ---
            stock_change = (today['Close'] - prev_day['Close']) / prev_day['Close']
            # RS is the outperformance margin vs SPY
            rs_score = round((stock_change - spy_change) * 100, 2)

            # --- 3. STANDARD FILTERS ---
            rel_vol = today['Volume'] / df['Volume'].rolling(10).mean().iloc[-1]
            close_pos = (today['Close'] - today['Low']) / (today['High'] - today['Low'])

            # --- 4. COMBINED ALPHA STRATEGY ---
            # We want: Outperforming SPY + High Vol + Strong Close + NOT Exhausted
            if rs_score > 1.5 and rel_vol > 1.3 and close_pos > 0.80 and not is_exhausted:
                all_results.append({
                    "Ticker": symbol,
                    "RS_vs_SPY": rs_score,
                    "Vol_Quality": "Good" if not is_exhausted else "Exhausted",
                    "Win_Rate_%": 0, # Placeholder for backtest if needed
                    "Exp_Return_%": 0, # Placeholder
                    "Price": round(today['Close'], 2),
                    "Rel_Vol": round(rel_vol, 2),
                    "ATR_Multiple": round(todays_range / today['ATR'], 2)
                })
            
            time.sleep(0.1)
        except: continue

    return pd.DataFrame(all_results)

def send_alpha_email(df):
    if df.empty:
        content = "<h1>No Alpha-Leaders found. Market conditions suggest caution.</h1>"
        subject = "Market Report: Low Conviction"
    else:
        # Best of the best: Highest Relative Strength
        top_rs = df.sort_values(by="RS_vs_SPY", ascending=False).head(10)
        subject = f"Alpha Report: {len(df)} Relative Strength Leaders Found"
        
        content = f"""
        <html>
        <head>
        <style>
            table {{ border-collapse: collapse; width: 100%; font-family: sans-serif; }}
            th, td {{ text-align: left; padding: 8px; border-bottom: 1px solid #ddd; }}
            th {{ background-color: #1a237e; color: white; }}
            .rs {{ font-weight: bold; color: #2e7d32; }}
        </style>
        </head>
        <body>
            <h2>🔥 Top Relative Strength Leaders</h2>
            <p>These stocks are outperforming SPY without being overextended (ATR Filtered).</p>
            {top_rs.to_html(index=False)}
            <br>
            <p><i>Note: RS_vs_SPY shows how many percentage points the stock beat the market by today.</i></p>
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
    results = run_alpha_analyzer()
    print(f"Analysis complete. Found {len(results)} leaders.")
    send_alpha_email(results)
