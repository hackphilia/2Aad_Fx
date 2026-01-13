import os
from flask import Flask, request
import telebot
from google import genai

# 1. SETUP KEYS
# These are pulled from your Render Environment Variables
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHANNEL_ID = os.environ.get('TELEGRAM_CHAT_ID') # Must start with -100
GEMINI_KEY = os.environ.get('GEMINI_API_KEY')

# Initialize Clients
bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_KEY)

app = Flask(__name__)

def get_ai_rating(data):
    """Asks Gemini to analyze the trade based on your Aad-FX logic."""
    prompt = f"""
    Analyze this 'Aad-FX' Trading Signal:
    Asset: {data.get('ticker')}
    Action: {data.get('signal')}
    Price: {data.get('price')}
    RSI: {data.get('rsi')}
    Volume: {data.get('volume')}
    
    Tasks:
    1. Rate confluence 1-10 (e.g., 8.5/10).
    2. Give a 1-sentence 'Action Plan' (e.g., 'Wait for a retest of the breakout line').
    3. Keep it brief and professional.
    """
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash", 
            contents=prompt
        )
        return response.text
    except Exception as e:
        return f"Rating unavailable (Error: {str(e)})"

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == 'POST':
        data = request.json
        
        # Get the AI's thoughts
        ai_analysis = get_ai_rating(data)
        
        # Format the Final Message for your Channel
        msg = (
            f"🚀 *Aad-FX PREMIUM SIGNAL*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 *Asset:* {data.get('ticker')}\n"
            f"🎯 *Action:* {data.get('signal')}\n"
            f"💰 *Entry:* {data.get('price')}\n"
            f"📍 *SL:* {data.get('sl')}\n"
            f"🏁 *TP3:* {data.get('tp3')}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🧠 *AI ANALYSIS:*\n"
            f"{ai_analysis}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ *Trade at your own risk.*"
        )
        
        # Send to the Private Channel
        try:
            bot.send_message(CHANNEL_ID, msg, parse_mode='Markdown')
        except Exception as e:
            print(f"Failed to send to channel: {e}")
            
        return 'Success', 200

if __name__ == '__main__':
    # Use the port assigned by Render
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
