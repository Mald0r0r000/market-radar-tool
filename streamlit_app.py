import streamlit as st
import requests
import pandas as pd
import altair as alt

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(
    page_title="Market Radar 📡",
    page_icon="📡",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# --- CSS PERSONNALISÉ (STYLE "PRO") ---
st.markdown("""
<style>
    .stApp {background-color: #0E1117;}
    /* Bouton Orange pour le style "Tactique/Binance" */
    div.stButton > button {
        width: 100%; 
        background-color: #F0B90B; 
        color: black; 
        border: none; 
        height: 3em; 
        font-weight: bold; 
        border-radius: 8px;
    }
    div.stButton > button:hover {background-color: #D4A30A;}
    [data-testid="stMetricValue"] { font-size: 1.4rem; }
    h1 { color: #F0B90B; }
</style>
""", unsafe_allow_html=True)

# --- FONCTIONS API BINANCE (PUBLIQUES) ---

def get_binance_data():
    """Récupère le prix et le ratio Long/Short"""
    try:
        # 1. Prix Spot
        url_price = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
        price = float(requests.get(url_price).json()['price'])
        
        # 2. Global Long/Short Ratio (Futures)
        url_ls = "https://fapi.binance.com/fapi/v1/globalLongShortAccountRatio"
        params_ls = {'symbol': 'BTCUSDT', 'period': '5m', 'limit': 1}
        ls_data = requests.get(url_ls, params=params_ls).json()
        ratio = float(ls_data[0]['longShortRatio'])
        
        return price, ratio
    except Exception as e:
        st.error(f"Erreur API Binance Data: {e}")
        return 0, 0

def get_orderbook_analysis(spot_price):
    """Scan le carnet d'ordres pour trouver les murs"""
    try:
        # On récupère les 5000 ordres les plus proches
        url = "https://api.binance.com/api/v3/depth"
        params = {'symbol': 'BTCUSDT', 'limit': 5000}
        data = requests.get(url, params=params).json()
        
        # BUCKETING : On regroupe les ordres par paquets de 50$ pour voir les "zones"
        bucket_size = 50 
        
        # Analyse ACHATS (Bids) - Support
        bids = {}
        for price, qty in data['bids']:
            p = float(price)
            q = float(qty)
            # On ignore les ordres trop loin (-5%) pour garder le chart lisible
            if p < spot_price * 0.95: continue 
            
            bucket = (p // bucket_size) * bucket_size
            bids[bucket] = bids.get(bucket, 0) + q
            
        # Analyse VENTES (Asks) - Résistance
        asks = {}
        for price, qty in data['asks']:
            p = float(price)
            q = float(qty)
            # On ignore les ordres trop loin (+5%)
            if p > spot_price * 1.05: continue 
            
            bucket = (p // bucket_size) * bucket_size
            asks[bucket] = asks.get(bucket, 0) + q
            
        # Trouver les murs MAJEURS (Max Volume)
        bid_wall_price = max(bids, key=bids.get) if bids else 0
        ask_wall_price = max(asks, key=asks.get) if asks else 0
        
        # Préparation DataFrame pour le Graphique
        df_bids = pd.DataFrame(list(bids.items()), columns=['Price', 'Volume'])
        df_bids['Side'] = 'Achat (Support)'
        df_bids['Volume'] = df_bids['Volume'] * -1 # Négatif pour afficher vers le bas/gauche
        
        df_asks = pd.DataFrame(list(asks.items()), columns=['Price', 'Volume'])
        df_asks['Side'] = 'Vente (Résistance)'
        
        df_final = pd.concat([df_bids, df_asks])
        
        return bid_wall_price, ask_wall_price, df_final
        
    except Exception as e:
        st.error(f"Erreur API Depth: {e}")
        return 0, 0, pd.DataFrame()

# --- INTERFACE UTILISATEUR ---

st.title("📡 Market Radar")
st.markdown("**Scanner Tactique :** Liquidité Spot (Binance) & Sentiment.")

if st.button("🔄 SCANNERS LES MURS & SENTIMENT"):
    
    with st.spinner("Analyse du carnet d'ordres Binance en cours..."):
        spot, ls_ratio = get_binance_data()
        
        if spot > 0:
            bid_wall, ask_wall, df_walls = get_orderbook_analysis(spot)
            
            # --- DASHBOARD ---
            st.markdown(f"### 🎯 Prix Actuel: **${spot:,.0f}**")
            
            col1, col2, col3 = st.columns(3)
            
            col1.metric("🛡️ Mur Achat (Support)", f"${bid_wall:,.0f}", delta=f"Distance: {((bid_wall-spot)/spot)*100:.2f}%", delta_color="normal")
            col2.metric("⚔️ Mur Vente (Résistance)", f"${ask_wall:,.0f}", delta=f"Distance: {((ask_wall-spot)/spot)*100:.2f}%", delta_color="inverse")
            
            # Analyse Sentiment
            if ls_ratio > 2.0: sent_state = "🚨 Trop Bullish (Danger)"
            elif ls_ratio < 0.7: sent_state = "🚨 Trop Bearish (Danger)"
            else: sent_state = "✅ Neutre"
            
            col3.metric("⚖️ Long/Short Ratio", f"{ls_ratio:.2f}", sent_state)
            
            st.divider()
            
            # --- GRAPHIQUE ---
            st.markdown("#### 📊 Carte de Chaleur (Liquidité Immédiate)")
            
            chart = alt.Chart(df_walls).mark_bar().encode(
                x=alt.X('Price', title='Prix ($)', scale=alt.Scale(zero=False)),
                y=alt.Y('Volume', title='Volume (BTC)'),
                color=alt.Color('Side', scale=alt.Scale(domain=['Achat (Support)', 'Vente (Résistance)'], range=['#00C853', '#D50000'])),
                tooltip=['Price', 'Volume', 'Side']
            ).interactive()
            
            st.altair_chart(chart, use_container_width=True)
            
            # --- GENERATEUR DE CODE ---
            st.success("✅ Scan terminé. Copiez ces valeurs dans votre script 'Bitget H1 Master'.")
            
            code_snippet = f"""// --- DATA TACTIQUE (Market Radar) ---
float binance_bid = {bid_wall}
float binance_ask = {ask_wall}
float ls_ratio = {ls_ratio}"""
            
            st.code(code_snippet, language="pine")
            
        else:
            st.error("Impossible de récupérer les données Binance.")
