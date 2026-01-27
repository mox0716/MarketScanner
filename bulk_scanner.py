import yfinance as yf
import pandas as pd
import os
import time
import smtplib  # Added this
from email.message import EmailMessage  # Added this

def run_overnight_analyzer(ticker_file="tickers.txt"):
    if not os.path.exists(ticker_file):
        print(f"Error: {ticker_file} not found. Create it with one ticker per line.")
        return pd.DataFrame()

    with open(ticker_file, 'r') as f:
        tickers = [line.strip().upper() for line in f if line.strip()]

    recommendations = []

    for symbol in tickers:
        try:
            t = yf.Ticker(symbol)
            # 1. Float Filter (Looking for 'Light' stocks)
            shares_float = t.info.get('floatShares', 0)
            if shares_float > 500_000_000 or shares_float == 0:
                continue 

            # 2. Get 300 Days of Data
            df = t.history(period="300d")
            if len(df) < 50: continue

            # 3. Technical Calculations
            df['Rel_Vol'] = df['Volume'] / df['Volume'].rolling(10).mean()
            df['Day_Range'] = df['High'] - df['Low']
            df['Close_Pos'] = (df['Close'] - df['Low']) / df['Day_Range']
            
            # Probability of Gap Up Tomorrow
            df['Next_Open_Gap'] = (df['Open'].shift(-1) - df['Close']) / df['Close']
            
            # Define "The Setup" (High Vol + Strong Close)
            setup_condition = (df['Rel_Vol'] > 1.5) & (df['Close_Pos'] > 0.85)
            past_setups = df[setup_condition].dropna()
            
            win_rate = (len(past_setups[past_setups['Next_Open_Gap'] > 0]) / len(past_setups)) * 100 if len(past_setups) > 0 else 0
            
            # 4. Check if Today is a "Buy" Signal
            today = df.iloc[-1]
            if today['Rel_Vol'] > 1.5 and today['Close_Pos'] > 0.85:
                recommendations.append({
                    "Ticker": symbol,
                    "Rel_Vol": round(today['Rel_Vol'], 2),
                    "Historical_Win_Rate": f"{win_rate:.1f}%",
                    "Float_M": f"{shares_float/1e6:.1f}M",
                    "Price": round(today['Close'], 2)
                })
            
            time.sleep(0.1) # Respect API limits
        except Exception as e:
            continue

    return pd.DataFrame(recommendations)

def send_results_email(df_results, total_scanned):
    msg = EmailMessage()
    
    # Check if we have results or not
    if df_results.empty:
        content = f"Scan Complete. \n\nTotal Stocks Checked: {total_scanned}\nSignals Found: 0\n\nMarket conditions did not meet your strict technical criteria today. No trades recommended."
        msg['Subject'] = "Market Report: No Signals Found"
    else:
        content = f"Scan Complete. \nTotal Stocks Checked: {total_scanned}\n\nHigh-Probability Overnight Setups:\n\n" + df_results.to_string(index=False)
        msg['Subject'] = f"Market Report: {len(df_results)} Signals Found"

    msg.set_content(content)
    msg['From'] = os.environ.get('EMAIL_USER')
    msg['To'] = os.environ.get('EMAIL_RECEIVER')

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(os.environ.get('EMAIL_USER'), os.environ.get('EMAIL_PASS'))
            smtp.send_message(msg)
        print("Email sent successfully!")
    except Exception as e:
        print(f"Failed to send email: {e}")

if __name__ == "__main__":
    # Get the list of tickers to know the total count
    if not os.path.exists("tickers.txt"):
        print("tickers.txt missing.")
    else:
        with open("tickers.txt", 'r') as f:
            ticker_list = [line.strip() for line in f if line.strip()]
        
        print(f"Scanning {len(ticker_list)} tickers for overnight setups...")
        picks = run_overnight_analyzer()
        
        # Now passing the total count to the email function
        send_results_email(picks, len(ticker_list))
