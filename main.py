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

# --- TRADE TRACKING WITH FULL STATE ---
active_trades = {}
# Structure: {ticker: {
#   'msg_id': int,
#   'direction': 'BUY/SELL',
#   'entry': float,
#   'sl': float,
#   'tp1': float,
#   'tp2': float,
#   'tp3': float,
#   'be_hit': bool,
#   'tp1_hit': bool,
#   'tp2_hit': bool,
#   'tp3_hit': bool,
#   'sl_hit': bool,
#   'closed': bool
# }}

# --- CACHE SYSTEM ---
class NewsCache:
    def __init__(self, ttl_minutes=60):
        self.cache = {}
        self.ttl = ttl_minutes * 60
        
    def get(self, key):
        if key in self.cache:
            data, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return data
            else:
                del self.cache[key]
        return None
    
    def set(self, key, value):
        self.cache[key] = (value, time.time())
    
    def clear(self):
        self.cache = {}
    
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
    
    result = scrape_investing_com() or scrape_forex_factory() or get_default_news()
    news_cache.set(cache_key, result)
    return result

def scrape_investing_com():
    try:
        url = "https://www.investing.com/economic-calendar/"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        
        response = requests.get(url, headers=headers, timeout=8)
        if response.status_code != 200:
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
            except:
                continue
        
        if high_risk_events:
            return {
                'status': 'HIGH_RISK',
                'message': f"WARNING: {high_risk_events[0][:30]}",
                'adjust': -10,
                'source': 'Investing.com'
            }
        
        return {
            'status': 'CLEAR',
            'message': 'No major events',
            'adjust': 0,
            'source': 'Investing.com'
        }
        
    except Exception as e:
        return None

def scrape_forex_factory():
    try:
        url = "https://www.forexfactory.com/calendar?week=this"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        
        response = requests.get(url, headers=headers, timeout=8)
        if response.status_code != 200:
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
                'message': f'ALERT: {cpi_events[0][:30]}',
                'adjust': -15,
                'source': 'Forex Factory'
            }
        
        return {
            'status': 'CLEAR',
            'message': 'Safe window',
            'adjust': 0,
            'source': 'Forex Factory'
        }
        
    except Exception as e:
        return None

def get_default_news():
    return {
        'status': 'UNKNOWN',
        'message': 'News unavailable',
        'adjust': -5,
        'source': 'Default'
    }

# --- MULTI-TIMEFRAME ---
def get_mtf_correlation(ticker, current_tf):
    cache_key = f'mtf_{ticker}_{current_tf}'
    cached_data = mtf_cache.get(cache_key)
    if cached_data:
        return cached_data
    
    tf_hierarchy = {
        '1m': 1, '5m': 2, '15m': 3, '30m': 4, 
        '1h': 5, '4h': 6, '1d': 7, '1w': 8
    }
    
    current_level = tf_hierarchy.get(current_tf, 3)
    
    if current_level <= 2:
        result = {
            'confluence': 'WEAK',
            'message': 'Scalp - high risk',
            'boost': -5
        }
    elif current_level <= 3:
        result = {
            'confluence': 'MODERATE',
            'message': 'Check 1H trend',
            'boost': 0
        }
    elif current_level <= 5:
        result = {
            'confluence': 'GOOD',
            'message': 'Medium-term aligned',
            'boost': 5
        }
    else:
        result = {
            'confluence': 'STRONG',
            'message': 'Higher TF confirmed',
            'boost': 10
        }
    
    mtf_cache.set(cache_key, result)
    return result

# --- AI ANALYSIS FOR NEW SIGNALS ---
def get_ai_analysis(data):
    strat = data.get('strat', 'Unknown')
    ticker = data.get('ticker')
    tf = data.get('tf', 'N/A')
    direction = data.get('sig', 'N/A')
    entry_price = data.get('price', 'N/A')
    
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
    
    prompt = f"""
You are a professional forex analyst. Analyze this NEW trade setup:

TRADE DETAILS:
- Pair: {ticker}
- Direction: {direction}
- Strategy: {strat} (Historical: {base_prob}%)
- Timeframe: {tf}
- Entry: {entry_price}

MARKET CONTEXT:
- News Risk: {cpi_data['message']}
- Multi-Timeframe: {mtf_data['message']}

Your task: Rate this trade 1-10 and provide brief analysis.

OUTPUT (EXACTLY):
Win Probability: {final_prob}%
Trade Rating: X/10
Analysis: [One sentence on setup quality and key risk]

Keep analysis under 120 characters.
"""
    
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=200
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        return f"Win Probability: {final_prob}%\nTrade Rating: 7/10\nAnalysis: {strat} setup with {mtf_data['confluence']} MTF confluence."

# --- AI MOMENTUM ANALYSIS FOR UPDATES ---
def get_momentum_analysis(trade_data, current_status):
    """
    AI analyzes trade progress and suggests hold or exit
    """
    ticker = trade_data['ticker']
    direction = trade_data['direction']
    entry = trade_data['entry']
    current_price = trade_data.get('current_price', entry)
    
    # Calculate current profit
    if direction == 'BUY':
        pips_profit = (float(current_price) - float(entry)) * 10000
    else:
        pips_profit = (float(entry) - float(current_price)) * 10000
    
    prompt = f"""
You are analyzing a LIVE forex trade. Suggest whether to HOLD or CLOSE.

TRADE STATUS:
- Pair: {ticker}
- Direction: {direction}
- Entry: {entry}
- Current: {current_price}
- Progress: {current_status}
- Profit: {pips_profit:.1f} pips

Based on momentum and typical price action after {current_status}, should trader:
1. HOLD - Wait for next target
2. CLOSE - Take profit now

OUTPUT (ONE LINE):
Suggestion: [HOLD or CLOSE] - [Brief reason in 10 words or less]

Example: "Suggestion: HOLD - Strong momentum supports TP2 target"
"""
    
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=100
        )
        return completion.choices[0].message.content.strip()
    except:
        return "Suggestion: HOLD - Monitor price action"

# --- CALCULATE RR ---
def calculate_rr(entry, sl, current_price, direction):
    """Calculate risk:reward ratio"""
    entry = float(entry)
    sl = float(sl)
    current_price = float(current_price)
    
    risk = abs(entry - sl)
    if risk == 0:
        return 0
    
    if direction == 'BUY':
        profit = current_price - entry
    else:
        profit = entry - current_price
    
    rr = profit / risk
    return round(rr, 1)

# --- WEBHOOK ---
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        if not data:
            return 'No Data', 400

        ticker = data.get('ticker', 'UNKNOWN')
        
        # ===== BREAK-EVEN UPDATE =====
        if data.get("status") == "MOVED TO BE":
            if ticker not in active_trades:
                # Trade not tracked, send standalone message
                msg = (
                    f"BREAK-EVEN SECURED\n"
                    f"Asset: {ticker}\n"
                    f"Stop Loss moved to Entry\n"
                    f"Risk eliminated! (0RR secured)"
                )
                bot.send_message(CHANNEL_ID, msg)
                return 'OK', 200
            
            # Check if already sent
            if active_trades[ticker]['be_hit']:
                print(f"BE already sent for {ticker}, skipping duplicate")
                return 'OK', 200
            
            # Update state
            active_trades[ticker]['be_hit'] = True
            
            # Build status string
            status = f"BE DONE | TP1 {'DONE' if active_trades[ticker]['tp1_hit'] else 'PENDING'} | TP2 PENDING | TP3 PENDING"
            
            msg = (
                f"BREAK-EVEN SECURED\n"
                f"Asset: {ticker}\n"
                f"Status: {status}\n"
                f"Current Price: {data.get('price')}\n"
                f"Risk: 0RR (Secured)"
            )
            
            bot.send_message(
                CHANNEL_ID, msg,
                reply_to_message_id=active_trades[ticker]['msg_id']
            )
            
            return 'OK', 200
        
        # ===== TP/SL HITS =====
        if "hit" in data:
            hit_msg = data.get('hit')
            price = data.get('price', 'N/A')
            
            if ticker not in active_trades:
                # Send standalone if not tracked
                msg = f"{hit_msg}\nAsset: {ticker}\nPrice: {price}"
                bot.send_message(CHANNEL_ID, msg)
                return 'OK', 200
            
            trade = active_trades[ticker]
            
            # Prevent duplicate messages
            if "TP1" in hit_msg and trade['tp1_hit']:
                return 'OK', 200
            if "TP2" in hit_msg and trade['tp2_hit']:
                return 'OK', 200
            if "TP3" in hit_msg and trade['tp3_hit']:
                return 'OK', 200
            if "SL" in hit_msg and (trade['sl_hit'] or trade['be_hit']):
                # Can't hit SL after BE
                print(f"SL hit after BE for {ticker}, ignoring")
                return 'OK', 200
            
            # Calculate RR
            rr = calculate_rr(trade['entry'], trade['sl'], price, trade['direction'])
            
            # Determine outcome
            if "TP3" in hit_msg:
                status_emoji = "DONE"
                rr_display = f"+3RR ({rr}R actual)"
                trade['tp3_hit'] = True
                trade['closed'] = True
                ai_suggestion = "Trade completed successfully!"
                
            elif "TP2" in hit_msg:
                status_emoji = "DONE"
                rr_display = f"+2RR ({rr}R actual)"
                trade['tp2_hit'] = True
                
                # AI suggests hold or close
                trade_data = {
                    'ticker': ticker,
                    'direction': trade['direction'],
                    'entry': trade['entry'],
                    'current_price': price
                }
                ai_suggestion = get_momentum_analysis(trade_data, "TP2 hit")
                
            elif "TP1" in hit_msg:
                status_emoji = "DONE"
                rr_display = f"+1RR ({rr}R actual)"
                trade['tp1_hit'] = True
                
                # AI suggests hold or close
                trade_data = {
                    'ticker': ticker,
                    'direction': trade['direction'],
                    'entry': trade['entry'],
                    'current_price': price
                }
                ai_suggestion = get_momentum_analysis(trade_data, "TP1 hit")
                
            elif "SL" in hit_msg:
                status_emoji = "HIT"
                rr_display = f"-1RR ({rr}R actual)"
                trade['sl_hit'] = True
                trade['closed'] = True
                ai_suggestion = "Loss taken. Review setup for next trade."
                
            else:
                status_emoji = "UPDATE"
                rr_display = f"{rr}R"
                ai_suggestion = "Monitor trade progress"
            
            # Build status line
            be_status = "DONE" if trade['be_hit'] else "PENDING"
            tp1_status = "DONE" if trade['tp1_hit'] else "PENDING"
            tp2_status = "DONE" if trade['tp2_hit'] else "PENDING"
            tp3_status = "DONE" if trade['tp3_hit'] else "PENDING"
            
            status_line = f"BE {be_status} | TP1 {tp1_status} | TP2 {tp2_status} | TP3 {tp3_status}"
            
            msg = (
                f"{hit_msg}\n"
                f"Asset: {ticker}\n"
                f"Status: {status_line}\n"
                f"Exit Price: {price}\n"
                f"Result: {rr_display}\n"
                f"---\n"
                f"AI: {ai_suggestion}"
            )
            
            bot.send_message(
                CHANNEL_ID, msg,
                reply_to_message_id=trade['msg_id']
            )
            
            # Clean up closed trades
            if trade['closed']:
                del active_trades[ticker]
            
            return 'OK', 200

        # ===== NEW SIGNAL =====
        
        # CHECK FOR DUPLICATE SIGNAL
        if ticker in active_trades and not active_trades[ticker]['closed']:
            print(f"DUPLICATE SIGNAL BLOCKED: {ticker} already has active trade")
            
            # Send warning message (optional - reply to original signal)
            existing_trade = active_trades[ticker]
            warning_msg = (
                f"DUPLICATE SIGNAL BLOCKED\n"
                f"Asset: {ticker}\n"
                f"Reason: Active trade already running\n"
                f"Current Status:\n"
                f"- BE: {'DONE' if existing_trade['be_hit'] else 'PENDING'}\n"
                f"- TP1: {'DONE' if existing_trade['tp1_hit'] else 'PENDING'}\n"
                f"- TP2: {'DONE' if existing_trade['tp2_hit'] else 'PENDING'}\n"
                f"- TP3: {'DONE' if existing_trade['tp3_hit'] else 'PENDING'}\n"
                f"Ignoring new signal to avoid confusion."
            )
            
            bot.send_message(
                CHANNEL_ID, 
                warning_msg,
                reply_to_message_id=existing_trade['msg_id']
            )
            
            return 'OK', 200
        
        # Proceed with new signal
        ai_analysis = get_ai_analysis(data)
        
        msg = (
            f"AAD-FX PREMIUM SIGNAL\n"
            f"{'='*30}\n"
            f"Asset: {data.get('ticker')} | TF: {data.get('tf')}\n"
            f"Strategy: {data.get('strat')}\n"
            f"Direction: {data.get('sig')} at {data.get('price')}\n"
            f"{'-'*30}\n"
            f"SL: {data.get('sl')}\n"
            f"TP1: {data.get('tp1')}\n"
            f"TP2: {data.get('tp2')}\n"
            f"TP3: {data.get('tp3')}\n"
            f"{'='*30}\n"
            f"AI ANALYSIS:\n{ai_analysis}\n"
            f"{'='*30}\n"
            f"Time: {datetime.now().strftime('%H:%M UTC')}"
        )
        
        sent_msg = bot.send_message(CHANNEL_ID, msg)
        
        # Track trade state
        active_trades[ticker] = {
            'msg_id': sent_msg.message_id,
            'direction': data.get('sig'),
            'entry': data.get('price'),
            'sl': data.get('sl'),
            'tp1': data.get('tp1'),
            'tp2': data.get('tp2'),
            'tp3': data.get('tp3'),
            'be_hit': False,
            'tp1_hit': False,
            'tp2_hit': False,
            'tp3_hit': False,
            'sl_hit': False,
            'closed': False,
            'ticker': ticker
        }
        
        print(f"NEW SIGNAL TRACKED: {ticker} (msg_id: {sent_msg.message_id})")
        
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
        'active_trades': len(active_trades),
        'trades': {k: {
            'direction': v['direction'],
            'be_hit': v['be_hit'],
            'tp1_hit': v['tp1_hit'],
            'tp2_hit': v['tp2_hit'],
            'tp3_hit': v['tp3_hit'],
            'closed': v['closed']
        } for k, v in active_trades.items()}
    }

@app.route('/cache/clear', methods=['POST'])
def clear_cache():
    news_cache.clear()
    mtf_cache.clear()
    return {'status': 'Cache cleared'}

@app.route('/trades/clear', methods=['POST'])
def clear_trades():
    active_trades.clear()
    return {'status': 'All trades cleared'}

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