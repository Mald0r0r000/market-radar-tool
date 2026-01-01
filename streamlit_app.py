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

# --- 1. FETCHERS CEX (Kraken & Coinbase) ---
def get_cex_depth(exchange_name, symbol='BTC/USDT'):
    try:
        # Initialisation CCXT
        if exchange_name == 'Kraken':
            exch = ccxt.kraken()
            pair = 'BTC/USD'
        elif exchange_name == 'Coinbase':
            exch = ccxt.coinbasepro()
            pair = 'BTC-USD'
        else:
            return None
            
        # Récupération carnet (500 ordres)
        ob = exch.fetch_order_book(pair, limit=300)
        return ob
    except:
        return None

# --- 2. FETCHER HYPERLIQUID (DEX - API REST) ---
def get_hyperliquid_depth():
    try:
        url = "https://api.hyperliquid.xyz/info"
        headers = {'Content-Type': 'application/json'}
        # Payload spécifique Hyperliquid
        payload = {"type": "l2Book", "coin": "BTC"}
        
        response = requests.post(url, json=payload, headers=headers, timeout=3)
        data = response.json()
        
        # Formatage pour matcher CCXT (levels = [[price, qty], ...])
        bids = [[float(level['px']), float(level['sz'])] for level in data['levels'][0]]
        asks = [[float(level['px']), float(level['sz'])] for level in data['levels'][1]]
        
        return {'bids': bids, 'asks': asks}
    except:
        return None

# --- MOTEUR D'AGRÉGATION ---
# --- MOTEUR D'AGRÉGATION (CORRIGÉ) ---
def process_cloud_heatmap(spot_price):
    bucket_size = 50 
    global_bids = {}
    global_asks = {}
    report = []
    
    # Liste des sources "Cloud Safe"
    sources = ['Kraken', 'Coinbase', 'Hyperliquid']
    
    # Barre de progression
    my_bar = st.progress(0, text="Connexion aux marchés...")
    step = 1.0 / len(sources)
    curr = 0.0
    
    for source in sources:
        if source == 'Hyperliquid':
            ob = get_hyperliquid_depth()
        else:
            ob = get_cex_depth(source)
            
        if ob:
            report.append(f"✅ **{source}**")
            
            # --- CORRECTION ICI : On lit entry[0] et entry[1] pour éviter l'erreur d'unpacking ---
            
            # Agregation Bids
            for entry in ob['bids']:
                p = float(entry[0]) # Prix
                q = float(entry[1]) # Quantité
                
                if p < spot_price * 0.94: continue # Filtre -6%
                bucket = (p // bucket_size) * bucket_size
                global_bids[bucket] = global_bids.get(bucket, 0) + q
                
            # Agregation Asks
            for entry in ob['asks']:
                p = float(entry[0]) # Prix
                q = float(entry[1]) # Quantité
                
                if p > spot_price * 1.06: continue # Filtre +6%
                bucket = (p // bucket_size) * bucket_size
                global_asks[bucket] = global_asks.get(bucket, 0) + q
        else:
            report.append(f"❌ **{source}**")
            
        curr += step
        my_bar.progress(min(curr, 1.0))
        
    my_bar.empty()
    
    # Si aucune donnée n'a été récupérée, on évite le crash suivant
    if not global_bids and not global_asks:
        return spot_price, spot_price, pd.DataFrame(), report

    # Création DataFrame
    df_bids = pd.DataFrame(list(global_bids.items()), columns=['Price', 'Volume'])
    df_bids['Side'] = 'Support (Achat)'
    df_bids['Volume'] = df_bids['Volume'] * -1
    
    df_asks = pd.DataFrame(list(global_asks.items()), columns=['Price', 'Volume'])
    df_asks['Side'] = 'Résistance (Vente)'
    
    # Max Walls (Sécurité si dict vide)
    bid_wall = max(global_bids, key=global_bids.get) if global_bids else spot_price
    ask_wall = max(global_asks, key=global_asks.get) if global_asks else spot_price
    
    return bid_wall, ask_wall, pd.concat([df_bids, df_asks]), report

# --- INTERFACE ---

st.title("☁️ Cloud Liquidity Heatmap")
st.markdown("Agrégation de la liquidité **Institutionnelle** (Coinbase/Kraken) et **DeFi Pro** (Hyperliquid).")
st.caption("ℹ️ Fonctionne sans VPN/Proxy sur Streamlit Cloud.")

# Récup prix de référence (Kraken est safe)
try:
    ticker = ccxt.kraken().fetch_ticker('BTC/USD')
    spot = ticker['last']
    st.metric("Prix Référence (Kraken)", f"${spot:,.0f}")
except:
    spot = 0
    st.error("Erreur de connexion Kraken Initiale")

if st.button("LANCER LE SCAN CLOUD"):
    if spot > 0:
        bid_wall, ask_wall, df, report = process_cloud_heatmap(spot)
        
        # Affichage des sources
        st.write("Sources connectées : " + " | ".join(report))
        
        col1, col2 = st.columns(2)
        col1.metric("🛡️ SUPPORT MAJEUR", f"${bid_wall:,.0f}")
        col2.metric("⚔️ RESISTANCE MAJEURE", f"${ask_wall:,.0f}")
        
        # Chart
        c = alt.Chart(df).mark_bar().encode(
            x=alt.X('Price', scale=alt.Scale(zero=False)),
            y='Volume',
            color=alt.Color('Side', scale=alt.Scale(range=['#00E676', '#FF1744'])),
            tooltip=['Price', 'Volume', 'Side']
        ).interactive()
        st.altair_chart(c, use_container_width=True)
        
        # Code pour TradingView
        st.success("Données prêtes.")
        code = f"""// --- DATA CLOUD (Kraken/Coinbase/Hyperliquid) ---
float cloud_bid_wall = {bid_wall}
float cloud_ask_wall = {ask_wall}"""
        st.code(code, language='pine')
