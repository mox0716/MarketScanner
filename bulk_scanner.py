import yfinance as yf
import pandas as pd
import numpy as np
import os
import time
import smtplib
from email.message import EmailMessage

# --- DEBUGGING LOG ---
def log(msg):
    print(f"[LOG] {msg}")

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

def run_debug_analyzer(ticker_file="tickers.txt"):
    if not os.path.exists(ticker_file):
        log(f"ERROR: {ticker_file} not found. Check filename casing.")
        return pd.DataFrame()

    # --- MARKET TIDE BYPASS ---
    log("MARKET TIDE CHECK: BYPASSED for debugging.")
    
    with open(ticker_file, 'r') as f:
        tickers = [line.strip().upper() for line in f if line.strip()]

    log(f"Loaded {len(tickers)} tickers. Beginning scan...")
    all_results = []

    for i, symbol in enumerate(tickers):
        # Progress update every 100 tickers
        if i % 100 == 0: log(f"Processing: {i}/{len(tickers)}...")
        
        try:
            t = yf.Ticker(symbol)
            df = t.history(period="250d")
            
            if df.empty or len(df) < 50:
                continue

            # 1. Volume & Cap Check
            today_vol = df['Volume'].iloc[-1]
            avg_vol_20d = df['Volume'].rolling(20).mean().iloc[-2]
            rel_vol = today_vol / avg_vol_20d if avg_vol_20d > 0 else 0
            
            if avg_vol_20d < 300_000: continue

            # 2. Indicators
            df = calculate_indicators(df)
            today = df.iloc[-1]
            yesterday = df.iloc[-2]
            
            # 3. The Filter Stack
            is_trending = (today['Close'] > today['SMA10'] > today['SMA20'])
            is_accelerating = (today['ADX'] > 20) and (today['ADX'] > yesterday['ADX'])
            has_volume = rel_vol >= 1.5

            if is_trending and is_accelerating and has_volume:
                log(f"HIT FOUND: {symbol} (RelVol: {rel_vol:.2f})")
                
                # Probability Backtest
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

                if win_rate > 55 and avg_3d_return >= 3.0:
                    price = round(today['Close'], 2)
                    all_results.append({
                        "ticker": symbol, "win_rate_3d": f"{win_rate:.1f}%",
                        "exp_return_3d": f"{avg_3d_return:.2f}%", "adx_strength": round(today['ADX'], 1),
                        "price": price, "stop_loss": round(price * 0.99, 2),
                        "target_price": round(price * 1.03, 2), "rel_vol": round(rel_vol, 2)
                    })
            
            # Tiny sleep to prevent YFinance rate limiting
            time.sleep(0.02)
        except Exception as e:
            continue

    log(f"Scan complete. Found {len(all_results)} qualified setups.")
    return pd.DataFrame(all_results)

# ... (Keep the send_email function from previous version) ...

if __name__ == "__main__":
    results = run_debug_analyzer()
    if not results.empty:
        # send_email(results)
        print(results.to_string())
    else:
        log("No qualified tickers found after full scan.")
