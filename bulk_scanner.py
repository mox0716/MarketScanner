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
            # 1. Fundamental Filter
            info = t.info
            if info.get('floatShares', 0) > 500_000_000: continue

            df = t.history(period="300d")
            if len(df) < 50: continue

            # 2. Technical Indicators
            df['Rel_Vol'] = df['Volume'] / df['Volume'].rolling(10).mean()
            df['Day_Range'] = df['High'] - df['Low']
            df['Close_Pos'] = (df['Close'] - df['Low']) / df['Day_Range']
            df['SMA20'] = df['Close'].rolling(20).mean()
            df['Gap_Pct'] = (df['Open'].shift(-1) - df['Close']) / df['Close']

            # 3. Strategy Definitions
            s1 = (df['Rel_Vol'] > 1.5) & (df['Close_Pos'] > 0.85) # Power Hour
            s2 = (df['Close'] > df['SMA20']) & (df['Rel_Vol'] > 1.8) # Trend Break
            df['Signal'] = s1 | s2
            
            # 4. Backtest Metrics
            setups = df[df['Signal'] == True].dropna()
            if len(setups) < 3: continue 

            win_rate = (len(setups[setups['Gap_Pct'] > 0]) / len(setups)) * 100
            avg_gap = setups['Gap_Pct'].mean() * 100

            # 5. Check Today's Signal & Conviction
            today = df.iloc[-1]
            conviction_score = 0
            if s1.iloc[-1]: conviction_score += 1
            if s2.iloc[-1]: conviction_score += 1
            if today['Rel_Vol'] > 2.5: conviction_score += 1

            # Only proceed if we have at least one strategy signal
            if conviction_score >= 1:
                # RISK MANAGEMENT CALCS
                # SL: Today's Low (Standard for overnight holds)
                # TP: Close + (Expected Return * 1.2 for conservative target)
                sl_price = round(today['Low'], 2)
                tp_price = round(today['Close'] * (1 + (avg_gap / 100) * 1.2), 2)

                all_results.append({
                    "Ticker": symbol,
                    "Score": conviction_score,
                    "Win_Rate_%": round(win_rate, 1),
                    "Exp_Return_%": round(avg_gap, 2),
                    "Price": round(today['Close'], 2),
                    "Target_TP": tp_price,
                    "Stop_Loss": sl_price,
                    "Rel_Vol": round(today['Rel_Vol'], 2)
                })
            
            time.sleep(0.05) 
        except: continue

    return pd.DataFrame(all_results)

def send_pro_email(df):
    if df.empty:
        content = "<h1>No high-probability setups found today.</h1>"
        subject = "Market Report: Neutral"
    else:
        # Rank the Best of the Best
        top_safety = df.sort_values(by="Win_Rate_%", ascending=False).head(10)
        top_explosive = df.sort_values(by="Exp_Return_%", ascending=False).head(10)

        subject = f"Market Report: {len(df)} Active Signals"
        
        content = f"""
        <html>
        <head>
        <style>
            table {{ border-collapse: collapse; width: 100%; font-family: sans-serif; }}
            th, td {{ text-align: left; padding: 8px; border-bottom: 1px solid #ddd; }}
            th {{ background-color: #f2f2f2; }}
            .safety {{ color: #2e7d32; }}
            .explosive {{ color: #c62828; }}
        </style>
        </head>
        <body>
            <h2 class="safety">🛡️ Top 10 Safety Picks (Highest Probabilities)</h2>
            <p>Focus on these for consistent "Base Hits."</p>
            {top_safety.to_html(index=False)}
            
            <hr>
            
            <h2 class="explosive">🚀 Top 10 Explosive Picks (Highest Avg Returns)</h2>
            <p>Focus on these for high-volatility "Home Runs."</p>
            {top_explosive.to_html(index=False)}
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
    results = run_pro_analyzer()
    print(f"Found {len(results)} signals. Sending report...")
    send_pro_email(results)
