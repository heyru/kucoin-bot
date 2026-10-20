import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh
import ccxt # Library baru untuk eksekusi trading

st.set_page_config(page_title="KuCoin Top 30 Gainers Bot", layout="wide")

# --- INISIALISASI MEMORI BOT ---
if "notified_coins" not in st.session_state:
    st.session_state.notified_coins = set()
if "bought_coins" not in st.session_state:
    st.session_state.bought_coins = set()

count = st_autorefresh(interval=60000, limit=None, key="kucoin_refresh")

# --- SIDEBAR: PENGATURAN ANALISIS ---
st.sidebar.header("⚙️ Pengaturan")
timeframe = st.sidebar.selectbox("Pilih Timeframe:", ["1hour", "15min", "4hour", "1day"], index=0)
min_volume = st.sidebar.number_input("Minimum Volume (USDT):", min_value=0, value=50000, step=10000)
show_only_green = st.sidebar.checkbox("Hanya tampilkan koin Siap Entry (Hijau)", value=False)

# --- SIDEBAR: API & AUTO-TRADING ---
st.sidebar.markdown("---")
st.sidebar.header("🤖 Mode Auto-Trading (LIVE)")
st.sidebar.warning("HATI-HATI: Ini akan menggunakan saldo asli Anda.")
api_key = st.sidebar.text_input("KuCoin API Key:", type="password")
api_secret = st.sidebar.text_input("KuCoin API Secret:", type="password")
api_passphrase = st.sidebar.text_input("KuCoin Passphrase:", type="password")

enable_auto_trade = st.sidebar.checkbox("Aktifkan Auto-Buy (Beli Otomatis)", value=False)
trade_amount_usdt = st.sidebar.number_input("Jumlah Beli per Koin (USDT):", min_value=1.0, value=5.0, step=1.0)

# --- SIDEBAR: TELEGRAM ---
st.sidebar.markdown("---")
st.sidebar.header("📱 Notifikasi Telegram")
telegram_token = st.sidebar.text_input("Bot Token:", type="password")
telegram_chat_id = st.sidebar.text_input("Chat ID:")
enable_telegram = st.sidebar.checkbox("Aktifkan Notifikasi Bot", value=False)

st.title("📈 KuCoin: Auto-Scanner & Bot Simulator")
st.write(f"Menampilkan 30 koin top gainer (Volume > **{min_volume:,.0f} USDT**). Data diperbarui tiap 60 detik.")

with st.expander("💡 BACA DULU: Panduan & Peringatan Risiko Auto-Trading"):
    st.markdown("""
    ### Sistem Auto-Buy
    Jika fitur Auto-Buy diaktifkan, bot akan langsung mengeksekusi **Market Order** (membeli di harga terbaik saat ini) senilai USDT yang Anda tentukan, asalkan:
    1. Koin tersebut berstatus **Hijau (RSI >= 60)**.
    2. Koin tersebut memiliki **Volume Breakout (🔥 YA)**.
    3. Bot **belum pernah** membeli koin tersebut sejak aplikasi dibuka (agar tidak *spam buy*).
    
    *Catatan: Bot ini saat ini hanya mengeksekusi Beli (Entry). Untuk Stop Loss (SL) dan Take Profit (TP), Anda harus memasangnya secara manual (OCO Order / Stop Limit) di aplikasi KuCoin setelah pembelian berhasil.*
    """)

# --- FUNGSI EKSEKUSI AUTO-TRADING (CCXT) ---
def execute_auto_buy(symbol, amount_usdt, key, secret, passphrase):
    try:
        # Konfigurasi koneksi ke KuCoin
        exchange = ccxt.kucoin({
            'apiKey': key,
            'secret': secret,
            'password': passphrase,
            'enableRateLimit': True,
        })
        
        # Format simbol untuk CCXT (Misal: BTC-USDT menjadi BTC/USDT)
        ccxt_symbol = symbol.replace('-', '/')
        
        # Mengeksekusi Market Buy senilai jumlah USDT (menggunakan parameter 'cost'/'funds')
        order = exchange.create_order(
            symbol=ccxt_symbol,
            type='market',
            side='buy',
            amount=None, 
            price=None,
            params={'cost': amount_usdt} # KuCoin butuh ini untuk beli berdasarkan nominal USDT
        )
        return True, order
    except Exception as e:
        return False, str(e)

# --- FUNGSI TELEGRAM ---
def send_telegram_alert(token, chat_id, symbol, rsi, entry, sl, tp, vol_breakout, trade_status=""):
    vol_text = "🔥 TERDETEKSI!" if vol_breakout else "Normal"
    message = (
        f"🚀 *Sinyal Entry: {symbol}*\n\n"
        f"📈 *RSI:* {rsi:.2f}\n"
        f"📊 *Volume Breakout:* {vol_text}\n"
        f"🎯 *Target Entry:* {entry:g} USDT\n"
        f"🛑 *Trailing SL:* Mulai dari {sl:g} USDT\n"
        f"✅ *Take Profit:* {tp:g} USDT (Upper BB)\n\n"
        f"{trade_status}\n"
        f"_KuCoin Auto-Scanner Bot_"
    )
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception:
        pass

# --- FUNGSI INDIKATOR (Sama seperti sebelumnya) ---
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

def calculate_volume_breakout(data, window=20, multiplier=2.0):
    data['Vol_SMA'] = data['volume'].rolling(window=window).mean()
    data['Vol_Breakout'] = data['volume'] > (data['Vol_SMA'] * multiplier)
    return data

def run_backtest(df):
    wins, losses, in_position, tp_price, sl_price, highest_price = 0, 0, False, 0, 0, 0
    for i in range(20, len(df)):
        row = df.iloc[i]
        if in_position:
            if row['high'] > highest_price:
                highest_price = row['high']
                new_trailing_sl = highest_price * 0.97
                if new_trailing_sl > sl_price: sl_price = new_trailing_sl
            if row['high'] >= tp_price:
                wins += 1
                in_position = False
            elif row['low'] <= sl_price:
                losses += 1
                in_position = False
        else:
            prev_row = df.iloc[i-1]
            if prev_row['RSI'] < 60 and row['RSI'] >= 60: 
                in_position = True
                entry_price = row['close']
                highest_price = entry_price
                lower_bb, upper_bb = row['Lower_Band'], row['Upper_Band']
                sl_price = lower_bb if lower_bb < entry_price else entry_price * 0.97
                tp_price = upper_bb if upper_bb > entry_price else entry_price * 1.03 
    total_trades = wins + losses
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    return total_trades, wins, losses, win_rate

def get_rsi_analysis(rsi_value):
    if pd.isna(rsi_value): return "Data belum cukup", "Tunggu data terkumpul", "info"
    if rsi_value >= 85: return "Momentum ekstrem", "Hindari mengejar harga", "warning"
    elif rsi_value >= 72: return "Harga naik kuat", "Waspadai koreksi", "warning"
    elif rsi_value >= 60: return "Momentum sehat", "Siap Entry", "success"
    elif rsi_value >= 45: return "Mulai membaik", "Periksa tren & volume", "info"
    elif rsi_value >= 25: return "Jual kuat", "Tunggu pantulan", "info"
    else: return "Oversold ekstrem", "Tunggu pantulan", "info"

def simulate_trade(df, rsi_value):
    latest_close = df['close'].iloc[-1]
    latest_upper_bb = df['Upper_Band'].iloc[-1]
    latest_lower_bb = df['Lower_Band'].iloc[-1]
    if pd.isna(rsi_value): return latest_close, latest_lower_bb, latest_upper_bb
    
    if rsi_value >= 72: entry_price = latest_close * 0.95 
    elif rsi_value >= 60: entry_price = latest_close
    elif rsi_value >= 45: entry_price = latest_close * 0.98
    else: entry_price = latest_close * 0.95 
    
    initial_sl = latest_lower_bb if latest_lower_bb < entry_price else entry_price * 0.97 
    tp_price = latest_upper_bb if latest_upper_bb > entry_price else entry_price * 1.03 
    return entry_price, initial_sl, tp_price

@st.cache_data(ttl=50) 
def get_top_gainers(limit=30, min_vol=0):
    url = "https://api.kucoin.com/api/v1/market/allTickers"
    try:
        response = requests.get(url)
        data = response.json()
        if data['code'] == '200000':
            tickers = data['data']['ticker']
            usdt_pairs = [t for t in tickers if t['symbol'].endswith('-USDT') and float(t.get('volValue', 0)) >= min_vol]
            sorted_tickers = sorted(usdt_pairs, key=lambda x: float(x.get('changeRate', 0) if x.get('changeRate') else 0), reverse=True)
            return sorted_tickers[:limit]
    except Exception: pass
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
            for col in ['open', 'close', 'high', 'low']: df[col] = df[col].astype(float)
            df = df.sort_values('time').reset_index(drop=True)
            df = calculate_rsi(df, window=14)
            df = calculate_macd(df)
            df = calculate_bollinger_bands(df)
            df = calculate_volume_breakout(df)
            return df
    except Exception: pass
    return pd.DataFrame()

@st.cache_data(ttl=20)
def get_order_book(symbol, depth=5):
    url = f"https://api.kucoin.com/api/v1/market/orderbook/level2_20?symbol={symbol}"
    try:
        res = requests.get(url).json()
        if res['code'] == '200000':
            return res['data']['bids'][:depth], res['data']['asks'][:depth]
    except Exception: pass
    return [], []

def plot_full_chart(df, symbol, change_rate):
    if df.empty: return go.Figure()
    percent_str = f"+{float(change_rate)*100:.2f}%" if float(change_rate) > 0 else f"{float(change_rate)*100:.2f}%"
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.02, row_heights=[0.4, 0.15, 0.2, 0.25])
    fig.add_trace(go.Scatter(x=df['time'], y=df['Upper_Band'], line=dict(color='rgba(173, 216, 230, 0.5)', width=1), name='Upper BB', hoverinfo='none'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['time'], y=df['Lower_Band'], line=dict(color='rgba(173, 216, 230, 0.5)', width=1), fill='tonexty', fillcolor='rgba(173, 216, 230, 0.1)', name='Lower BB', hoverinfo='none'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['time'], y=df['SMA_20'], line=dict(color='orange', width=1, dash='dash'), name='SMA 20'), row=1, col=1)
    fig.add_trace(go.Candlestick(x=df['time'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], increasing_line_color='green', decreasing_line_color='red', name='Harga'), row=1, col=1)
    vol_colors = ['green' if row['close'] >= row['open'] else 'red' for idx, row in df.iterrows()]
    fig.add_trace(go.Bar(x=df['time'], y=df['volume'], marker_color=vol_colors, name='Volume'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['time'], y=df['RSI'], line=dict(color='purple', width=1.5), name='RSI'), row=3, col=1)
    fig.add_hline(y=72, line_dash="dot", line_color="red", row=3, col=1)
    fig.add_hline(y=25, line_dash="dot", line_color="green", row=3, col=1)
    macd_colors = ['green' if val >= 0 else 'red' for val in df['Histogram']]
    fig.add_trace(go.Bar(x=df['time'], y=df['Histogram'], marker_color=macd_colors, name='Histogram'), row=4, col=1)
    fig.add_trace(go.Scatter(x=df['time'], y=df['MACD'], line=dict(color='blue', width=1), name='MACD'), row=4, col=1)
    fig.add_trace(go.Scatter(x=df['time'], y=df['Signal'], line=dict(color='orange', width=1), name='Signal'), row=4, col=1)
    fig.update_layout(
        title=dict(text=f"<b>{symbol}</b> <span style='color:green;'>({percent_str})</span>", font=dict(size=14)),
        xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=40, b=10), height=550,
        showlegend=False, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
    )
    fig.update_xaxes(showticklabels=False, row=1, col=1)
    fig.update_xaxes(showticklabels=False, row=2, col=1)
    fig.update_xaxes(showticklabels=False, row=3, col=1)
    fig.update_yaxes(range=[0, 100], row=3, col=1)
    return fig


with st.spinner("Menarik data pasar & memindai sinyal..."):
    top_gainers = get_top_gainers(limit=30, min_vol=min_volume)

if not top_gainers:
    st.warning("Tidak ada koin yang memenuhi kriteria.")
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
        vol_breakout = df_chart['Vol_Breakout'].iloc[-1]
        
        interpretasi, tindakan, status_color = get_rsi_analysis(latest_rsi)
        entry_price, sl_price, tp_price = simulate_trade(df_chart, latest_rsi)
        total_trades, wins, losses, win_rate = run_backtest(df_chart)
        
        trade_status_msg = ""
        
        # --- LOGIKA AUTO-TRADING & NOTIFIKASI ---
        if status_color == "success":
            # Syarat Auto-Buy: Status Hijau (RSI sehat), Ada Volume Breakout, dan belum dibeli sebelumnya
            if enable_auto_trade and vol_breakout and (symbol not in st.session_state.bought_coins):
                if not api_key or not api_secret or not api_passphrase:
                    trade_status_msg = "⚠️ Gagal Beli: Kunci API KuCoin belum diisi di sidebar!"
                else:
                    st.toast(f"Mencoba membeli {symbol} senilai {trade_amount_usdt} USDT...")
                    success, response = execute_auto_buy(symbol, trade_amount_usdt, api_key, api_secret, api_passphrase)
                    
                    if success:
                        trade_status_msg = f"✅ BERHASIL BELI {trade_amount_usdt} USDT!"
                        st.session_state.bought_coins.add(symbol)
                    else:
                        trade_status_msg = f"❌ GAGAL BELI: {response}"
            
            # Notifikasi Telegram
            if enable_telegram and telegram_token and telegram_chat_id:
                if symbol not in st.session_state.notified_coins:
                    send_telegram_alert(telegram_token, telegram_chat_id, symbol, latest_rsi, entry_price, sl_price, tp_price, vol_breakout, trade_status_msg)
                    st.session_state.notified_coins.add(symbol)
        else:
            # Hapus dari memori notifikasi jika koin sudah tidak hijau
            if symbol in st.session_state.notified_coins:
                st.session_state.notified_coins.remove(symbol)
        
        # --- FILTER TAMPILAN ---
        if show_only_green and status_color != "success":
            continue
            
        col_idx = display_count % 3
        with cols[col_idx]:
            fig = plot_full_chart(df_chart, symbol, change_rate)
            st.plotly_chart(fig, use_container_width=True)
            
            vol_status_text = "🔥 **YA (> 2x Rata-rata)**" if vol_breakout else "❌ Normal"
            
            info_text = f"""
            **Harga:** {latest_close:g} USDT | **RSI:** {latest_rsi:.2f}  
            **Status:** {interpretasi}  
            **Tindakan Bot:** {tindakan}  
            
            📊 **Volume Breakout:** {vol_status_text}
            🏆 **Win-Rate Historis:** {win_rate:.1f}% ({wins} Win / {losses} Loss)
            
            🎯 **Entry:** `{entry_price:g}`  
            🛑 **Trailing SL:** Mulai dari `{sl_price:g}`  
            ✅ **TP:** `{tp_price:g}` (Upper BB)
            """
            
            if status_color == "success": st.success(info_text)
            elif status_color == "warning": st.warning(info_text)
            else: st.info(info_text)
            
            # Jika ada pesan status Auto-Trading, tampilkan juga
            if trade_status_msg:
                st.warning(trade_status_msg)
            
            with st.expander(f"📊 Lihat Order Book {symbol}"):
                bids, asks = get_order_book(symbol, depth=5)
                if bids and asks:
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown("**Beli (Bids) 🟢**")
                        for price, size in bids: st.write(f"`{float(price):g}` | `{float(size):g}`")
                    with c2:
                        st.markdown("**Jual (Asks) 🔴**")
                        for price, size in asks: st.write(f"`{float(price):g}` | `{float(size):g}`")
                else:
                    st.info("Data antrean sedang tidak tersedia.")
            
            st.markdown("---")
            
        display_count += 1
        
    if display_count == 0:
        st.info("Saat ini tidak ada koin yang memenuhi kriteria filter (Siap Entry - RSI > 60).")
