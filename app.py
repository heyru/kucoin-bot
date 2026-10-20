import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh

# Konfigurasi halaman
st.set_page_config(page_title="KuCoin Top 30 Gainers Bot", layout="wide")

# --- INISIALISASI SESSION STATE UNTUK TELEGRAM ---
# Berguna agar bot tidak mengirim notifikasi berulang untuk koin yang sama setiap menit
if "notified_coins" not in st.session_state:
    st.session_state.notified_coins = set()

# --- AUTO REFRESH ---
count = st_autorefresh(interval=60000, limit=None, key="kucoin_refresh")

# --- SIDEBAR: PENGATURAN ---
st.sidebar.header("⚙️ Pengaturan")
timeframe = st.sidebar.selectbox("Pilih Timeframe:", ["1hour", "15min", "4hour", "1day"], index=0)
min_volume = st.sidebar.number_input("Minimum Volume (USDT):", min_value=0, value=50000, step=10000)

st.sidebar.markdown("---")
st.sidebar.header("🔍 Filter Tampilan")
show_only_green = st.sidebar.checkbox("Hanya tampilkan koin Siap Entry (Hijau)", value=False)

st.sidebar.markdown("---")
st.sidebar.header("📱 Notifikasi Telegram")
telegram_token = st.sidebar.text_input("Bot Token:", type="password", help="Dapatkan dari @BotFather")
telegram_chat_id = st.sidebar.text_input("Chat ID:", help="Dapatkan dari @userinfobot")
enable_telegram = st.sidebar.checkbox("Aktifkan Notifikasi Bot", value=False)

st.title("📈 KuCoin: Auto-Scanner & Bot Simulator")
st.write(f"Menampilkan 30 koin top gainer (Volume > **{min_volume:,.0f} USDT**). Data diperbarui tiap 60 detik.")

def send_telegram_alert(token, chat_id, symbol, rsi, entry, sl, tp):
    """Mengirim pesan notifikasi ke Telegram"""
    message = (
        f"🚀 *Sinyal Entry: {symbol}*\n\n"
        f"📈 *RSI:* {rsi:.2f}\n"
        f"🎯 *Target Entry:* {entry:g} USDT\n"
        f"🛑 *Stop Loss:* {sl:g} USDT\n"
        f"✅ *Take Profit:* {tp:g} USDT\n\n"
        f"_KuCoin Auto-Scanner Bot_"
    )
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        pass

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
    macd = exp1 - exp2
    signal = macd.ewm(span=9, adjust=False).mean()
    data['MACD'] = macd
    data['Signal'] = signal
    data['Histogram'] = macd - signal
    return data

def calculate_bollinger_bands(data, window=20, num_std=2):
    data['SMA_20'] = data['close'].rolling(window=window).mean()
    rolling_std = data['close'].rolling(window=window).std()
    data['Upper_Band'] = data['SMA_20'] + (rolling_std * num_std)
    data['Lower_Band'] = data['SMA_20'] - (rolling_std * num_std)
    return data

def get_rsi_analysis(rsi_value):
    if pd.isna(rsi_value):
        return "Data belum cukup", "Tunggu data terkumpul", "info"
    if rsi_value >= 85: return "Momentum sangat ekstrem", "Hindari mengejar harga tanpa konfirmasi", "warning"
    elif rsi_value >= 72: return "Harga sudah naik kuat", "Waspadai membeli di harga puncak", "warning"
    elif rsi_value >= 55: return "Momentum naik cukup sehat", "Siap untuk Entry jika syarat lain lolos", "success"
    elif rsi_value >= 45: return "Momentum mulai membaik", "Periksa tren dan volume", "info"
    elif rsi_value >= 25: return "Momentum jual sangat kuat", "Tunggu konfirmasi pantulan", "info"
    else: return "Oversold ekstrem", "Tunggu konfirmasi pantulan kuat", "info"

def simulate_trade(df, rsi_value):
    latest_close = df['close'].iloc[-1]
    recent_low = df['low'].tail(5).min()
    if pd.isna(rsi_value): return latest_close, latest_close * 0.97, latest_close * 1.06
    if rsi_value >= 72: entry_price = latest_close * 0.95 
    elif rsi_value >= 55: entry_price = latest_close
    elif rsi_value >= 45: entry_price = latest_close * 0.98
    else: entry_price = recent_low
    if entry_price > recent_low: sl_price = recent_low * 0.995 
    else: sl_price = entry_price * 0.97 
    if sl_price >= entry_price: sl_price = entry_price * 0.97
    risk = entry_price - sl_price
    tp_price = entry_price + (risk * 2)
    return entry_price, sl_price, tp_price

@st.cache_data(ttl=50) 
def get_top_gainers(limit=30, min_vol=0):
    url = "https://api.kucoin.com/api/v1/market/allTickers"
    try:
        response = requests.get(url)
        data = response.json()
        if data['code'] == '200000':
            tickers = data['data']['ticker']
            usdt_pairs = [t for t in tickers if t['symbol'].endswith('-USDT') and float(t.get('volValue', 0)) >= min_vol]
            sorted_tickers = sorted(
                usdt_pairs, key=lambda x: float(x.get('changeRate', 0) if x.get('changeRate') else 0), reverse=True
            )
            return sorted_tickers[:limit]
    except Exception as e:
        pass
    return []

@st.cache_data(ttl=50)
def get_klines_indicators(symbol, tf='1hour'):
    url = f"https://api.kucoin.com/api/v1/market/candles?symbol={symbol}&type={tf}"
    try:
        response = requests.get(url)
        data = response.json()
        if data['code'] == '200000' and data['data']:
            df = pd.DataFrame(data['data'], columns=['time', 'open', 'close', 'high', 'low', 'volume', 'turnover'])
            df['time'] = pd.to_datetime(df['time'].astype(int), unit='s')
            for col in ['open', 'close', 'high', 'low']:
                df[col] = df[col].astype(float)
            df = df.sort_values('time').reset_index(drop=True)
            df = calculate_rsi(df, window=14)
            df = calculate_macd(df)
            df = calculate_bollinger_bands(df)
            return df
    except Exception as e:
        pass
    return pd.DataFrame()

def plot_full_chart(df, symbol, change_rate):
    if df.empty: return go.Figure()
    percent_str = f"+{float(change_rate)*100:.2f}%" if float(change_rate) > 0 else f"{float(change_rate)*100:.2f}%"
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.5, 0.25, 0.25])
    fig.add_trace(go.Scatter(x=df['time'], y=df['Upper_Band'], line=dict(color='rgba(173, 216, 230, 0.5)', width=1), name='Upper BB', hoverinfo='none'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['time'], y=df['Lower_Band'], line=dict(color='rgba(173, 216, 230, 0.5)', width=1), fill='tonexty', fillcolor='rgba(173, 216, 230, 0.1)', name='Lower BB', hoverinfo='none'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['time'], y=df['SMA_20'], line=dict(color='orange', width=1, dash='dash'), name='SMA 20'), row=1, col=1)
    fig.add_trace(go.Candlestick(x=df['time'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], increasing_line_color='green', decreasing_line_color='red', name='Harga'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['time'], y=df['RSI'], line=dict(color='purple', width=1.5), name='RSI'), row=2, col=1)
    fig.add_hline(y=72, line_dash="dot", line_color="red", row=2, col=1)
    fig.add_hline(y=25, line_dash="dot", line_color="green", row=2, col=1)
    macd_colors = ['green' if val >= 0 else 'red' for val in df['Histogram']]
    fig.add_trace(go.Bar(x=df['time'], y=df['Histogram'], marker_color=macd_colors, name='Histogram'), row=3, col=1)
    fig.add_trace(go.Scatter(x=df['time'], y=df['MACD'], line=dict(color='blue', width=1), name='MACD'), row=3, col=1)
    fig.add_trace(go.Scatter(x=df['time'], y=df['Signal'], line=dict(color='orange', width=1), name='Signal'), row=3, col=1)
    fig.update_layout(
        title=dict(text=f"<b>{symbol}</b> <span style='color:green;'>({percent_str})</span>", font=dict(size=14)),
        xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=40, b=10), height=450,
        showlegend=False, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
    )
    fig.update_xaxes(showticklabels=False, row=1, col=1)
    fig.update_xaxes(showticklabels=False, row=2, col=1)
    fig.update_yaxes(range=[0, 100], row=2, col=1)
    return fig

# --- Eksekusi Utama ---
with st.spinner("Menarik data pasar terkini..."):
    top_gainers = get_top_gainers(limit=30, min_vol=min_volume)

if not top_gainers:
    st.warning("Tidak ada koin yang memenuhi kriteria volume tersebut atau gagal memuat data.")
else:
    cols = st.columns(3)
    display_count = 0
    
    for coin in top_gainers:
        symbol = coin['symbol']
        change_rate = coin['changeRate']
        
        df_chart = get_klines_indicators(symbol, timeframe)
        if df_chart.empty:
            continue
            
        latest_close = df_chart['close'].iloc[-1]
        latest_rsi = df_chart['RSI'].iloc[-1]
        
        interpretasi, tindakan, status_color = get_rsi_analysis(latest_rsi)
        entry_price, sl_price, tp_price = simulate_trade(df_chart, latest_rsi)
        
        # --- LOGIKA TELEGRAM NOTIFIKASI ---
        if status_color == "success":
            if enable_telegram and telegram_token and telegram_chat_id:
                if symbol not in st.session_state.notified_coins:
                    send_telegram_alert(telegram_token, telegram_chat_id, symbol, latest_rsi, entry_price, sl_price, tp_price)
                    st.session_state.notified_coins.add(symbol)
        else:
            # Jika status koin sudah tidak hijau, hapus dari memori agar bisa dinotif ulang nanti
            if symbol in st.session_state.notified_coins:
                st.session_state.notified_coins.remove(symbol)
        
        # --- LOGIKA FILTER TAMPILAN ---
        if show_only_green and status_color != "success":
            continue
            
        col_idx = display_count % 3
        with cols[col_idx]:
            fig = plot_full_chart(df_chart, symbol, change_rate)
            st.plotly_chart(fig, use_container_width=True)
            
            info_text = f"""
            **Harga Saat Ini:** {latest_close:g} USDT  
            **RSI Terkini:** {latest_rsi:.2f}  
            **Status:** {interpretasi}  
            **Tindakan Bot:** {tindakan}  
            🎯 **Target Entry:** `{entry_price:g} USDT`  
            🛑 **Stop Loss (SL):** `{sl_price:g} USDT`  
            ✅ **Take Profit (TP):** `{tp_price:g} USDT` (R/R 1:2)
            """
            
            if status_color == "success": st.success(info_text)
            elif status_color == "warning": st.warning(info_text)
            else: st.info(info_text)
                
            st.markdown("---")
            
        display_count += 1
        
    if display_count == 0:
        st.info("Saat ini tidak ada koin yang memenuhi kriteria filter (Siap Entry).")