import os
from flask import Flask, request, jsonify
import telebot
from groq import Groq
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import time
import json

# --- CONFIG ---
bot = telebot.TeleBot(os.environ.get('TELEGRAM_TOKEN'))
CHANNEL_ID = os.environ.get('TELEGRAM_CHAT_ID')
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

app = Flask(__name__)

# --- TRADE TRACKING WITH FULL STATE ---
active_trades = {}
cluster_states = {}

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
        return {'items': len(self.cache), 'ttl_minutes': self.ttl / 60}

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
            return {'status': 'HIGH_RISK', 'message': f"WARNING: {high_risk_events[0][:30]}", 'adjust': -10, 'source': 'Investing.com'}
        
        return {'status': 'CLEAR', 'message': 'No major events', 'adjust': 0, 'source': 'Investing.com'}
        
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
            return {'status': 'CPI_ALERT', 'message': f'ALERT: {cpi_events[0][:30]}', 'adjust': -15, 'source': 'Forex Factory'}
        
        return {'status': 'CLEAR', 'message': 'Safe window', 'adjust': 0, 'source': 'Forex Factory'}
        
    except Exception as e:
        return None

def get_default_news():
    return {'status': 'UNKNOWN', 'message': 'News unavailable', 'adjust': -5, 'source': 'Default'}

# --- MULTI-TIMEFRAME ---
def get_mtf_correlation(ticker, current_tf):
    cache_key = f'mtf_{ticker}_{current_tf}'
    cached_data = mtf_cache.get(cache_key)
    if cached_data:
        return cached_data
    
    tf_hierarchy = {'1m': 1, '5m': 2, '15m': 3, '30m': 4, '1h': 5, '4h': 6, '1d': 7, '1w': 8}
    current_level = tf_hierarchy.get(current_tf, 3)
    
    if current_level <= 2:
        result = {'confluence': 'WEAK', 'message': 'Scalp - high risk', 'boost': -5}
    elif current_level <= 3:
        result = {'confluence': 'MODERATE', 'message': 'Check 1H trend', 'boost': 0}
    elif current_level <= 5:
        result = {'confluence': 'GOOD', 'message': 'Medium-term aligned', 'boost': 5}
    else:
        result = {'confluence': 'STRONG', 'message': 'Higher TF confirmed', 'boost': 10}
    
    mtf_cache.set(cache_key, result)
    return result

# --- AI ANALYSIS FOR NEW SIGNALS ---
def get_ai_analysis(data):
    strat = data.get('strat', 'Ribbon Breakout')
    ticker = data.get('ticker')
    tf = data.get('tf', 'N/A')
    direction = data.get('sig', data.get('direction', 'N/A'))
    entry_price = data.get('price', 'N/A')
    
    strategy_probabilities = {
        'Triangle Breakout': 80, 'Triangle Breakdown': 80, 'Range Bounce': 70,
        'Range Rejection': 70, 'Scalp MA Cross': 45, 'Ribbon Breakout': 75
    }
    
    base_prob = strategy_probabilities.get(strat, 50)
    cpi_data = get_cpi_bias()
    mtf_data = get_mtf_correlation(ticker, tf)
    
    final_prob = base_prob + cpi_data['adjust'] + mtf_data['boost']
    final_prob = max(30, min(95, final_prob))
    
    prompt = f"""You are a professional forex analyst. Analyze this NEW trade setup:

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

Keep analysis under 120 characters."""
    
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
    ticker = trade_data['ticker']
    direction = trade_data['direction']
    entry = trade_data['entry']
    current_price = trade_data.get('current_price', entry)
    
    if direction == 'BUY':
        pips_profit = (float(current_price) - float(entry)) * 10000
    else:
        pips_profit = (float(entry) - float(current_price)) * 10000
    
    prompt = f"""You are analyzing a LIVE forex trade. Suggest whether to HOLD or CLOSE.

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

Example: "Suggestion: HOLD - Strong momentum supports TP2 target" """
    
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
            print("ERROR: No data received")
            return jsonify({'error': 'No data'}), 400

        print(f"WEBHOOK RECEIVED: {json.dumps(data, indent=2)}")
        
        ticker = data.get('ticker', 'UNKNOWN')
        alert_type = data.get('alert_type', 'signal')
        
        print(f"Processing alert_type: {alert_type} for {ticker}")
        
        # ===== RIBBON STRATEGY ALERTS =====
        if alert_type == "cluster_formed":
            direction = data.get('direction', 'UNKNOWN')
            price = data.get('price', 'N/A')
            spread = data.get('spread', 'N/A')
            tf = data.get('tf', 'N/A')
            
            msg = (
                f"CLUSTER POINT FORMED\n"
                f"{'='*35}\n"
                f"Asset: {ticker} | TF: {tf}\n"
                f"Direction: {direction}\n"
                f"Price: {price}\n"
                f"Ribbon Spread: {spread}%\n"
                f"{'='*35}\n"
                f"Status: Awaiting Confirmation\n"
                f"Watch for price action...\n"
                f"Time: {datetime.now().strftime('%H:%M UTC')}"
            )
            
            print(f"Sending cluster message to Telegram...")
            sent_msg = bot.send_message(CHANNEL_ID, msg)
            print(f"Message sent! ID: {sent_msg.message_id}")
            
            # Track cluster state
            cluster_states[ticker] = {
                'cluster_formed': True,
                'confirmed': False,
                'brokeout': False,
                'direction': direction,
                'cluster_price': price,
                'msg_id': sent_msg.message_id,
                'tf': tf
            }
            
            return jsonify({'status': 'ok', 'message': 'Cluster alert sent'}), 200
        
        elif alert_type == "confirmed":
            direction = data.get('direction', 'UNKNOWN')
            price = data.get('price', 'N/A')
            
            if ticker not in cluster_states:
                msg = f"CONFIRMED\nAsset: {ticker}\nDirection: {direction}\nPrice: {price}"
                bot.send_message(CHANNEL_ID, msg)
                return jsonify({'status': 'ok'}), 200
            
            cluster_states[ticker]['confirmed'] = True
            
            msg = (
                f"CONFIRMATION RECEIVED\n"
                f"{'='*35}\n"
                f"Asset: {ticker}\n"
                f"Direction: {direction}\n"
                f"Price: {price}\n"
                f"{'='*35}\n"
                f"Status: Confirmed & Valid\n"
                f"MMA 40 & 100: Properly aligned\n"
                f"Awaiting breakout signal...\n"
                f"Time: {datetime.now().strftime('%H:%M UTC')}"
            )
            
            bot.send_message(CHANNEL_ID, msg, reply_to_message_id=cluster_states[ticker]['msg_id'])
            
            return jsonify({'status': 'ok', 'message': 'Confirmation sent'}), 200
        
        elif alert_type == "breakout_due":
            direction = data.get('direction', 'UNKNOWN')
            spread = data.get('spread', 'N/A')
            
            if ticker not in cluster_states:
                msg = f"BREAKOUT DUE\nAsset: {ticker}\nRibbons spreading!"
                bot.send_message(CHANNEL_ID, msg)
                return jsonify({'status': 'ok'}), 200
            
            msg = (
                f"BREAKOUT IMMINENT\n"
                f"{'='*35}\n"
                f"Asset: {ticker}\n"
                f"Direction: {direction}\n"
                f"Ribbon Spread: {spread}%\n"
                f"{'='*35}\n"
                f"Status: Ribbons fanning out!\n"
                f"Prepare for breakout entry\n"
                f"Time: {datetime.now().strftime('%H:%M UTC')}"
            )
            
            bot.send_message(CHANNEL_ID, msg, reply_to_message_id=cluster_states[ticker]['msg_id'])
            
            return jsonify({'status': 'ok', 'message': 'Breakout due sent'}), 200
        
        elif alert_type == "breakout":
            direction = data.get('direction', 'UNKNOWN')
            price = data.get('price', 'N/A')
            tp = data.get('tp', 'N/A')
            sl = data.get('sl', 'N/A')
            market_condition = data.get('market_condition', 'NORMAL')
            stoch_k = data.get('stoch_k', 'N/A')
            tf = data.get('tf', 'N/A')
            
            if ticker in cluster_states:
                cluster_states[ticker]['brokeout'] = True
            
            # Get AI analysis for breakout
            ai_data = {
                'strat': 'Ribbon Breakout',
                'ticker': ticker,
                'tf': tf,
                'sig': direction,
                'price': price
            }
            ai_analysis = get_ai_analysis(ai_data)
            
            msg = (
                f"BREAKOUT CONFIRMED!\n"
                f"{'='*35}\n"
                f"Asset: {ticker} | TF: {tf}\n"
                f"Direction: {direction}\n"
                f"Entry: {price}\n"
                f"{'-'*35}\n"
                f"TP: {tp}\n"
                f"SL: {sl}\n"
                f"{'='*35}\n"
                f"Market Condition: {market_condition}\n"
                f"Stoch K: {stoch_k}\n"
                f"{'-'*35}\n"
                f"AI ANALYSIS:\n{ai_analysis}\n"
                f"{'='*35}\n"
                f"Time: {datetime.now().strftime('%H:%M UTC')}"
            )
            
            if ticker in cluster_states:
                sent_msg = bot.send_message(CHANNEL_ID, msg, reply_to_message_id=cluster_states[ticker]['msg_id'])
            else:
                sent_msg = bot.send_message(CHANNEL_ID, msg)
            
            # Track as active trade
            active_trades[ticker] = {
                'msg_id': sent_msg.message_id,
                'direction': direction,
                'entry': price,
                'sl': sl,
                'tp1': tp,
                'tp2': tp,
                'tp3': tp,
                'be_hit': False,
                'tp1_hit': False,
                'tp2_hit': False,
                'tp3_hit': False,
                'sl_hit': False,
                'closed': False,
                'ticker': ticker
            }
            
            return jsonify({'status': 'ok', 'message': 'Breakout sent'}), 200
        
        elif alert_type == "trend_change":
            original_direction = data.get('original_direction', 'UNKNOWN')
            advice = data.get('advice', 'CLOSE')
            price = data.get('price', 'N/A')
            tf = data.get('tf', 'N/A')
            
            msg = (
                f"TREND CHANGE DETECTED\n"
                f"{'='*35}\n"
                f"Asset: {ticker} | TF: {tf}\n"
                f"Original Trade: {original_direction}\n"
                f"Current Price: {price}\n"
                f"{'='*35}\n"
                f"MMA Lines Crossed Against Trade\n"
                f"Recommendation: {advice}\n"
                f"{'='*35}\n"
                f"Consider closing or securing profits!\n"
                f"Time: {datetime.now().strftime('%H:%M UTC')}"
            )
            
            if ticker in cluster_states:
                bot.send_message(CHANNEL_ID, msg, reply_to_message_id=cluster_states[ticker]['msg_id'])
            elif ticker in active_trades:
                bot.send_message(CHANNEL_ID, msg, reply_to_message_id=active_trades[ticker]['msg_id'])
            else:
                bot.send_message(CHANNEL_ID, msg)
            
            return jsonify({'status': 'ok', 'message': 'Trend change sent'}), 200
        
        # ===== EXISTING BREAK-EVEN UPDATE =====
        if data.get("status") == "MOVED TO BE":
            if ticker not in active_trades:
                msg = (
                    f"BREAK-EVEN SECURED\n"
                    f"Asset: {ticker}\n"
                    f"Stop Loss moved to Entry\n"
                    f"Risk eliminated! (0RR secured)"
                )
                bot.send_message(CHANNEL_ID, msg)
                return jsonify({'status': 'ok'}), 200
            
            if active_trades[ticker]['be_hit']:
                print(f"BE already sent for {ticker}, skipping duplicate")
                return jsonify({'status': 'duplicate'}), 200
            
            active_trades[ticker]['be_hit'] = True
            
            status = f"BE DONE | TP1 {'DONE' if active_trades[ticker]['tp1_hit'] else 'PENDING'} | TP2 PENDING | TP3 PENDING"
            
            msg = (
                f"BREAK-EVEN SECURED\n"
                f"Asset: {ticker}\n"
                f"Status: {status}\n"
                f"Current Price: {data.get('price')}\n"
                f"Risk: 0RR (Secured)"
            )
            
            bot.send_message(CHANNEL_ID, msg, reply_to_message_id=active_trades[ticker]['msg_id'])
            
            return jsonify({'status': 'ok'}), 200
        
        # ===== TP/SL HITS =====
        if "hit" in data:
            hit_msg = data.get('hit')
            price = data.get('price', 'N/A')
            
            if ticker not in active_trades:
                msg = f"{hit_msg}\nAsset: {ticker}\nPrice: {price}"
                bot.send_message(CHANNEL_ID, msg)
                return jsonify({'status': 'ok'}), 200
            
            trade = active_trades[ticker]
            
            if "TP1" in hit_msg and trade['tp1_hit']:
                return jsonify({'status': 'duplicate'}), 200
            if "TP2" in hit_msg and trade['tp2_hit']:
                return jsonify({'status': 'duplicate'}), 200
            if "TP3" in hit_msg and trade['tp3_hit']:
                return jsonify({'status': 'duplicate'}), 200
            if "SL" in hit_msg and (trade['sl_hit'] or trade['be_hit']):
                print(f"SL hit after BE for {ticker}, ignoring")
                return jsonify({'status': 'ignored'}), 200
            
            rr = calculate_rr(trade['entry'], trade['sl'], price, trade['direction'])
            
            if "TP3" in hit_msg:
                rr_display = f"+3RR ({rr}R actual)"
                trade['tp3_hit'] = True
                trade['closed'] = True
                ai_suggestion = "Trade completed successfully!"
                
            elif "TP2" in hit_msg:
                rr_display = f"+2RR ({rr}R actual)"
                trade['tp2_hit'] = True
                
                trade_data = {
                    'ticker': ticker,
                    'direction': trade['direction'],
                    'entry': trade['entry'],
                    'current_price': price
                }
                ai_suggestion = get_momentum_analysis(trade_data, "TP2 hit")
                
            elif "TP1" in hit_msg:
                rr_display = f"+1RR ({rr}R actual)"
                trade['tp1_hit'] = True
                
                trade_data = {
                    'ticker': ticker,
                    'direction': trade['direction'],
                    'entry': trade['entry'],
                    'current_price': price
                }
                ai_suggestion = get_momentum_analysis(trade_data, "TP1 hit")
                
            elif "SL" in hit_msg:
                rr_display = f"-1RR ({rr}R actual)"
                trade['sl_hit'] = True
                trade['closed'] = True
                ai_suggestion = "Loss taken. Review setup for next trade."
            else:
                rr_display = f"{rr}R"
                ai_suggestion = "Monitor trade progress"
            
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
            
            bot.send_message(CHANNEL_ID, msg, reply_to_message_id=trade['msg_id'])
            
            if trade['closed']:
                del active_trades[ticker]
                if ticker in cluster_states:
                    del cluster_states[ticker]
            
            return jsonify({'status': 'ok'}), 200

        # ===== DEFAULT: NEW SIGNAL (ORIGINAL LOGIC) =====
        if ticker in active_trades and not active_trades[ticker]['closed']:
            print(f"DUPLICATE SIGNAL BLOCKED: {ticker} already has active trade")
            return jsonify({'status': 'duplicate', 'message': 'Trade already active'}), 200
        
        # Original signal format
        if 'sig' in data and 'strat' in data:
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
            
            return jsonify({'status': 'ok', 'message': 'Signal sent'}), 200
        
        return jsonify({'status': 'ok', 'message': 'Processed'}), 200
        
    except Exception as e:
        print(f"WEBHOOK ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# ADMIN ENDPOINTS
@app.route('/cache/stats', methods=['GET'])
def cache_stats():
    return jsonify({
        'news_cache': news_cache.get_stats(),
        'mtf_cache': mtf_cache.get_stats(),
        'active_trades': len(active_trades),
        'cluster_states': len(cluster_states),
        'trades': {k: {
            'direction': v['direction'],
            'be_hit': v['be_hit'],
            'closed': v['closed']
        } for k, v in active_trades.items()},
        'clusters': {k: {
            'direction': v['direction'],
            'confirmed': v['confirmed'],
            'brokeout': v['brokeout']
        } for k, v in cluster_states.items()}
    })

@app.route('/cache/clear', methods=['POST'])
def clear_cache():
    news_cache.clear()
    mtf_cache.clear()
    return jsonify({'status': 'Cache cleared'})

@app.route('/trades/clear', methods=['POST'])
def clear_trades():
    active_trades.clear()
    cluster_states.clear()
    return jsonify({'status': 'All trades and clusters cleared'})

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'active_trades': len(active_trades),
        'cluster_states': len(cluster_states),
        'telegram_token_set': bool(os.environ.get('TELEGRAM_TOKEN')),
        'channel_id_set': bool(os.environ.get('TELEGRAM_CHAT_ID'))
    })

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        'service': 'AAD-FX Trading Bot',
        'version': '2.0',
        'status': 'running',
        'endpoints': ['/webhook', '/health', '/cache/stats', '/trades/clear']
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"=== AAD-FX Bot Starting ===")
    print(f"Port: {port}")
    print(f"Telegram Token Set: {bool(os.environ.get('TELEGRAM_TOKEN'))}")
    print(f"Channel ID Set: {bool(os.environ.get('TELEGRAM_CHAT_ID'))}")
    print(f"=========================")
    app.run(host='0.0.0.0', port=port, debug=False)