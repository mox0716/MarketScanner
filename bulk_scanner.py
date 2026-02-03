import yfinance as yf
import pandas as pd
import numpy as np
import os
import time
import smtplib
from email.message import EmailMessage

def calculate_indicators(df):
    # 1. Calculate True Range and Directional Movement
    df['UpMove'] = df['High'] - df['High'].shift(1)
    df['DownMove'] = df['Low'].shift(1) - df['Low']
    df['+DM'] = np.where((df['UpMove'] > df['DownMove']) & (df['UpMove'] > 0), df['UpMove'], 0)
    df['-DM'] = np.where((df['DownMove'] > df['UpMove']) & (df['DownMove'] > 0), df['DownMove'], 0)
    df['TR'] = pd.concat([df['High']-df['Low'], abs(df['High']-df['Close'].shift()), abs(df['Low']-df['Close'].shift())], axis=1).max(axis=1)
    
    period = 14
    # 2. Smooth the indicators
    df['+DI'] = 100 * (df['+DM'].rolling(period).mean() / df['TR'].rolling(period).mean())
    df['-DI'] = 100 * (df['-DM'].rolling(period).mean() / df['TR'].rolling(period).mean())
    df['DX'] = 100 * (abs(df['+DI'] - df['-DI']) / (df['+DI'] + df['-DI']))
    df['ADX'] = df['DX'].rolling(period).mean()
    
    # 3. Moving Averages
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
            
            # --- BASE FILTERS ---
            mkt_cap = info.get('marketCap', 0)
            prev_close = info.get('previousClose', 0)
            if mkt_cap < 100_000_000 or prev_close < 1.00: continue

            df = t.history(period="250d")
            if len(df) < 50: continue

            # --- LIQUIDITY FILTER ---
            avg_vol = df['Volume'].tail(30).mean()
            if avg_vol < 300_000: continue

            # --- INDICATOR CALCULATIONS ---
            df = calculate_indicators(df)
            today = df.iloc[-1]
            yesterday = df.iloc[-2]
            
            # --- THE "RISING ALPHA" CONDITION ---
            # 1. Price > SMA10 > SMA20 (Upward trend)
            # 2. ADX > 20 (Strength is present)
            # 3. ADX Today > ADX Yesterday (Strength is INCREASING)
            is_trending = (today['Close'] > today['SMA10']) & (today['SMA10'] > today['SMA20'])
            is_strong = today['ADX'] > 20
            is_accelerating = today['ADX'] > yesterday['ADX']

            setup_active = is_trending and is_strong and is_accelerating
            
            # --- PROBABILITY BACKTEST ---
            # We look back at the last year to see how this EXACT setup performed
            # (Matches: Trend + Strength + Acceleration)
            hist_signals = df[(df['Close'] > df['SMA10']) & 
                              (df['SMA10'] > df['SMA20']) & 
                              (df['ADX'] > 20) & 
                              (df['ADX'] > df['ADX'].shift(1))].index
            
            wins, total_signals, total_return = 0, 0, 0

            for date in hist_signals:
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

            # --- FINAL OUTPUT ---
            if setup_active and win_rate > 55:
                current_price = round(today['Close'], 2)
                target_price = round(current_price * (1 + (avg_3d_return / 100)), 2)

                all_results.append({
                    "ticker": symbol,
                    "win_rate_3d": f"{win_rate:.1f}%",
                    "exp_return_3d": f"{avg_3d_return:.2f}%",
                    "adx_strength": round(today['ADX'], 1),
                    "price": current_price,
                    "stop_loss": round(today['SMA20'], 2),
                    "target_price": target_price,
                    "mkt_cap_m": f"{mkt_cap/1e6:.1f}M"
                })
            
            time.sleep(0.05) 
        except: continue

    # Exact Column Order
    columns_order = ["ticker", "win_rate_3d", "exp_return_3d", "adx_strength", "price", "stop_loss", "target_price", "mkt_cap_m"]
    return pd.DataFrame(all_results, columns=columns_order)

def send_conviction_email(df):
    if df.empty:
        subject = "Swing Report: No Accelerating Setups"
        content = "No stocks met the Rising ADX and 55% win rate criteria today."
    else:
        df_sorted = df.sort_values(by="win_rate_3d", ascending=False)
        subject = f"🚀 Momentum Report: {len(df)} Rising Setups"
        content = f"""
        <html>
        <head>
        <style>
            table {{ border-collapse: collapse; width: 100%; font-family: sans-serif; font-size: 13px; }}
            th, td {{ text-align: left; padding: 10px; border-bottom: 1px solid #ddd; }}
            th {{ background-color: #004d40; color: white; text-transform: uppercase; }}
            tr:nth-child(even) {{ background-color: #f2f2f2; }}
            .ticker-cell {{ font-weight: bold; color: #004d40; }}
        </style>
        </head>
        <body>
            <h2 style="color: #004d40;">Accelerating 3-Day Swing Targets</h2>
            <p>Criteria: <b>ADX > 20 and Rising</b>. This filters for trends that are actively gaining strength.</p>
            {df_sorted.to_html(index=False, classes='ticker-cell')}
            <br>
            <p><b>Execution:</b> Set sell orders at <b>target_price</b> and stop-loss at <b>stop_loss</b>.</p>
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
