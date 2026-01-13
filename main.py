import os
import time
from flask import Flask, request
import telebot
import google.generativeai as genai

# 1. SETUP KEYS
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHANNEL_ID = os.environ.get('TELEGRAM_CHAT_ID') 
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')

# Initialize Bots
bot = telebot.TeleBot(TELEGRAM_TOKEN)
genai.configure(api_key=GEMINI_KEY)

# SWITCHED TO 1.5-FLASH FOR BETTER FREE QUOTA
model = genai.GenerativeModel('gemini-1.5-flash')

app = Flask(__name__)

def get_ai_rating(data):
    """Retries 3 times if Google says 'Quota Exhausted'"""
    prompt = f"""
    Analyze this 'Aad-FX' trade: {data}
    1. Rate confluence 1-10.
    2. Give a 1-sentence 'Action Plan'.
    Keep it very brief.
    """
    for attempt in range(3):
        try:
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            if "429" in str(e):
                print(f"Quota hit, retrying in 5s... (Attempt {attempt+1})")
                time.sleep(5) 
                continue
            return f"AI Busy: {str(e)[:50]}"
    return "Rating Timeout - Check Chart"

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == 'POST':
        data = request.json
        
        # Get AI Analysis
        rating = get_ai_rating(data)
        
        # Professional Message Formatting
        msg = (
            f"🚀 *Aad-FX PREMIUM SIGNAL*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 *Asset:* {data.get('ticker', 'N/A')}\n"
            f"🎯 *Action:* {data.get('signal', 'N/A')}\n"
            f"💰 *Entry:* {data.get('price', 'N/A')}\n"
            f"📍 *SL:* {data.get('sl', 'N/A')}\n"
            f"🏁 *TP3:* {data.get('tp3', 'N/A')}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🧠 *AI ANALYSIS:*\n"
            f"{rating}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ *Trade at your own risk.*"
        )
        
        try:
            bot.send_message(CHANNEL_ID, msg, parse_mode='Markdown')
        except Exception as e:
            print(f"Telegram Error: {e}")
            
        return 'Success', 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
    
