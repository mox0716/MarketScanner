import yfinance as yf
import pandas as pd
import os
import time
import smtplib
from email.message import EmailMessage

def run_pro_analyzer(ticker_file="tickers.txt"):
    if not os.path.exists(ticker_file):
        return pd.DataFrame()

    with open(ticker_file, 'r') as f:
        tickers = [line.strip().upper() for line in f if line.strip()]

    all_results = []

    for symbol in tickers:
        try:
            t = yf.Ticker(symbol)
            # Fundamental Filter: Keep it under 500M float for movement
            info = t.info
            if info.get('floatShares', 0) > 500_000_000: continue

            df = t.history(period="300d")
            if len(df) < 50: continue

            # --- Technical Indicators ---
            df['Rel_Vol'] = df['Volume'] / df['Volume'].rolling(10).mean()
            df['Day_Range'] = df['High'] - df['Low']
            df['Close_Pos'] = (df['Close'] - df['Low']) / df['Day_Range']
            df['SMA20'] = df['Close'].rolling(20).mean()
            df['Gap_Pct'] = (df['Open'].shift(-1) - df['Close']) / df['Close']

            # --- Strategy Definitions ---
            # S1: Power Hour (High Vol + Strong Close)
            s1 = (df['Rel_Vol'] > 1.5) & (df['Close_Pos'] > 0.85)
            # S2: Trend Break (Price cross SMA20 + Vol)
            s2 = (df['Close'] > df['SMA20']) & (df['Rel_Vol'] > 1.8)
            
            df['Signal'] = s1 | s2
            
            # --- Backtest ---
            setups = df[df['Signal'] == True].dropna()
            if len(setups) < 3: continue 

            win_rate = (len(setups[setups['Gap_Pct'] > 0]) / len(setups)) * 100
            avg_gap = setups['Gap_Pct'].mean() * 100

            # --- Check Today's Signal ---
            today = df.iloc[-1]
            if today['Rel_Vol'] > 1.2 and today['Close_Pos'] > 0.70:
                all_results.append({
                    "Ticker": symbol,
                    "Win_Rate": round(win_rate, 1),
                    "Expected_Return": round(avg_gap, 2),
                    "Rel_Vol": round(today['Rel_Vol'], 2),
                    "Price": round(today['Close'], 2)
                })
            
            time.sleep(0.05) # Optimized for 1000 tickers
        except: continue

    return pd.DataFrame(all_results)

def send_pro_email(df):
    if df.empty:
        content = "<h1>No high-probability setups found today.</h1>"
        subject = "Market Report: Neutral"
    else:
        # Rank the Top 10s
        top_safety = df.sort_values(by="Win_Rate", ascending=False).head(10)
        top_explosive = df.sort_values(by="Expected_Return", ascending=False).head(10)

        subject = f"Market Report: {len(df)} Active Signals"
        
        # Build HTML Tables
        content = f"""
        <html>
        <body>
            <h2 style="color: #2e7d32;">Top 10 Safety Picks (Highest Win Rate)</h2>
            {top_safety.to_html(index=False)}
            
            <h2 style="color: #c62828;">Top 10 Explosive Picks (Highest Avg Gap)</h2>
            {top_explosive.to_html(index=False)}
        </body>
        </html>
        """

    msg = EmailMessage()
    msg.set_content(content) # Fallback for non-HTML clients
    msg.add_alternative(content, subtype='html')
    msg['Subject'] = subject
    msg['From'] = os.environ.get('EMAIL_USER')
    msg['To'] = os.environ.get('EMAIL_RECEIVER')

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(os.environ.get('EMAIL_USER'), os.environ.get('EMAIL_PASS'))
        smtp.send_message(msg)

if __name__ == "__main__":
    results = run_pro_analyzer()
    with open("tickers.txt", 'r') as f:
        total = len([l for l in f if l.strip()])
    print(f"Scanned {total} tickers. Found {len(results)} signals.")
    send_pro_email(results)
