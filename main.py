import os
import time
from flask import Flask, request
import telebot
from google import genai

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHANNEL_ID = os.environ.get('TELEGRAM_CHAT_ID')
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')

# Initialize Clients
bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_KEY)

app = Flask(__name__)

# --- AI ANALYSIS WITH RETRY LOGIC ---
def get_ai_rating(data):
    """Retries with increasing wait times if Gemini is busy (429 error)."""
    prompt = (
        f"Analyze this Aad-FX signal: {data}. "
        "Give a rating 1-10 and a 1-sentence action plan. "
        "Be professional and concise."
    )
    
    # Wait times: 2s, 6s, 12s (Exponential Backoff)
    wait_times = [2, 6, 12]
    
    for delay in wait_times:
        try:
            # Using the stable 2026 model to avoid 404 errors
            response = client.models.generate_content(
                model="gemini-2.0-flash", 
                contents=prompt
            )
            return response.text
        except Exception as e:
            if "429" in str(e): # 'Resource Exhausted' / Busy
                print(f"Gemini busy, retrying in {delay}s...")
                time.sleep(delay)
                continue
            # If it's a 404 or other error, return the specific error
            return f"AI Analysis Error: {str(e)[:40]}"
            
    return "AI Busy - Review Signal Manually 💔"

# --- WEBHOOK ENDPOINT ---
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == 'POST':
        try:
            data = request.json
            print(f"Signal Received: {data}")

            # Get the AI Rating
            ai_analysis = get_ai_rating(data)

            # Construct the Telegram Message
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
