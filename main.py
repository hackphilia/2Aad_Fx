import os
import time
from flask import Flask, request
import telebot
from google import genai

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHANNEL_ID = os.environ.get('TELEGRAM_CHAT_ID')
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')

# Initialize Clients (2026 SDK)
bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_KEY)
MODEL_ID = "gemini-2.0-flash" # Stable 2026 Model

app = Flask(__name__)

# --- AI ANALYSIS WITH SMART RETRY ---
def get_ai_rating(data):
    """Retries with increasing wait times if Gemini is busy."""
    prompt = f"Analyze this Aad-FX signal: {data}. Give a 1-10 rating and a 1-sentence action plan."
    
    # Wait steps: 4s, 12s, 25s (to clear Google's 429 quota)
    for delay in [4, 12, 25]:
        try:
            response = client.models.generate_content(model=MODEL_ID, contents=prompt)
            return response.text
        except Exception as e:
            if "429" in str(e):
                print(f"AI Busy, retrying in {delay}s...")
                time.sleep(delay)
                continue
            return f"AI Logic Error: {str(e)[:30]}"
    return "AI Busy - Review Manually 💔"

# --- WEBHOOK ROUTE ---
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        
        # TYPE A: Target/Stop Loss Hits
        if "hit" in data:
            hit_msg = (
                f"🔔 *UPDATE: {data.get('ticker')}*\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🎯 *Result:* {data.get('hit')}\n"
                f"💰 *Price:* {data.get('price')}\n"
                f"━━━━━━━━━━━━━━━━━━"
            )
            bot.send_message(CHANNEL_ID, hit_msg, parse_mode='Markdown')
            return 'OK', 200

        # TYPE B: New Trade Signals
        ai_analysis = get_ai_rating(data)
        
        # Format "tf" to be human readable (e.g., 1h, 15m)
        tf = data.get('tf', 'N/A')
        
        msg = (
            f"🚀 *Aad-FX PREMIUM SIGNAL*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 *Asset:* {data.get('ticker')}\n"
            f"⏱️ *Timeframe:* {tf}\n"
            f"🎯 *Action:* {data.get('sig')}\n"
            f"💰 *Entry:* {data.get('price')}\n"
            f"📍 *SL:* {data.get('sl')}\n"
            f"🏁 *TPs:* {data.get('tp1')} | {data.get('tp2')} | {data.get('tp3')}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🧠 *AI ANALYSIS:*\n\n"
            f"{ai_analysis}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ *Trade at your own risk.*"
        )
        
        bot.send_message(CHANNEL_ID, msg, parse_mode='Markdown')
        return 'OK', 200

    except Exception as e:
        print(f"Webhook Error: {e}")
        return 'Error', 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
