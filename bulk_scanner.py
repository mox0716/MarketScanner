import yfinance as yf
import pandas as pd
import numpy as np
import os
import time
import smtplib
from email.message import EmailMessage

def calculate_indicators(df):
    # ADX Calculation
    df['UpMove'] = df['High'] - df['High'].shift(1)
    df['DownMove'] = df['Low'].shift(1) - df['Low']
    df['+DM'] = np.where((df['UpMove'] > df['DownMove']) & (df['UpMove'] > 0), df['UpMove'], 0)
    df['-DM'] = np.where((df['DownMove'] > df['UpMove']) & (df['DownMove'] > 0), df['DownMove'], 0)
    df['TR'] = pd.concat([df['High']-df['Low'], abs(df['High']-df['Close'].shift()), abs(df['Low']-df['Close'].shift())], axis=1).max(axis=1)
    period = 14
    df['+DI'] = 100 * (df['+DM'].rolling(period).mean() / df['TR'].rolling(period).mean())
    df['-DI'] = 100 * (df['-DM'].rolling(period).mean() / df['TR'].rolling(period).mean())
    df['DX'] = 100 * (abs(df['+DI'] - df['-DI']) / (df['+DI'] + df['-DI']))
    df['ADX'] = df['DX'].rolling(period).mean()
    # Moving Averages
    df['SMA10'] = df['Close'].rolling(10).mean()
    df['SMA20'] = df['Close'].rolling(20).mean()
    return df

def get_market_tide():
    """Checks if SPY is above its 20-day SMA."""
    try:
        spy = yf.Ticker("SPY").history(period="50d")
        spy_sma20 = spy['Close'].rolling(window=20).mean().iloc[-1]
        current_spy = spy['Close'].iloc[-1]
        return current_spy >= spy_sma20
    except:
        return False # Err on the side of caution

def run_phenomenal_analyzer(ticker_file="tickers.txt"):
    if not os.path.exists(ticker_file): return pd.DataFrame()
    
    # --- MARKET TIDE CHECK ---
    market_is_healthy = get_market_tide()
    if not market_is_healthy:
        print("Market Tide is LOW (SPY below 20SMA). Scanning aborted to protect capital.")
        return pd.DataFrame()

    with open(ticker_file, 'r') as f:
        tickers = [line.strip().upper() for line in f if line.strip()]

    all_results = []
    repo_id = os.environ.get('GITHUB_REPOSITORY', 'MarketScanner-Main')

    for symbol in tickers:
        try:
            t = yf.Ticker(symbol)
            info = t.info
            mkt_cap = info.get('marketCap', 0)
            if mkt_cap < 100_000_000: continue

            df = t.history(period="250d")
            if len(df) < 50: continue

            # --- RELATIVE VOLUME CALCULATION ---
            today_vol = df['Volume'].iloc[-1]
            avg_vol_20d = df['Volume'].rolling(20).mean().iloc[-2] # Avg of previous 20 days
            rel_vol = today_vol / avg_vol_20d if avg_vol_20d > 0 else 0

            # Liquidity and Price Gates
            if avg_vol_20d < 300_000 or df['Close'].iloc[-1] < 1.00: continue

            df = calculate_indicators(df)
            today = df.iloc[-1]
            yesterday = df.iloc[-2]
            
            # --- THE SNIPER CRITERIA ---
            # 1. Trend: Price > SMA10 > SMA20
            # 2. Strength: ADX > 20 and RISING
            # 3. Gas: Relative Volume > 1.5 (50% more volume than usual)
            is_trending = (today['Close'] > today['SMA10'] > today['SMA20'])
            is_accelerating = (today['ADX'] > 20) and (today['ADX'] > yesterday['ADX'])
            has_volume = rel_vol >= 1.5

            if is_trending and is_accelerating and has_volume:
                # 4. Probability Backtest
                hist_signals = df[(df['Close'] > df['SMA10']) & (df['SMA10'] > df['SMA20']) & (df['ADX'] > 20) & (df['ADX'] > df['ADX'].shift(1))].index
                wins, total_signals, total_return = 0, 0, 0
                for date in hist_signals:
                    idx = df.index.get_loc(date)
                    if idx + 3 < len(df):
                        ret = (df.iloc[idx + 3]['Close'] - df.iloc[idx]['Close']) / df.iloc[idx]['Close']
                        if ret > 0: wins += 1
                        total_return += ret
                        total_signals += 1

                win_rate = (wins / total_signals * 100) if total_signals > 0 else 0
                avg_3d_return = (total_return / total_signals * 100) if total_signals > 0 else 0

                # --- PROFITABILITY FILTERS ---
                if win_rate > 55 and avg_3d_return >= 3.0:
                    price = round(today['Close'], 2)
                    all_results.append({
                        "ticker": symbol,
                        "win_rate_3d": f"{win_rate:.1f}%",
                        "exp_return_3d": f"{avg_3d_return:.2f}%",
                        "adx_strength": round(today['ADX'], 1),
                        "price": price,
                        "stop_loss": round(price * 0.99, 2),
                        "target_price": round(price * 1.03, 2),
                        "mkt_cap_m": f"{mkt_cap/1e6:.1f}M",
                        "rel_vol": round(rel_vol, 2)
                    })
            time.sleep(0.05)
        except: continue

    cols = ["ticker", "win_rate_3d", "exp_return_3d", "adx_strength", "price", "stop_loss", "target_price", "mkt_cap_m"]
    return pd.DataFrame(all_results, columns=cols)

def send_sniper_email(df):
    # (Same email logic as before, just sorting by win_rate_3d)
    if df.empty:
        subject = "Sniper Report: Market Tide Low or No Quality Setups"
        content = "Either SPY is weak or no stocks met the 3:1 + Volume requirements."
    else:
        df_sorted = df.sort_values(by="win_rate_3d", ascending=False)
        subject = f"🎯 SNIPER ALERT: {len(df)} High-Volume Plays"
        content = f"""
        <html>
        <body style="font-family: sans-serif;">
            <h2 style="color: #d32f2f;">Institutional Volume & Trend Setups</h2>
            <p>Criteria: <b>SPY Healthy</b> | <b>Rel Vol > 1.5</b> | <b>Exp Return > 3%</b></p>
            {df_sorted.to_html(index=False)}
        </body>
        </html>
        """
    # ... (Email sending code remains the same)
