import os
from flask import Flask, request
import telebot
from groq import Groq

# --- CONFIG ---
bot = telebot.TeleBot(os.environ.get('TELEGRAM_TOKEN'))
CHANNEL_ID = os.environ.get('TELEGRAM_CHAT_ID')
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

app = Flask(__name__)

def get_ai_analysis(data):
    strat = data.get('strat', 'Unknown')
    ticker = data.get('ticker')
    tf = data.get('tf', 'N/A')
    
    # Prompt enforcing your 80%/70% win-rate strategy
    prompt = f"""
    Analyze this {strat} trade on {ticker} ({tf}).
    Rules: 
    - Triangle Breakout/Breakdown = 80% Win Probability.
    - Range Trade = 70% Win Probability.
    - Scalp = 45% Win Probability.
    Output format: State 'Win Probability: X%' followed by one professional sentence on entry logic.
    """
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}]
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"Groq Error: {e}")
        return "AI Analysis: Market Volatility High (Review Manually)"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        if not data: return 'No Data', 400

        # 1. Handle "MOVED TO BE" Text
        if data.get("status") == "MOVED TO BE":
            msg = f"🛡️ *UPDATE: {data.get('ticker')}*\n📍 Price reached safety zone. *SL MOVED TO BE!*"
            bot.send_message(CHANNEL_ID, msg, parse_mode='Markdown')
            return 'OK', 200
        
        # 2. Handle TP/SL Hits
        if "hit" in data:
            msg = f"🔔 *RESULT: {data.get('ticker')}*\n{data.get('hit')}"
            bot.send_message(CHANNEL_ID, msg, parse_mode='Markdown')
            return 'OK', 200

        # 3. New Signal with all 3 TPs
        ai_result = get_ai_analysis(data)
        
        # We pull tp1, tp2, and tp3 directly from your script's JSON
        msg = (
            f"🚀 *Aad-FX PREMIUM SIGNAL*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 Asset: {data.get('ticker')}\n"
            f"🛠️ Strategy: {data.get('strat')}\n"
            f"⏱️ Timeframe: {data.get('tf', 'N/A')}\n"
            f"🎯 Action: {data.get('sig')}\n"
            f"💰 Entry: {data.get('price')}\n"
            f"📍 SL: {data.get('sl')}\n"
            f"✅ *TP1:* {data.get('tp1')}\n"
            f"🔵 *TP2:* {data.get('tp2')}\n"
            f"🔥 *TP3:* {data.get('tp3')}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🧠 *AI ANALYSIS:*\n{ai_result}\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        bot.send_message(CHANNEL_ID, msg, parse_mode='Markdown')
        return 'OK', 200
    except Exception as e:
        print(f"Webhook Error: {e}")
        return 'Error', 500

if __name__ == '__main__':
    # Render handles the PORT
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
