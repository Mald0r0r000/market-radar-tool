import streamlit as st
import ccxt
import requests
import pandas as pd
import altair as alt

# --- CONFIGURATION ---
st.set_page_config(page_title="Deep Market Scan", layout="centered")
st.markdown("""<style>.stApp {background-color: #0E1117;}</style>""", unsafe_allow_html=True)

# --- UTILITAIRES ---
def get_usdt_rate():
    try:
        return float(ccxt.kraken().fetch_ticker('USDT/USD')['last'])
    except:
        return 1.0

# --- FETCHERS ---
def get_depth(source):
    try:
        if source == 'Binance': # AJOUT MAJEUR
            exch = ccxt.binance()
            pair = 'BTC/USDT' # Binance est déjà en USDT
            return exch.fetch_order_book(pair, limit=1000), 1.0 # Taux 1:1
            
        elif source == 'Kraken':
            exch = ccxt.kraken()
            return exch.fetch_order_book('BTC/USD', limit=500), 'USD'
            
        elif source == 'Coinbase':
            exch = ccxt.coinbasepro()
            return exch.fetch_order_book('BTC-USD', limit=500), 'USD'
            
        elif source == 'Hyperliquid':
            url = "https://api.hyperliquid.xyz/info"
            payload = {"type": "l2Book", "coin": "BTC"}
            res = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=3).json()
            bids = [[float(l['px']), float(l['sz'])] for l in res['levels'][0]]
            asks = [[float(l['px']), float(l['sz'])] for l in res['levels'][1]]
            return {'bids': bids, 'asks': asks}, 'USD'
    except:
        return None, None

# --- CORE LOGIC ---
def scan_market(bucket_size=20): # Granularité affinée (20$ au lieu de 100$)
    usdt_rate = get_usdt_rate()
    sources = ['Binance', 'Kraken', 'Coinbase', 'Hyperliquid']
    
    global_bids = {}
    global_asks = {}
    report = []
    
    # Prix de référence (Binance pour la précision)
    try:
        ref_price = float(ccxt.binance().fetch_ticker('BTC/USDT')['last'])
    except:
        ref_price = 88000
    
    my_bar = st.progress(0, text="Deep Scan en cours...")
    
    for i, source in enumerate(sources):
        ob, currency = get_depth(source)
        if ob:
            report.append(f"✅ {source}")
            # Facteur de conversion
            rate = 1.0 if currency == 1.0 else (1.0 / usdt_rate)
            
            # --- AGREGATION ---
            # On scanne +/- 5% autour du prix (plus serré mais plus précis)
            min_price = ref_price * 0.98
            max_price = ref_price * 1.02
            
            for side, data in [('bids', ob['bids']), ('asks', ob['asks'])]:
                for price, qty in data:
                    p_usdt = float(price) * rate
                    
                    if min_price < p_usdt < max_price:
                        # Arrondi au bucket près
                        bucket = round(p_usdt / bucket_size) * bucket_size
                        
                        if side == 'bids':
                            global_bids[bucket] = global_bids.get(bucket, 0) + qty
                        else:
                            global_asks[bucket] = global_asks.get(bucket, 0) + qty
        else:
            report.append(f"❌ {source}")
        my_bar.progress((i + 1) / len(sources))
        
    my_bar.empty()
    
    # DataFrame construction
    data = []
    for p, v in global_bids.items():
        data.append({'Price': p, 'Volume': -v, 'Side': 'Support'})
    for p, v in global_asks.items():
        data.append({'Price': p, 'Volume': v, 'Side': 'Resistance'})
        
    df = pd.DataFrame(data)
    
    # Calcul des murs les plus proches
    bid_wall = max(global_bids, key=global_bids.get) if global_bids else ref_price
    ask_wall = max(global_asks, key=global_asks.get) if global_asks else ref_price
    
    return df, report, bid_wall, ask_wall, ref_price

# --- UI ---
st.title("🦅 Eagle Eye Heatmap")
st.caption("Binance + Kraken + Coinbase + Hyperliquid | Granularité: 20$")

if st.button("SCAN DEEP LIQUIDITY"):
    df, sources, bid_wall, ask_wall, spot = scan_market(bucket_size=20)
    
    st.write(" | ".join(sources))
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Prix Actuel", f"{spot:,.0f}")
    col2.metric("Gros Support", f"{bid_wall:,.0f}", delta=f"{bid_wall-spot:.0f}")
    col3.metric("Grosse Résistance", f"{ask_wall:,.0f}", delta=f"{ask_wall-spot:.0f}")

    # Chart amélioré
    base = alt.Chart(df).encode(x=alt.X('Price', scale=alt.Scale(domain=[spot*0.99, spot*1.01]))) # Zoom auto
    
    bars = base.mark_bar(size=15).encode( # Barres plus fines
        y='Volume',
        color=alt.Color('Side', scale=alt.Scale(range=['#00C853', '#D50000'])),
        tooltip=['Price', 'Volume']
    )
    
    st.altair_chart(bars, width="stretch")
    st.success(f"Spread Analyse: La liquidité est concentrée entre {bid_wall} et {ask_wall}.")
