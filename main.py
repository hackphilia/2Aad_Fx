import os
from flask import Flask, request
import telebot
import google.generativeai as genai

# 1. SETUP KEYS (Get these from your environment variables)
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')

# Initialize Bots
bot = telebot.TeleBot(TELEGRAM_TOKEN)
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

app = Flask(__name__)

def get_ai_rating(data):
    # This prompt tells the AI how to rate your specific Aad-FX logic
    prompt = f"""
    You are a professional trading analyst. Rate this trade setup from 1-10.
    Data: {data}
    
    Rules for Rating:
    - Range Rejection: Higher if RSI > 70 (Sell) or < 30 (Buy).
    - Triangle Breakout: Only high if Volume is High. 
    - Scalping: Penalize if Risk/Reward is less than 1:1.
    Provide a 2-sentence reasoning.
    """
    response = model.generate_content(prompt)
    return response.text

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == 'POST':
        data = request.json
        # 1. Get AI Rating
        rating = get_ai_rating(data)
        
        # 2. Format Telegram Message
        msg = f"🔔 *NEW SIGNAL: {data.get('ticker')}*\n"
        msg += f"Signal: {data.get('signal')}\n"
        msg += f"Rating: {rating}"
        
        # 3. Send to Telegram
        bot.send_message(CHAT_ID, msg, parse_mode='Markdown')
        return 'Success', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
