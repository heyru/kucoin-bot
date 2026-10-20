import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh
import ccxt
import json
import google.generativeai as genai # Library AI Google Gemini

st.set_page_config(page_title="KuCoin Auto Trading Bot", layout="wide")

# --- INISIALISASI MEMORI BOT ---
if "notified_coins" not in st.session_state: st.session_state.notified_coins = set()
if "bought_coins" not in st.session_state: st.session_state.bought_coins = set()
if "active_trades" not in st.session_state: st.session_state.active_trades = {}
if "trade_history" not in st.session_state: st.session_state.trade_history = [] 

count = st_autorefresh(interval=60000, limit=None, key="kucoin_refresh")

# --- SIDEBAR: PENGATURAN ANALISIS ---
st.sidebar.header("⚙️ Pengaturan")
timeframe = st.sidebar.selectbox("Pilih Timeframe:", ["1hour", "15min", "4hour", "1day"], index=0)
min_volume = st.sidebar.number_input("Minimum Volume (USDT):", min_value=0, value=50000, step=10000)
show_only_green = st.sidebar.checkbox("Hanya tampilkan koin Siap Entry (Hijau)", value=False)

# --- SIDEBAR: FILTER KEAMANAN & AI ---
st.sidebar.markdown("---")
st.sidebar.header("🛡️ Filter Keamanan & AI")
blacklist_input = st.sidebar.text_input("Daftar Blacklist (misal: DOGE,PEPE):", value="")
blacklist_coins = [x.strip().upper() for x in blacklist_input.split(',')] if blacklist_input else []

enable_ai_sentiment = st.sidebar.checkbox("🧠 Aktifkan Filter AI Gemini", value=True)
gemini_api_key = st.sidebar.text_input("Google Gemini API Key:", type="password", help="Dapatkan gratis di aistudio.google.com")

# --- SIDEBAR: API & AUTO-TRADING ---
st.sidebar.markdown("---")
st.sidebar.header("🤖 Mode Auto-Trading")
paper_trading = st.sidebar.checkbox("✅ Gunakan Mode Simulasi (Paper Trading)", value=True)
enable_auto_trade = st.sidebar.checkbox("Aktifkan Auto Buy & Sell", value=False)
trade_amount_usdt = st.sidebar.number_input("Jumlah Beli per Koin (USDT):", min_value=1.0, value=5.0, step=1.0)

api_key = st.sidebar.text_input("KuCoin API Key:", type="password")
api_secret = st.sidebar.text_input("KuCoin API Secret:", type="password")
api_passphrase = st.sidebar.text_input("KuCoin Passphrase:", type="password")

st.sidebar.markdown("---")
if st.session_state.trade_history:
    csv_data = pd.DataFrame(st.session_state.trade_history).to_csv(index=False).encode('utf-8')
    st.sidebar.download_button("📥 Download Riwayat Trading (CSV)", data=csv_data, file_name='riwayat_trading.csv', mime='text/csv')

mode_teks = "SIMULASI (Uang Palsu)" if paper_trading else "LIVE (Uang Asli)"
st.title("📈 KuCoin: Full Auto-Trading Bot dengan AI")
st.write(f"Status Bot: **{mode_teks}** | Otak AI: **Google Gemini** | Update ke-{count}.")

# --- FUNGSI AI SENTIMEN (GOOGLE GEMINI REAL) ---
def get_ai_sentiment(symbol, api_key_gemini):
    if not api_key_gemini:
        return {"status": "NEUTRAL", "reason": "API Key Gemini belum dimasukkan."}
    
    try:
        genai.configure(api_key=api_key_gemini)
        model = genai.GenerativeModel('gemini-1.5-flash') # Model yang cepat dan murah
        
        prompt = f"""
        Kamu adalah analis kripto handal. Coba ingat atau perkirakan sentimen pasar saat ini untuk koin {symbol}.
        Apakah secara umum fundamental dan beritanya BULLISH, BEARISH, atau NEUTRAL?
        Berikan jawaban HANYA dalam format JSON persis seperti di bawah ini, tanpa teks tambahan:
        {{"status": "BULLISH", "reason": "Satu kalimat alasan singkat maksimal 15 kata."}}
        Pastikan key "status" hanya berisi salah satu dari: BULLISH, BEARISH, NEUTRAL.
        """
        
        response = model.generate_content(prompt)
        
        # Bersihkan format JSON dari markdown jika ada (misal: ```json ... ```)
        teks_bersih = response.text.replace('```json', '').replace('```', '').strip()
        hasil_json = json.loads(teks_bersih)
        
        if hasil_json.get("status") not in ["BULLISH", "BEARISH", "NEUTRAL"]:
            hasil_json["status"] = "NEUTRAL"
            
        return hasil_json
    except Exception as e:
        return {"status": "NEUTRAL", "reason": f"Gagal membaca sentimen AI. Lanjut teknikal."}

# --- FUNGSI TRADING (CCXT) ---
def execute_auto_buy(symbol, amount_usdt, key, secret, passphrase, is_paper):
    if is_paper: return True, "Simulasi berhasil"
    try:
        exchange = ccxt.kucoin({'apiKey': key, 'secret': secret, 'password': passphrase, 'enableRateLimit': True})
        order = exchange.create_order(symbol.replace('-', '/'), type='market', side='buy', amount=None, price=None, params={'cost': amount_usdt})
        return True, order
    except Exception as e: return False, str(e)

def execute_auto_sell(symbol, amount, key, secret, passphrase, is_paper):
    if is_paper: return True, "Simulasi berhasil"
    try:
        exchange = ccxt.kucoin({'apiKey': key, 'secret': secret, 'password': passphrase, 'enableRateLimit': True})
        order = exchange.create_order(symbol.replace('-', '/'), type='market', side='sell', amount=amount)
        return True, order
    except Exception as e: return False, str(e)

def send_telegram_alert(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload)
    except: pass

# --- INDIKATOR TEKNIKAL ---
def calculate_rsi(data, window=14):
    delta = data['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    data['RSI'] = 100 - (100 / (1 + rs))
    return data

def calculate_macd(data):
    exp1 = data['close'].ewm(span=12, adjust=False).mean()
    exp2 = data['close'].ewm(span=26, adjust=False).mean()
    data['MACD'] = exp1 - exp2
    data['Signal'] = data['MACD'].ewm(span=9, adjust=False).mean()
    data['Histogram'] = data['MACD'] - data['Signal']
    return data

def calculate_bollinger_bands(data, window=20, num_std=2):
    data['SMA_20'] = data['close'].rolling(window=window).mean()
    rolling_std = data['close'].rolling(window=window).std()
    data['Upper_Band'] = data['SMA_20'] + (rolling_std * num_std)
    data['Lower_Band'] = data['SMA_20'] - (rolling_std * num_std)
    return data

def calculate_volume_breakout(data, window=20, multiplier=2.0):
    data['Vol_SMA'] = data['volume'].rolling(window=window).mean()
    data['Vol_Breakout'] = data['volume'] > (data['Vol_SMA'] * multiplier)
    return data

def get_rsi_analysis(rsi_value):
    if pd.isna(rsi_value): return "Belum cukup data", "Tunggu", "info"
    if rsi_value >= 85: return "Overbought", "Hindari", "warning"
    elif rsi_value >= 72: return "Naik Kuat", "Waspada", "warning"
    elif rsi_value >= 60: return "Momentum Sehat", "Siap Entry", "success"
    else: return "Belum Siap", "Tunggu", "info"

def simulate_trade(df, rsi_value):
    close, upper_bb, lower_bb = df['close'].iloc[-1], df['Upper_Band'].iloc[-1], df['Lower_Band'].iloc[-1]
    if pd.isna(rsi_value): return close, lower_bb, upper_bb
    sl = lower_bb if lower_bb < close else close * 0.97
    tp = upper_bb if upper_bb > close else close * 1.03
    return close, sl, tp

@st.cache_data(ttl=50) 
def get_top_gainers(limit=30, min_vol=0):
    try:
        response = requests.get("https://api.kucoin.com/api/v1/market/allTickers").json()
        if response['code'] == '200000':
            tickers = [t for t in response['data']['ticker'] if t['symbol'].endswith('-USDT') and float(t.get('volValue', 0)) >= min_vol]
            return sorted(tickers, key=lambda x: float(x.get('changeRate', 0) if x.get('changeRate') else 0), reverse=True)[:limit]
    except: pass
    return []

@st.cache_data(ttl=50)
def get_klines_indicators(symbol, tf='1hour'):
    try:
        data = requests.get(f"https://api.kucoin.com/api/v1/market/candles?symbol={symbol}&type={tf}").json()
        if data['code'] == '200000' and data['data']:
            df = pd.DataFrame(data['data'], columns=['time', 'open', 'close', 'high', 'low', 'volume', 'turnover'])
            df['time'] = pd.to_datetime(df['time'].astype(int), unit='s')
            for col in ['open', 'close', 'high', 'low']: df[col] = df[col].astype(float)
            df = df.sort_values('time').reset_index(drop=True)
            return calculate_rsi(calculate_macd(calculate_bollinger_bands(calculate_volume_breakout(df))))
    except: pass
    return pd.DataFrame()

def plot_full_chart(df, symbol, change_rate):
    if df.empty: return go.Figure()
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.02, row_heights=[0.4, 0.15, 0.2, 0.25])
    fig.add_trace(go.Scatter(x=df['time'], y=df['Upper_Band'], line=dict(color='rgba(173, 216, 230, 0.5)', width=1), name='Upper BB'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['time'], y=df['Lower_Band'], line=dict(color='rgba(173, 216, 230, 0.5)', width=1), fill='tonexty', fillcolor='rgba(173, 216, 230, 0.1)'), row=1, col=1)
    fig.add_trace(go.Candlestick(x=df['time'], open=df['open'], high=df['high'], low=df['low'], close=df['close']), row=1, col=1)
    fig.add_trace(go.Bar(x=df['time'], y=df['volume'], marker_color=['green' if r['close'] >= r['open'] else 'red' for i, r in df.iterrows()]), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['time'], y=df['RSI'], line=dict(color='purple')), row=3, col=1)
    fig.add_hline(y=60, line_dash="dot", line_color="green", row=3, col=1)
    fig.add_trace(go.Bar(x=df['time'], y=df['Histogram'], marker_color=['green' if v>=0 else 'red' for v in df['Histogram']]), row=4, col=1)
    fig.update_layout(title=f"<b>{symbol}</b>", xaxis_rangeslider_visible=False, margin=dict(l=10,r=10,t=40,b=10), height=450, showlegend=False)
    return fig

with st.spinner("Menarik data pasar & AI sedang menganalisa sentimen..."):
    top_gainers = get_top_gainers(limit=30, min_vol=min_volume)

if top_gainers:
    cols = st.columns(3)
    display_count = 0
    
    for coin in top_gainers:
        symbol = coin['symbol']
        if symbol.split('-')[0] in blacklist_coins: continue
            
        df_chart = get_klines_indicators(symbol, timeframe)
        if df_chart.empty: continue
            
        latest_close, latest_rsi, vol_breakout = df_chart['close'].iloc[-1], df_chart['RSI'].iloc[-1], df_chart['Vol_Breakout'].iloc[-1]
        interpretasi, tindakan, status_color = get_rsi_analysis(latest_rsi)
        entry_price, sl_price, tp_price = simulate_trade(df_chart, latest_rsi)
        
        trade_status_msg = ""
        prefix = "[SIMULASI] " if paper_trading else ""
        
        # LOGIKA SELL
        if enable_auto_trade and (symbol in st.session_state.active_trades):
            trade = st.session_state.active_trades[symbol]
            if latest_close > trade['highest_price']:
                trade['highest_price'] = latest_close
                if latest_close * 0.97 > trade['sl']: trade['sl'] = latest_close * 0.97
            
            if latest_close >= trade['tp'] or latest_close <= trade['sl']:
                alasan = "TAKE PROFIT ✅" if latest_close >= trade['tp'] else "STOP LOSS 🛑"
                success, response = execute_auto_sell(symbol, trade['amount'], api_key, api_secret, api_passphrase, paper_trading)
                if success:
                    pl_pct = ((latest_close - trade['entry_price']) / trade['entry_price']) * 100
                    trade_status_msg = f"{prefix}💰 BERHASIL JUAL: {symbol} ({alasan}) | P/L: {pl_pct:.2f}%"
                    st.session_state.trade_history.append({
                        "Waktu": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"), "Mode": "Simulasi" if paper_trading else "Real",
                        "Koin": symbol, "Status": alasan, "Beli": trade['entry_price'], "Jual": latest_close, "P/L (%)": round(pl_pct, 2)
                    })
                    del st.session_state.active_trades[symbol]
                else: trade_status_msg = f"❌ {prefix}GAGAL JUAL {symbol}: {response}"

        # LOGIKA BUY & CEK AI SENTIMEN (Google Gemini)
        elif status_color == "success":
            if enable_auto_trade and vol_breakout and (symbol not in st.session_state.bought_coins):
                
                ai_approved = True
                if enable_ai_sentiment:
                    sentimen = get_ai_sentiment(symbol, gemini_api_key) # Memanggil AI Sungguhan
                    if sentimen["status"] == "BEARISH":
                        ai_approved = False
                        trade_status_msg = f"🚫 BATAL BELI: AI mendeteksi sentimen buruk ({sentimen['reason']})"
                
                if ai_approved:
                    if not paper_trading and not api_key: trade_status_msg = "⚠️ API Key KuCoin belum diisi (Dibutuhkan untuk mode LIVE)!"
                    else:
                        success, response = execute_auto_buy(symbol, trade_amount_usdt, api_key, api_secret, api_passphrase, paper_trading)
                        if success:
                            st.session_state.active_trades[symbol] = {'entry_price': latest_close, 'highest_price': latest_close, 'sl': sl_price, 'tp': tp_price, 'amount': trade_amount_usdt / latest_close}
                            st.session_state.bought_coins.add(symbol)
                            trade_status_msg = f"✅ {prefix}BERHASIL BELI {symbol} di {latest_close}"
                        else: trade_status_msg = f"❌ {prefix}GAGAL BELI: {response}"
        
        # TAMPILAN KARTU
        if show_only_green and status_color != "success" and symbol not in st.session_state.active_trades: continue
            
        with cols[display_count % 3]:
            st.plotly_chart(plot_full_chart(df_chart, symbol, coin['changeRate']), use_container_width=True)
            
            # Label sentimen AI
            if enable_ai_sentiment:
                ai_res = get_ai_sentiment(symbol, gemini_api_key)
                ai_color = "🔴" if ai_res["status"] == "BEARISH" else "🟢" if ai_res["status"] == "BULLISH" else "⚪"
                st.caption(f"🧠 Sentimen Gemini: {ai_color} {ai_res['status']} - {ai_res['reason']}")
            
            if symbol in st.session_state.active_trades:
                trade = st.session_state.active_trades[symbol]
                st.info(f"**🟢 POSISI AKTIF**\n**P/L:** `{((latest_close - trade['entry_price']) / trade['entry_price']) * 100:.2f}%`\n**Entry:** `{trade['entry_price']:g}` | **TP:** `{trade['tp']:g}`")
            else:
                if status_color == "success": st.success(f"**RSI:** {latest_rsi:.2f} | **Volume Breakout:** {'🔥 YA' if vol_breakout else '❌ Tidak'}")
                else: st.info(f"**RSI:** {latest_rsi:.2f}")
            
            if trade_status_msg: st.warning(trade_status_msg)
            st.markdown("---")
        display_count += 1
