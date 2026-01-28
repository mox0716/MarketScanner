import yfinance as yf
import pandas as pd
import numpy as np
import os
import time
import smtplib
from email.message import EmailMessage

def calculate_indicators(df):
    # Trend Strength (Simplified ADX)
    df['UpMove'] = df['High'] - df['High'].shift(1)
    df['DownMove'] = df['Low'].shift(1) - df['Low']
    df['+DM'] = np.where((df['UpMove'] > df['DownMove']) & (df['UpMove'] > 0), df['UpMove'], 0)
    df['-DM'] = np.where((df['DownMove'] > df['UpMove']) & (df['DownMove'] > 0), df['DownMove'], 0)
    df['TR'] = pd.concat([df['High']-df['Low'], abs(df['High']-df['Close'].shift()), abs(df['Low']-df['Close'].shift())], axis=1).max(axis=1)
    
    period = 14
    df['+DI'] = 100 * (df['+DM'].rolling(period).mean() / df['TR'].rolling(period).mean())
    df['DX'] = 100 * (abs(df['+DI'] - (100 * (df['-DM'].rolling(period).mean() / df['TR'].rolling(period).mean()))) / (df['+DI'] + (100 * (df['-DM'].rolling(period).mean() / df['TR'].rolling(period).mean()))))
    df['ADX'] = df['DX'].rolling(period).mean()
    
    # Moving Averages
    df['SMA10'] = df['Close'].rolling(10).mean()
    df['SMA20'] = df['Close'].rolling(20).mean()
    return df

def run_conviction_analyzer(ticker_file="tickers.txt"):
    if not os.path.exists(ticker_file): return pd.DataFrame()

    with open(ticker_file, 'r') as f:
        tickers = [line.strip().upper() for line in f if line.strip()]

    all_results = []

    for symbol in tickers:
        try:
            t = yf.Ticker(symbol)
            info = t.info
            
            # 1. BASE FILTERS
            mkt_cap = info.get('marketCap', 0)
            prev_close = info.get('previousClose', 0)
            if mkt_cap < 100_000_000 or prev_close < 1.00: continue

            df = t.history(period="250d")
            if len(df) < 50: continue

            # 2. LIQUIDITY FILTER
            avg_vol = df['Volume'].tail(30).mean()
            if avg_vol < 300_000: continue

            # 3. INDICATOR CALCULATIONS
            df = calculate_indicators(df)
            today = df.iloc[-1]
            
            # Setup: Price > SMA10 > SMA20 AND strong trend (ADX > 20)
            setup_condition = (df['Close'] > df['SMA10']) & (df['SMA10'] > df['SMA20']) & (df['ADX'] > 20)
            
            # 4. PROBABILITY BACKTEST (3-Day Window)
            # Find all days in the past where this setup occurred
            signals = df[setup_condition].index
            wins = 0
            total_signals = 0
            total_return = 0

            for date in signals:
                # We need at least 3 days of data after the signal to check the win
                idx = df.index.get_loc(date)
                if idx + 3 < len(df):
                    price_then = df.iloc[idx]['Close']
                    price_3d_later = df.iloc[idx + 3]['Close']
                    ret = (price_3d_later - price_then) / price_then
                    if ret > 0: wins += 1
                    total_return += ret
                    total_signals += 1

            win_rate = (wins / total_signals * 100) if total_signals > 0 else 0
            avg_3d_return = (total_return / total_signals * 100) if total_signals > 0 else 0

            # 5. FINAL TRIGGER (Is it active today?)
            if setup_condition.iloc[-1] and win_rate > 55:  # Only suggest if hist. win rate > 55%
                all_results.append({
                    "Ticker": symbol,
                    "Win_Rate_3D": round(win_rate, 1),
                    "Exp_Return_3D": round(avg_3d_return, 2),
                    "ADX_Strength": round(today['ADX'], 1),
                    "Price": round(today['Close'], 2),
                    "Stop_Loss": round(today['SMA20'], 2),
                    "Mkt_Cap_M": f"{mkt_cap/1e6:.1f}M"
                })
            
            time.sleep(0.05) 
        except: continue

    return pd.DataFrame(all_results)

def send_conviction_email(df):
    if df.empty:
        subject = "Swing Report: No High-Probability Setups"
        content = "No stocks met the 55%+ historical win rate criteria today."
    else:
        # THE FIX: Order by Win Rate, not price
        df_sorted = df.sort_values(by="Win_Rate_3D", ascending=False)
        subject = f"🎯 High-Probability Report: {len(df)} Swing Setups"
        content = f"""
        <html>
        <head>
        <style>
            table {{ border-collapse: collapse; width: 100%; font-family: sans-serif; font-size: 14px; }}
            th, td {{ text-align: left; padding: 12px; border-bottom: 1px solid #ddd; }}
            th {{ background-color: #283593; color: white; }}
            tr:hover {{ background-color: #f5f5f5; }}
            .high-win {{ color: #2e7d32; font-weight: bold; }}
        </style>
        </head>
        <body>
            <h2 style="color: #283593;">Top Quality 2-3 Day Swing Setups</h2>
            <p>Ordered by <b>Historical Win Rate</b>. These stocks have a proven track record of returning profit 3 days after this specific setup.</p>
            {df_sorted.to_html(index=False)}
            <br>
            <p><b>Exit Strategy:</b> Target the 'Exp_Return_3D' or exit after 72 hours. Exit immediately if price closes below 'Stop_Loss'.</p>
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
    results = run_conviction_analyzer()
    send_conviction_email(results)
