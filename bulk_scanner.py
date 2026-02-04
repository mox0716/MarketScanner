import yfinance as yf
import pandas as pd
import numpy as np
import os
import time
import smtplib
from email.message import EmailMessage

def calculate_indicators(df):
    """Calculates ADX and Moving Averages for trend strength and direction."""
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
    """Returns True if SPY is healthy (above 20 SMA), else False + message."""
    try:
        spy = yf.Ticker("SPY").history(period="50d")
        if spy.empty: return True, "Proceeding: SPY data unavailable."
        spy_sma20 = spy['Close'].rolling(window=20).mean().iloc[-1]
        current_spy = spy['Close'].iloc[-1]
        
        if current_spy < spy_sma20:
            return False, f"Market Tide is LOW (SPY {current_spy:.2f} < SMA20 {spy_sma20:.2f})."
        return True, "Market Tide is Healthy."
    except Exception as e:
        return True, f"Proceeding: Tide check error ({e})."

def send_sniper_email(df, status_msg):
    """Sends a diagnostic email regardless of whether hits were found."""
    msg = EmailMessage()
    user = os.environ.get('EMAIL_USER')
    password = os.environ.get('EMAIL_PASS')
    receiver = os.environ.get('EMAIL_RECEIVER')
    repo = os.environ.get('GITHUB_REPOSITORY', 'MarketScanner-Main')

    if df.empty:
        subject = "⚪ Scanner Report: Zero Hits"
        header_color = "#555555"
        table_html = "<p>No stocks met the 3% Return / 1.5x Volume / Rising ADX criteria today.</p>"
    else:
        subject = f"🎯 Sniper Alert: {len(df)} High-Conviction Setups"
        header_color = "#1a237e"
        table_html = df.to_html(index=False, justify='left')

    content = f"""
    <html>
    <body style="font-family: sans-serif; color: #333;">
        <h2 style="color: {header_color};">3:1 Sniper Trading Report</h2>
        <p><b>System Status:</b> {status_msg}</p>
        <hr size="1" color="#ddd">
        {table_html}
        <br>
        <p style="font-size: 11px; color: #888;">
            <b>Parameters:</b> 3:1 Reward/Risk | Target: 1.03 | Stop: 0.99 | Min Win Rate: 55%<br>
            <b>Source:</b> {repo}
        </p>
    </body>
    </html>
    """
    
    msg.add_alternative(content, subtype='html')
    msg['Subject'] = subject
    msg['From'] = user
    msg['To'] = receiver

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
        print("Email sent successfully.")
    except Exception as e:
        print(f"Email failed: {e}")

def run_main():
    ticker_file = "tickers.txt"
    all_results = []
    
    # 1. Market Tide Check (Logic requested: we can keep it active or comment the 'return' to ignore)
    tide_ok, tide_status = get_market_tide()
    # To bypass Tide check, comment out the next 2 lines:
    # if not tide_ok:
    #    send_sniper_email(pd.DataFrame(), tide_status)
    #    return

    if not os.path.exists(ticker_file):
        send_sniper_email(pd.DataFrame(), f"Error: {ticker_file} not found in repository.")
        return

    with open(ticker_file, 'r') as f:
        tickers = [line.strip().upper() for line in f if line.strip()]

    print(f"Starting optimized scan for {len(tickers)} symbols...")

    for symbol in tickers:
        try:
            t = yf.Ticker(symbol)
            
            # --- FAST FILTER 1: Mkt Cap & Price ---
            # Using t.info is slower but necessary for Cap/Price without history
            info = t.info
            mkt_cap = info.get('marketCap', 0)
            price = info.get('currentPrice') or info.get('regularMarketPrice') or 0
            
            if mkt_cap < 100_000_000 or price < 1.00:
                continue

            # --- FAST FILTER 2: 20-Day Volume ---
            # Fetching only what we need to verify volume gas
            vol_df = t.history(period="21d") # 21 days to get 20d avg + current
            if len(vol_df) < 20: continue
            
            avg_vol_20d = vol_df['Volume'].iloc[:-1].mean()
            today_vol = vol_df['Volume'].iloc[-1]
            rel_vol = today_vol / avg_vol_20d if avg_vol_20d > 0 else 0
            
            if avg_vol_20d < 300_000 or rel_vol < 1.5:
                continue

            # --- DEEP SCAN: 250-Day History ---
            print(f"Hit Gate: {symbol} - RelVol: {rel_vol:.2f}. Running deep scan...")
            df = t.history(period="250d")
            df = calculate_indicators(df)
            
            today = df.iloc[-1]
            yesterday = df.iloc[-2]
            
            # Trend and Acceleration
            is_trending = (today['Close'] > today['SMA10'] > today['SMA20'])
            is_accelerating = (today['ADX'] > 20) and (today['ADX'] > yesterday['ADX'])

            if is_trending and is_accelerating:
                # 3-Day Probability Backtest
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

                # --- 3:1 SNIPER PROFITABILITY FILTER ---
                if win_rate >= 55 and avg_3d_return >= 3.0:
                    all_results.append({
                        "ticker": symbol, 
                        "win_rate_3d": f"{win_rate:.1f}%",
                        "exp_return_3d": f"{avg_3d_return:.2f}%", 
                        "adx": round(today['ADX'], 1),
                        "price": round(price, 2), 
                        "stop_loss": round(price * 0.99, 2),
                        "target_price": round(price * 1.03, 2),
                        "rel_vol": round(rel_vol, 2)
                    })
            
            time.sleep(0.05) # Prevent rate limiting
        except:
            continue

    # Final Execution
    results_df = pd.DataFrame(all_results)
    send_sniper_email(results_df, tide_status)

if __name__ == "__main__":
    run_main()
