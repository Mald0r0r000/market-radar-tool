import streamlit as st
import ccxt
import requests
import pandas as pd
import altair as alt

# --- CONFIGURATION ---
st.set_page_config(page_title="Cloud Heatmap ☁️", page_icon="☁️", layout="centered")

st.markdown("""
<style>
    .stApp {background-color: #0E1117;}
    div.stButton > button {
        width: 100%; background-color: #7C4DFF; color: white; border: none; height: 3em; font-weight: bold; border-radius: 8px;
    }
    div.stButton > button:hover {background-color: #651FFF;}
</style>
""", unsafe_allow_html=True)

# --- 0. UTILITAIRES ---
def get_usdt_exchange_rate():
    """Récupère le taux USDT/USD pour la conversion"""
    try:
        # On utilise Kraken pour avoir la valeur réelle du Tether en Dollar
        ticker = ccxt.kraken().fetch_ticker('USDT/USD')
        return float(ticker['last'])
    except:
        return 1.0 # Fallback si échec (1 USDT = 1 USD)

# --- 1. FETCHERS CEX (Kraken & Coinbase) ---
def get_cex_depth(exchange_name):
    try:
        if exchange_name == 'Kraken':
            exch = ccxt.kraken()
            pair = 'BTC/USD'
        elif exchange_name == 'Coinbase':
            exch = ccxt.coinbasepro()
            pair = 'BTC-USD'
        else:
            return None
            
        # AUGMENTATION DE LA PROFONDEUR : limit=1000 au lieu de 300
        ob = exch.fetch_order_book(pair, limit=1000)
        return ob
    except:
        return None

# --- 2. FETCHER HYPERLIQUID (DEX - API REST) ---
def get_hyperliquid_depth():
    try:
        url = "https://api.hyperliquid.xyz/info"
        headers = {'Content-Type': 'application/json'}
        payload = {"type": "l2Book", "coin": "BTC"}
        
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        data = response.json()
        
        # Hyperliquid renvoie les données en USDC/USD, on traitera ça comme du USD
        bids = [[float(level['px']), float(level['sz'])] for level in data['levels'][0]]
        asks = [[float(level['px']), float(level['sz'])] for level in data['levels'][1]]
        
        return {'bids': bids, 'asks': asks}
    except:
        return None

# --- MOTEUR D'AGRÉGATION ---
def process_cloud_heatmap(spot_price_usd):
    # Récupération du taux de conversion USDT
    usdt_rate = get_usdt_exchange_rate()
    
    # Calcul du prix Spot en USDT pour centrer le graph
    spot_price_usdt = spot_price_usd / usdt_rate
    
    # Augmentation de la taille des "seaux" (buckets) car on regarde plus large
    bucket_size = 100 
    
    global_bids = {}
    global_asks = {}
    report = []
    
    sources = ['Kraken', 'Coinbase', 'Hyperliquid']
    
    my_bar = st.progress(0, text=f"Scan du marché (Taux USDT: ${usdt_rate:.4f})...")
    step = 1.0 / len(sources)
    curr = 0.0
    
    for source in sources:
        if source == 'Hyperliquid':
            ob = get_hyperliquid_depth()
        else:
            ob = get_cex_depth(source)
            
        if ob:
            report.append(f"✅ **{source}**")
            
            # --- TRAITEMENT BIDS ---
            for entry in ob['bids']:
                p_usd = float(entry[0])
                q = float(entry[1])
                
                # CONVERSION EN USDT
                p_usdt = p_usd / usdt_rate
                
                # FILTRE ÉLARGI : On prend tout ce qui est à +/- 15% (au lieu de 6%)
                if p_usdt < spot_price_usdt * 0.85: continue 
                
                bucket = (p_usdt // bucket_size) * bucket_size
                global_bids[bucket] = global_bids.get(bucket, 0) + q
                
            # --- TRAITEMENT ASKS ---
            for entry in ob['asks']:
                p_usd = float(entry[0])
                q = float(entry[1])
                
                # CONVERSION EN USDT
                p_usdt = p_usd / usdt_rate
                
                if p_usdt > spot_price_usdt * 1.15: continue 
                
                bucket = (p_usdt // bucket_size) * bucket_size
                global_asks[bucket] = global_asks.get(bucket, 0) + q
        else:
            report.append(f"❌ **{source}**")
            
        curr += step
        my_bar.progress(min(curr, 1.0))
        
    my_bar.empty()
    
    if not global_bids and not global_asks:
        return spot_price_usdt, spot_price_usdt, pd.DataFrame(), report, usdt_rate

    # Création DataFrame
    df_bids = pd.DataFrame(list(global_bids.items()), columns=['Price', 'Volume'])
    df_bids['Side'] = 'Support (Achat)'
    df_bids['Volume'] = df_bids['Volume'] * -1 # Négatif pour le graph
    
    df_asks = pd.DataFrame(list(global_asks.items()), columns=['Price', 'Volume'])
    df_asks['Side'] = 'Résistance (Vente)'
    
    # Identification des murs majeurs
    bid_wall = max(global_bids, key=global_bids.get) if global_bids else spot_price_usdt
    ask_wall = max(global_asks, key=global_asks.get) if global_asks else spot_price_usdt
    
    return bid_wall, ask_wall, pd.concat([df_bids, df_asks]), report, usdt_rate

# --- INTERFACE ---

st.title("☁️ Cloud Liquidity Heatmap (USDT)")
st.markdown("Agrégation de la liquidité convertie en **USDT** pour le trading Perp.")
st.caption("ℹ️ Données élargies (+/- 15%) et converties selon le taux USDT/USD réel.")

# Init Prix
try:
    ticker = ccxt.kraken().fetch_ticker('BTC/USD')
    spot_usd = ticker['last']
    st.metric("Prix Référence (USD - Kraken)", f"${spot_usd:,.0f}")
except:
    spot_usd = 0
    st.error("Erreur de connexion Kraken Initiale")

if st.button("LANCER LE SCAN CLOUD"):
    if spot_usd > 0:
        bid_wall, ask_wall, df, report, rate_used = process_cloud_heatmap(spot_usd)
        
        st.write(f"Sources : {' | '.join(report)} (Taux USDT: {rate_used:.4f})")
        
        col1, col2 = st.columns(2)
        col1.metric("🛡️ SUPPORT (USDT)", f"{bid_wall:,.0f}")
        col2.metric("⚔️ RESISTANCE (USDT)", f"{ask_wall:,.0f}")
        
        # Chart Altair
        c = alt.Chart(df).mark_bar().encode(
            x=alt.X('Price', scale=alt.Scale(zero=False), title='Prix (USDT)'),
            y='Volume',
            color=alt.Color('Side', scale=alt.Scale(range=['#00E676', '#FF1744'])),
            tooltip=['Price', 'Volume', 'Side']
        ).interactive()
        
        # CORRECTION DU WARNING : width="stretch"
        st.altair_chart(c, width="stretch")
        
        st.success("Données calibrées pour Bitget BTC/USDT.")
        code = f"""// --- DATA CLOUD (USDT Calibrated) ---
float cloud_bid_wall = {bid_wall:.2f}
float cloud_ask_wall = {ask_wall:.2f}"""
        st.code(code, language='pine')
