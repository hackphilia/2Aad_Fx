import os
import time
from flask import Flask, request
import telebot
from openai import OpenAI

# --- 1. CONFIGURATION ---
bot = telebot.TeleBot(os.environ.get('TELEGRAM_TOKEN'))
CHANNEL_ID = os.environ.get('TELEGRAM_CHAT_ID')

# DeepSeek uses the OpenAI format
client = OpenAI(
    api_key=os.environ.get('DEEPSEEK_API_KEY'), 
    base_url="https://api.deepseek.com"
)

app = Flask(__name__)

# --- 2. DEEPSEEK ANALYSIS ENGINE ---
def get_ai_analysis(data):
    """Analyzes trade with 80%/70% bias logic using DeepSeek."""
    strat = data.get('strat', 'Unknown')
    ticker = data.get('ticker')
    
    prompt = f"""
    Analyze this {strat} trade on {ticker}. 
    Rules: 
    1. If it's a Triangle Breakout, Win Probability is 80%.
    2. If it's a Range trade, Win Probability is 70%.
    3. For Scalps, Win Probability is 45%.
    Output: State the Win Probability % clearly and give a 1-sentence professional logic for the entry.
    """
    
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are a professional Forex/Crypto analyst bot."},
                {"role": "user", "content": prompt},
            ],
            stream=False
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"DeepSeek Error: {e}")
        return "AI Analysis Temporarily Offline"

# --- 3. WEBHOOK ROUTE ---
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        if not data: return 'No Data', 400

        # CASE A: BREAK-EVEN (BE) ALERTS
        if data.get("status") == "MOVED TO BE":
            be_msg = (
                f"🛡️ *TRADE ADVISORY: {data.get('ticker')}*\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"✅ Price reached the Safety Zone.\n"
                f"📍 *ACTION:* MOVED SL TO BREAK-EVEN (BE)!\n"
                f"💰 Current Price: {data.get('price')}\n"
                f"━━━━━━━━━━━━━━━━━━"
            )
            bot.send_message(CHANNEL_ID, be_msg, parse_mode='Markdown')
            return 'OK', 200

        # CASE B: TARGET/STOP LOSS HITS
        if "hit" in data:
            hit_msg = f"🔔 *UPDATE:* {data.get('ticker')} - {data.get('hit')} at {data.get('price')}"
            bot.send_message(CHANNEL_ID, hit_msg, parse_mode='Markdown')
            return 'OK', 200

        # CASE C: NEW SIGNALS
        ai_result = get_ai_analysis(data)
        
        msg = (
            f"🚀 *Aad-FX PREMIUM SIGNAL*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 *Asset:* {data.get('ticker')}\n"
            f"🛠️ *Strategy:* {data.get('strat')}\n"
            f"🎯 *Action:* {data.get('sig')}\n"
            f"💰 *Entry:* {data.get('price')}\n"
            f"📍 *SL:* {data.get('sl')} | *TP1:* {data.get('tp1')}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🧠 *DEEPSEEK AI ANALYSIS:*\n{ai_result}\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        bot.send_message(CHANNEL_ID, msg, parse_mode='Markdown')
        return 'OK', 200

    except Exception as e:
        print(f"Error: {e}")
        return 'Error', 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
