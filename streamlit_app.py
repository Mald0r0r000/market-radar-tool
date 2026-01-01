import streamlit as st
import ccxt
import requests
import pandas as pd
import altair as alt
import time

# --- CONFIGURATION ---
st.set_page_config(page_title="Eagle Eye V3 🦅", layout="centered")
st.markdown("""<style>.stApp {background-color: #0E1117;}</style>""", unsafe_allow_html=True)

# --- 0. UTILITAIRES ---
def get_usdt_rate():
    try:
        return float(ccxt.kraken().fetch_ticker('USDT/USD')['last'])
    except:
        return 1.0

# --- 1. BYPASS PROXY BINANCE ---
def get_binance_via_proxy():
    """
    Tente de récupérer le carnet Binance via un proxy public
    pour contourner le géoblocage des serveurs US (Streamlit Cloud).
    """
    try:
        # On passe par un proxy CORS public souvent utilisé pour contourner les restrictions basiques
        # URL cible : API officielle Binance
        target_url = "https://api.binance.com/api/v3/depth?symbol=BTCUSDT&limit=1000"
        
        # Proxy URL
        proxy_url = f"https://corsproxy.io/?{target_url}"
        
        response = requests.get(proxy_url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            # Formatage manuel car on n'utilise pas CCXT ici
            bids = [[float(x[0]), float(x[1])] for x in data['bids']]
            asks = [[float(x[0]), float(x[1])] for x in data['asks']]
            return {'bids': bids, 'asks': asks}
        else:
            return None
    except:
        return None

# --- 2. FETCHERS MULTI-SOURCES ---
def get_depth(source):
    try:
        # --- BYBIT (Très liquide sur les Perps) ---
        if source == 'Bybit':
            exch = ccxt.bybit()
            return exch.fetch_order_book('BTC/USDT', limit=500), 1.0
            
        # --- OKX (Gros volume asiatique) ---
        elif source == 'OKX':
            exch = ccxt.okx()
            return exch.fetch_order_book('BTC/USDT', limit=500), 1.0

        # --- BINANCE (Avec tentative de Bypass) ---
        elif source == 'Binance':
            # 1. Tentative via CCXT standard (Futures)
            try:
                exch = ccxt.binanceusdm() # Essai sur les Futures (parfois non bloqué)
                return exch.fetch_order_book('BTC/USDT', limit=500), 1.0
            except:
                # 2. Fallback sur le Proxy HTTP
                ob = get_binance_via_proxy()
                if ob: return ob, 1.0
                return None, None
            
        # --- KRAKEN (Référence Fiat) ---
        elif source == 'Kraken':
            exch = ccxt.kraken()
            return exch.fetch_order_book('BTC/USD', limit=500), 'USD'
            
        # --- COINBASE (Institutionnels US) ---
        elif source == 'Coinbase':
            exch = ccxt.coinbasepro()
            return exch.fetch_order_book('BTC-USD', limit=500), 'USD'
            
        # --- HYPERLIQUID (DEX) ---
        elif source == 'Hyperliquid':
            url = "https://api.hyperliquid.xyz/info"
            payload = {"type": "l2Book", "coin": "BTC"}
            res = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=3).json()
            bids = [[float(l['px']), float(l['sz'])] for l in res['levels'][0]]
            asks = [[float(l['px']), float(l['sz'])] for l in res['levels'][1]]
            return {'bids': bids, 'asks': asks}, 'USD'
            
    except Exception:
        return None, None
    return None, None

# --- 3. CORE LOGIC ---
def scan_market(bucket_size=20): 
    usdt_rate = get_usdt_rate()
    
    # AJOUT DE BYBIT ET OKX POUR COMPENSER SI BINANCE BLOQUE
    sources = ['Binance', 'Bybit', 'OKX', 'Kraken', 'Coinbase', 'Hyperliquid']
    
    global_bids = {}
    global_asks = {}
    report = []
    
    # Prix Ref
    try:
        ref_price = float(ccxt.binance().fetch_ticker('BTC/USDT')['last'])
    except:
        try:
            ref_price = float(ccxt.kraken().fetch_ticker('USDT/USD')['last']) * usdt_rate
        except:
            ref_price = 88000.0
    
    my_bar = st.progress(0, text="Deep Scan (Proxy & Multi-Exchange)...")
    
    for i, source in enumerate(sources):
        ob, currency = get_depth(source)
        
        if ob and 'bids' in ob and len(ob['bids']) > 0:
            report.append(f"✅ {source}")
            rate = 1.0 if currency == 1.0 else (1.0 / usdt_rate)
            
            # Scan +/- 2%
            min_price = ref_price * 0.98
            max_price = ref_price * 1.02
            
            for side, data in [('bids', ob['bids']), ('asks', ob['asks'])]:
                for entry in data:
                    try:
                        p = float(entry[0])
                        q = float(entry[1])
                    except: continue
                    
                    p_usdt = p * rate
                    
                    if min_price < p_usdt < max_price:
                        bucket = round(p_usdt / bucket_size) * bucket_size
                        if side == 'bids': global_bids[bucket] = global_bids.get(bucket, 0) + q
                        else: global_asks[bucket] = global_asks.get(bucket, 0) + q
        else:
            report.append(f"❌ {source}")
        
        my_bar.progress((i + 1) / len(sources))
        time.sleep(0.1) # Petite pause pour éviter rate limit
        
    my_bar.empty()
    
    # DataFrame clean
    data = []
    for p, v in global_bids.items():
        if v > 0.05: data.append({'Price': p, 'Volume': -v, 'Side': 'Support'})
    for p, v in global_asks.items():
        if v > 0.05: data.append({'Price': p, 'Volume': v, 'Side': 'Resistance'})
        
    df = pd.DataFrame(data)
    
    if df.empty: return df, report, ref_price, ref_price, ref_price

    bid_wall = max(global_bids, key=global_bids.get) if global_bids else ref_price
    ask_wall = max(global_asks, key=global_asks.get) if global_asks else ref_price
    
    return df, report, bid_wall, ask_wall, ref_price

# --- UI ---
st.title("🦅 Eagle Eye V3 (Proxy Activated)")
st.caption("Scan global : Binance (Via Proxy) + Bybit + OKX + CEX US + DEX")

if st.button("LANCER LE SCAN OPTIMISÉ"):
    df, sources, bid_wall, ask_wall, spot = scan_market(bucket_size=20)
    
    st.write(" | ".join(sources))
    
    if not df.empty:
        col1, col2, col3 = st.columns(3)
        col1.metric("Prix Actuel", f"{spot:,.0f}")
        col2.metric("Support (Buy Wall)", f"{bid_wall:,.0f}", delta=f"{bid_wall-spot:.0f}")
        col3.metric("Résistance (Sell Wall)", f"{ask_wall:,.0f}", delta=f"{ask_wall-spot:.0f}")

        # Domaine dynamique serré
        dom_min = spot - 1500
        dom_max = spot + 1500
        
        base = alt.Chart(df).encode(
            x=alt.X('Price', scale=alt.Scale(domain=[dom_min, dom_max]), title="Prix (USDT)"),
            tooltip=['Price', 'Volume', 'Side']
        )
        
        bars = base.mark_bar(size=12).encode(
            y='Volume',
            color=alt.Color('Side', scale=alt.Scale(range=['#00C853', '#D50000']))
        ).interactive()
        
        st.altair_chart(bars, width="stretch")
        
        st.code(f"""// PINE SCRIPT LEVELS
float eagle_support = {bid_wall:.2f}
float eagle_resist = {ask_wall:.2f}""", language='pine')
        
    else:
        st.error("Aucune donnée disponible. Les API sont peut-être saturées.")
