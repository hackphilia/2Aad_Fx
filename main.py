import os
import time
from flask import Flask, request
import telebot
from google import genai

# --- 1. CONFIGURATION ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHANNEL_ID = os.environ.get('TELEGRAM_CHAT_ID')
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')

# Initialize Telegram & Google AI Client (2026 SDK)
bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_KEY)

app = Flask(__name__)

# --- 2. AI ANALYSIS FUNCTION ---
def get_ai_rating(data):
    """Sends trade data to Gemini 2.0 and returns analysis."""
    prompt = (
        f"Analyze this Aad-FX signal: {data}. "
        "Give a rating 1-10 and a 1-sentence action plan. "
        "Be concise and professional."
    )
    
    # Retry loop to handle 429 (Rate Limit) errors
    for attempt in range(3):
        try:
            # Use the stable 2.0-flash model for 2026
            response = client.models.generate_content(
                model="gemini-2.0-flash", 
                contents=prompt
            )
            return response.text
        except Exception as e:
            if "429" in str(e):
                time.sleep(5)
                continue
            return f"AI Analysis Unavailable ({str(e)[:30]})"
    return "AI Busy - Review Manually"

# --- 3. WEBHOOK ROUTE ---
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == 'POST':
        try:
            data = request.json
            
            # Get analysis from Gemini
            ai_analysis = get_ai_rating(data)
            
            # Build the Telegram Message
            msg = (
                f"🚀 *Aad-FX PREMIUM SIGNAL*\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📊 *Asset:* {data.get('ticker', 'N/A')}\n"
                f"⏱️ *Timeframe:* {data.get('tf', 'N/A')}\n"
                f"🎯 *Action:* {data.get('signal', 'N/A')}\n"
                f"💰 *Entry:* {data.get('price', 'N/A')}\n"
                f"📍 *SL:* {data.get('sl', 'N/A')}\n"
                f"🏁 *TP3:* {data.get('tp3', 'N/A')}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🧠 *AI ANALYSIS:*\n"
                f"{ai_analysis}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"⚠️ *Trade at your own risk.*"
            )
            
            bot.send_message(CHANNEL_ID, msg, parse_mode='Markdown')
            return 'OK', 200
            
        except Exception as e:
            print(f"Error: {e}")
            return 'Error', 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
