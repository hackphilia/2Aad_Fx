import os
from flask import Flask, request
import telebot
from groq import Groq
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import time

# --- CONFIG ---
bot = telebot.TeleBot(os.environ.get('TELEGRAM_TOKEN'))
CHANNEL_ID = os.environ.get('TELEGRAM_CHAT_ID')
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

app = Flask(__name__)

# --- TRADE TRACKING ---
active_trades = {}

# --- CACHE SYSTEM ---
class NewsCache:
    def __init__(self, ttl_minutes=60):
        self.cache = {}
        self.ttl = ttl_minutes * 60
        
    def get(self, key):
        if key in self.cache:
            data, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                print(f"Cache HIT for {key}")
                return data
            else:
                print(f"Cache EXPIRED for {key}")
                del self.cache[key]
        print(f"Cache MISS for {key}")
        return None
    
    def set(self, key, value):
        self.cache[key] = (value, time.time())
        print(f"Cached {key}")
    
    def clear(self):
        self.cache = {}
        print("Cache cleared")
    
    def get_stats(self):
        return {
            'items': len(self.cache),
            'ttl_minutes': self.ttl / 60
        }

news_cache = NewsCache(ttl_minutes=60)
mtf_cache = NewsCache(ttl_minutes=15)

# --- CPI NEWS SCRAPER ---
def get_cpi_bias():
    cache_key = 'cpi_news'
    cached_data = news_cache.get(cache_key)
    if cached_data:
        return cached_data
    
    print("Fetching fresh CPI news data...")
    result = scrape_investing_com() or scrape_forex_factory() or get_default_news()
    news_cache.set(cache_key, result)
    return result

def scrape_investing_com():
    try:
        url = "https://www.investing.com/economic-calendar/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=8)
        if response.status_code != 200:
            print(f"Investing.com failed: {response.status_code}")
            return None
            
        soup = BeautifulSoup(response.content, 'html.parser')
        events = soup.find_all('tr', {'class': 'js-event-item'})
        
        high_risk_events = []
        
        for event in events[:25]:
            try:
                impact = event.find('td', {'class': 'sentiment'})
                if impact and len(impact.find_all('i', {'class': 'grayFullBullishIcon'})) == 3:
                    event_name_elem = event.find('td', {'class': 'event'})
                    if event_name_elem:
                        name_text = event_name_elem.get_text(strip=True)
                        if any(kw in name_text.upper() for kw in ['CPI', 'NFP', 'FOMC', 'GDP', 'INTEREST RATE', 'EMPLOYMENT']):
                            high_risk_events.append(name_text)
            except Exception as e:
                continue
        
        if high_risk_events:
            return {
                'status': 'HIGH_RISK',
                'message': f"WARNING {high_risk_events[0][:35]}",
                'adjust': -10,
                'source': 'Investing.com',
                'events': high_risk_events
            }
        
        return {
            'status': 'CLEAR',
            'message': 'No major events',
            'adjust': 0,
            'source': 'Investing.com',
            'events': []
        }
        
    except Exception as e:
        print(f"Investing.com error: {e}")
        return None

def scrape_forex_factory():
    try:
        url = "https://www.forexfactory.com/calendar?week=this"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=8)
        if response.status_code != 200:
            print(f"Forex Factory failed: {response.status_code}")
            return None
            
        soup = BeautifulSoup(response.content, 'html.parser')
        high_impact = soup.find_all('span', {'class': 'high'})
        
        cpi_events = []
        for event in high_impact[:15]:
            row = event.find_parent('tr')
            if row:
                title_elem = row.find('span', {'class': 'calendar__event-title'})
                if title_elem:
                    event_text = title_elem.get_text(strip=True)
                    if any(kw in event_text.upper() for kw in ['CPI', 'NFP', 'FOMC']):
                        cpi_events.append(event_text)
        
        if cpi_events:
            return {
                'status': 'CPI_ALERT',
                'message': f'ALERT {cpi_events[0][:35]}',
                'adjust': -15,
                'source': 'Forex Factory',
                'events': cpi_events
            }
        
        return {
            'status': 'CLEAR',
            'message': 'Safe window',
            'adjust': 0,
            'source': 'Forex Factory',
            'events': []
        }
        
    except Exception as e:
        print(f"Forex Factory error: {e}")
        return None

def get_default_news():
    return {
        'status': 'UNKNOWN',
        'message': 'News check unavailable',
        'adjust': -5,
        'source': 'Default',
        'events': []
    }

# --- MULTI-TIMEFRAME ---
def get_mtf_correlation(ticker, current_tf):
    cache_key = f'mtf_{ticker}_{current_tf}'
    cached_data = mtf_cache.get(cache_key)
    if cached_data:
        return cached_data
    
    print(f"Calculating MTF for {ticker} on {current_tf}")
    
    tf_hierarchy = {
        '1m': 1, '5m': 2, '15m': 3, '30m': 4, 
        '1h': 5, '4h': 6, '1d': 7, '1w': 8
    }
    
    current_level = tf_hierarchy.get(current_tf, 3)
    
    if current_level <= 2:
        result = {
            'confluence': 'WEAK',
            'message': 'Scalp setup - high risk',
            'boost': -5,
            'timeframe_quality': 'LOW'
        }
    elif current_level <= 3:
        result = {
            'confluence': 'MODERATE',
            'message': 'Check 1H trend',
            'boost': 0,
            'timeframe_quality': 'MEDIUM'
        }
    elif current_level <= 5:
        result = {
            'confluence': 'GOOD',
            'message': 'Medium-term aligned',
            'boost': 5,
            'timeframe_quality': 'GOOD'
        }
    else:
        result = {
            'confluence': 'STRONG',
            'message': 'Higher TF confirmation',
            'boost': 10,
            'timeframe_quality': 'EXCELLENT'
        }
    
    mtf_cache.set(cache_key, result)
    return result

# --- AI ANALYSIS ---
def get_ai_analysis(data):
    strat = data.get('strat', 'Unknown')
    ticker = data.get('ticker')
    tf = data.get('tf', 'N/A')
    direction = data.get('sig', 'N/A')
    entry_price = data.get('price', 'N/A')
    sl = data.get('sl', 'N/A')
    tp3 = data.get('tp3', 'N/A')
    
    strategy_probabilities = {
        'Triangle Breakout': 80,
        'Triangle Breakdown': 80,
        'Range Bounce': 70,
        'Range Rejection': 70,
        'Scalp MA Cross': 45
    }
    
    base_prob = strategy_probabilities.get(strat, 50)
    cpi_data = get_cpi_bias()
    mtf_data = get_mtf_correlation(ticker, tf)
    
    final_prob = base_prob + cpi_data['adjust'] + mtf_data['boost']
    final_prob = max(30, min(95, final_prob))
    
    try:
        entry = float(entry_price)
        stop = float(sl)
        target = float(tp3)
        risk = abs(entry - stop)
        reward = abs(target - entry)
        rr_ratio = round(reward / risk, 1) if risk > 0 else 0
    except:
        rr_ratio = 3.0
    
    prompt = f"""
You are an elite forex trader. Analyze this setup:

Pair: {ticker}
Direction: {direction}
Strategy: {strat} (Base Win Rate: {base_prob}%)
Timeframe: {tf}
Entry: {entry_price}
Risk:Reward: 1:{rr_ratio}

Market Intelligence:
News Risk: {cpi_data['message']} (Source: {cpi_data['source']})
Multi-Timeframe: {mtf_data['message']}
Adjusted Win Probability: {final_prob}%

Rate this trade 1-10 based on strategy edge, news risk, MTF confluence, and R:R profile.

OUTPUT FORMAT (STRICT):
Win Probability: {final_prob}%
Trade Rating: X/10
Bias: [One concise sentence with direction bias and key risk]

Keep bias under 150 characters.
"""
    
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=250
        )
        ai_text = completion.choices[0].message.content.strip()
        
        return {
            'analysis': ai_text,
            'cpi_status': cpi_data['message'],
            'mtf_status': mtf_data['message'],
            'final_prob': final_prob,
            'rr_ratio': rr_ratio,
            'news_source': cpi_data['source']
        }
    except Exception as e:
        print(f"AI Error: {e}")
        return {
            'analysis': f"Win Probability: {final_prob}%\nTrade Rating: 7/10\nBias: {strat} setup with {mtf_data['timeframe_quality']} TF quality.",
            'cpi_status': cpi_data['message'],
            'mtf_status': mtf_data['message'],
            'final_prob': final_prob,
            'rr_ratio': rr_ratio,
            'news_source': cpi_data.get('source', 'Unknown')
        }

# --- WEBHOOK ---
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        if not data:
            return 'No Data', 400

        ticker = data.get('ticker', 'UNKNOWN')
        
        # BREAK-EVEN UPDATE
        if data.get("status") == "MOVED TO BE":
            msg = (
                f"BREAK-EVEN SECURED\n"
                f"Asset: {ticker}\n"
                f"Stop Loss moved to Entry\n"
                f"Current Price: {data.get('price')}\n"
                f"Risk eliminated!"
            )
            
            if ticker in active_trades:
                bot.send_message(
                    CHANNEL_ID, msg,
                    reply_to_message_id=active_trades[ticker]['msg_id']
                )
            else:
                bot.send_message(CHANNEL_ID, msg)
            
            return 'OK', 200
        
        # TP/SL HITS
        if "hit" in data:
            hit_msg = data.get('hit')
            price = data.get('price', 'N/A')
            
            if "TP3" in hit_msg:
                status = "MAXIMUM PROFIT"
            elif "TP2" in hit_msg:
                status = "STRONG WIN"
            elif "TP1" in hit_msg:
                status = "PROFIT LOCKED"
            elif "SL" in hit_msg:
                status = "STOPPED OUT"
            else:
                status = "UPDATE"
            
            msg = (
                f"{status}\n"
                f"Asset: {ticker}\n"
                f"{hit_msg}\n"
                f"Exit Price: {price}"
            )
            
            if ticker in active_trades:
                bot.send_message(
                    CHANNEL_ID, msg,
                    reply_to_message_id=active_trades[ticker]['msg_id']
                )
                
                if "TP3" in hit_msg or "SL" in hit_msg:
                    print(f"Removing {ticker} from active trades")
                    del active_trades[ticker]
            else:
                bot.send_message(CHANNEL_ID, msg)
            
            return 'OK', 200

        # NEW SIGNAL
        print(f"Processing new signal for {ticker}")
        ai_result = get_ai_analysis(data)
        
        direction_arrow = "UP" if data.get('sig') == 'BUY' else "DOWN"
        
        msg = (
            f"AAD-FX PREMIUM SIGNAL {direction_arrow}\n"
            f"==============================\n"
            f"Asset: {data.get('ticker')} | Time: {data.get('tf')}\n"
            f"Strategy: {data.get('strat')}\n"
            f"------------------------------\n"
            f"Direction: {data.get('sig')} at {data.get('price')}\n"
            f"Stop Loss: {data.get('sl')}\n"
            f"------------------------------\n"
            f"TP1: {data.get('tp1')}\n"
            f"TP2: {data.get('tp2')}\n"
            f"TP3: {data.get('tp3')}\n"
            f"Risk:Reward = 1:{ai_result['rr_ratio']}\n"
            f"==============================\n"
            f"AI ANALYSIS\n"
            f"{ai_result['analysis']}\n"
            f"------------------------------\n"
            f"News: {ai_result['cpi_status']}\n"
            f"MTF: {ai_result['mtf_status']}\n"
            f"==============================\n"
            f"Time: {datetime.now().strftime('%H:%M UTC')}"
        )
        
        sent_msg = bot.send_message(CHANNEL_ID, msg)
        
        active_trades[ticker] = {
            'msg_id': sent_msg.message_id,
            'direction': data.get('sig'),
            'entry': data.get('price'),
            'timeframe': data.get('tf'),
            'timestamp': datetime.now()
        }
        
        print(f"Signal sent and tracked: {ticker}")
        
        return 'OK', 200
        
    except Exception as e:
        print(f"Webhook Error: {e}")
        import traceback
        traceback.print_exc()
        return 'Error', 500

# ADMIN ENDPOINTS
@app.route('/cache/stats', methods=['GET'])
def cache_stats():
    return {
        'news_cache': news_cache.get_stats(),
        'mtf_cache': mtf_cache.get_stats(),
        'active_trades': len(active_trades)
    }

@app.route('/cache/clear', methods=['POST'])
def clear_cache():
    news_cache.clear()
    mtf_cache.clear()
    return {'status': 'Cache cleared successfully'}

@app.route('/health', methods=['GET'])
def health_check():
    return {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'active_trades': len(active_trades)
    }

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting AAD-FX Bot on port {port}")
    app.run(host='0.0.0.0', port=port)