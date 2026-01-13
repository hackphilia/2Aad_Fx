import os
import time
import logging
from flask import Flask, request
import telebot
from google import genai
from google.genai import types

# --- 1. CONFIGURATION ---
# Ensure these are set in your Render "Environment Variables"
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHANNEL_ID = os.environ.get('TELEGRAM_CHAT_ID')
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')

# Initialize clients
bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_KEY)

# Stable 2026 Model ID
MODEL_ID = "gemini-2.0-flash" 

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# --- 2. AI ANALYSIS WITH RETRY LOGIC ---
def get_ai_rating(data):
    """
    Retries with Exponential Backoff if Gemini returns a 429 (Busy).
    Maximum wait time is 60 seconds to satisfy Free Tier limits.
    """
    prompt = (
        f"Analyze this {data.get('strat', 'Trade')} signal on {data.get('ticker')}. "
        f"Action: {data.get('sig')}, Timeframe: {data.get('tf')}, Price: {data.get('price')}. "
        "Rate 1-10 and give a 1-sentence action plan."
    )
    
    # Retry delays: 5s, 15s, 40s (Totaling ~60s of patience)
    retry_delays = [5, 15, 40]
    
    for delay in retry_delays:
        try:
            # Using the latest SDK syntax for 2026
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=prompt
            )
            return response.text
        except Exception as e:
            if "429" in str(e): # 'Resource Exhausted' / Rate Limit Hit
                logging.warning(f"Gemini Busy (429). Retrying in {delay}s...")
                time.sleep(delay)
                continue
            logging.error(f"AI Error: {e}")
            return f"AI Logic Error: {str(e)[:40]}"
            
    return "AI Busy - Review Signal Manually 💔"

# --- 3. WEBHOOK ENDPOINT ---
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        if not data:
            return 'No Data', 400

        # CASE A: TARGET/STOP LOSS HITS (Emoji Alerts)
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

        # CASE B: NEW TRADE SIGNALS
        # This triggers the AI analysis with the retry loop
        ai_analysis = get_ai_rating(data)
        
        # Format "tf" safely
        tf = data.get('tf', 'N/A')
        
        msg = (
            f"🚀 *Aad-FX PREMIUM SIGNAL*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 *Asset:* {data.get('ticker')}\n"
            f"🛠️ *Strategy:* {data.get('strat', 'Multi-Strategy')}\n"
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
        logging.error(f"Webhook processing failed: {e}")
        return 'Error', 500

if __name__ == '__main__':
    # Bind to PORT provided by Render
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
