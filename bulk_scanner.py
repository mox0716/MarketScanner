import yfinance as yf
import pandas as pd
import numpy as np
import os
import time
import smtplib
from email.message import EmailMessage

def calculate_indicators(df):
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
    df['SMA10'] = df['Close'].rolling(10).mean()
    df['SMA20'] = df['Close'].rolling(20).mean()
    return df

def get_market_tide():
    try:
        spy = yf.Ticker("SPY").history(period="50d")
        if spy.empty: return True, "Caution: SPY data missing, proceeding anyway."
        spy_sma20 = spy['Close'].rolling(window=20).mean().iloc[-1]
        current_spy = spy['Close'].iloc[-1]
        if current_spy < spy_sma20:
            return False, f"Market Tide is LOW (SPY {current_spy:.2f} < SMA20 {spy_sma20:.2f})."
        return True, "Market Tide is Healthy."
    except:
        return True, "Market Tide check failed, proceeding by default."

def run_phenomenal_analyzer(ticker_file="tickers.txt"):
    all_results = []
    
    # 1. Market Tide Check
    tide_ok, tide_msg = get_market_tide()
    if not tide_ok:
        return pd.DataFrame(), tide_msg

    if not os.path.exists(ticker_file):
        return pd.DataFrame(), f"Error: {ticker_file} not found."

    with open(ticker_file, 'r') as f:
        tickers = [line.strip().upper() for line in f if line.strip()]

    print(f"Scanning {len(tickers)} tickers...")
    
    for symbol in tickers:
        try:
            t = yf.Ticker(symbol)
            # --- FAST FILTERING ---
            info = t.info
            mkt_cap = info.get('marketCap', 0)
            price = info.get('currentPrice') or info.get('regularMarketPrice') or 0
            
            if mkt_cap < 100_000_000 or price < 1.00:
                continue

            # --- VOLUME GATE ---
            vol_df = t.history(period="20d")
            avg_vol = vol_df['Volume'].mean()
            if avg_vol < 300_000:
                continue

            # --- DEEP SCAN & BACKTEST ---
            df = t.history(period="250d")
            df = calculate_indicators(df)
            today = df.iloc[-1]
            yesterday = df.iloc[-2]
            
            # Relative Volume
            rel_vol = today['Volume'] / vol_df['Volume'].iloc[:-1].mean()

            # The Strategy
            is_trending = (today['Close'] > today['SMA10'] > today['SMA20'])
            is_accelerating = (today['ADX'] > 20) and (today['ADX'] > yesterday['ADX'])
            
            if is_trending and is_accelerating and rel_vol >= 1.5:
                # 3-Day Backtest
                hist_signals = df[(df['Close'] > df['SMA10']) & (df['SMA10'] > df['SMA20']) & 
                                  (df['ADX'] > 20) & (df['ADX'] > df['ADX'].shift(1))].index
                
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

                if win_rate > 55 and avg_3d_return >= 3.0:
                    all_results.append({
                        "ticker": symbol, "win_rate_3d": f"{win_rate:.1f}%",
                        "exp_return_3d": f"{avg_3d_return:.2f}%", "adx_strength": round(today['ADX'], 1),
                        "price": round(price, 2), "stop_loss": round(price * 0.99, 2),
                        "target_price": round(price * 1.03, 2), "mkt_cap_m": f"{mkt_cap/1e6:.1f}M"
                    })
            time.sleep(0.01)
        except: continue

    final_msg = tide_msg if all_results else "Tide was OK, but no stocks met the 3:1 Volume/Trend criteria."
    return pd.DataFrame(all_results), final_msg

def send_sniper_email(df, status_msg):
    msg = EmailMessage()
    repo = os.environ.get('GITHUB_REPOSITORY', 'MarketScanner')
    
    if df.empty:
        subject = "⚪ Scanner Report: Zero Hits"
        body = f"""<html><body>
                   <h2 style='color: #555;'>No Setups Found</h2>
                   <p><b>Status:</b> {status_msg}</p>
                   <p>Source: {repo}</p>
                   </body></html>"""
    else:
        subject = f"🎯 Sniper Alert: {len(df)} Setups Found"
        body = f"""<html><body>
                   <h2 style='color: #1a237e;'>Qualified 3:1 Swing Setups</h2>
                   <p><b>Status:</b> {status_msg}</p>
                   {df.to_html(index=False)}
                   </body></html>"""

    msg.add_alternative(body, subtype='html')
    msg['Subject'] = subject
    # ... (rest of your SMTP login code) ...
