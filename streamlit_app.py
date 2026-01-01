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

# --- CSS PERSONNALISÉ ---
st.markdown("""
<style>
    .stApp {background-color: #0E1117;}
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
</style>
""", unsafe_allow_html=True)

# --- MOTEUR DE DONNÉES (HYBRIDE BINANCE / KRAKEN) ---

def get_crypto_data():
    """
    Tente de récupérer les données sur Binance.
    En cas de blocage (IP US Streamlit), bascule automatiquement sur Kraken.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    # 1. TENTATIVE BINANCE (Priorité 1)
    try:
        # Prix
        url_price = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
        resp_price = requests.get(url_price, headers=headers, timeout=2)
        resp_price.raise_for_status() # Vérifie si erreur 403/404
        price = float(resp_price.json()['price'])
        
        # Ratio L/S (Uniquement dispo sur Binance Futures)
        url_ls = "https://fapi.binance.com/fapi/v1/globalLongShortAccountRatio"
        params_ls = {'symbol': 'BTCUSDT', 'period': '5m', 'limit': 1}
        try:
            ls_data = requests.get(url_ls, params=params_ls, headers=headers, timeout=2).json()
            ratio = float(ls_data[0]['longShortRatio'])
        except:
            ratio = 0 # Si bloqué sur Futures
            
        # Carnet d'ordres
        url_depth = "https://api.binance.com/api/v3/depth"
        params_depth = {'symbol': 'BTCUSDT', 'limit': 5000}
        depth_data = requests.get(url_depth, params=params_depth, headers=headers, timeout=2).json()
        
        # Si on arrive ici, c'est que Binance fonctionne
        return process_depth_data(depth_data, price, ratio, "Binance")

    except Exception as e:
        # 2. FALLBACK KRAKEN (Priorité 2 - Compatible US Servers)
        # Si Binance échoue, on utilise Kraken silencieusement
        try:
            # Prix Kraken (Pair XBTUSD)
            url_k_price = "https://api.kraken.com/0/public/Ticker?pair=XBTUSD"
            resp_k = requests.get(url_k_price, headers=headers, timeout=2).json()
            # Kraken API structure: result -> XXBTZUSD -> c -> [0]
            price = float(resp_k['result']['XXBTZUSD']['c'][0])
            
            # Carnet Kraken
            url_k_depth = "https://api.kraken.com/0/public/Depth?pair=XBTUSD&count=500"
            depth_k = requests.get(url_k_depth, headers=headers, timeout=2).json()
            # Mapping au format standard
            raw_depth = {
                'bids': depth_k['result']['XXBTZUSD']['bids'],
                'asks': depth_k['result']['XXBTZUSD']['asks']
            }
            
            return process_depth_data(raw_depth, price, 0, "Kraken (Relais)")
            
        except Exception as k_e:
            st.error(f"Échec critique (Binance & Kraken bloqués): {k_e}")
            return 0, 0, 0, 0, pd.DataFrame(), "Erreur"

def process_depth_data(data, spot_price, ratio, source_name):
    """Traite les données brutes (Binance ou Kraken) pour faire les murs"""
    
    bucket_size = 50 
    
    # Bids (Achats)
    bids = {}
    for entry in data['bids']:
        p = float(entry[0])
        q = float(entry[1])
        if p < spot_price * 0.95: continue 
        bucket = (p // bucket_size) * bucket_size
        bids[bucket] = bids.get(bucket, 0) + q
        
    # Asks (Ventes)
    asks = {}
    for entry in data['asks']:
        p = float(entry[0])
        q = float(entry[1])
        if p > spot_price * 1.05: continue 
        bucket = (p // bucket_size) * bucket_size
        asks[bucket] = asks.get(bucket, 0) + q
        
    # Max Walls
    bid_wall = max(bids, key=bids.get) if bids else spot_price
    ask_wall = max(asks, key=asks.get) if asks else spot_price
    
    # DataFrame
    df_bids = pd.DataFrame(list(bids.items()), columns=['Price', 'Volume'])
    df_bids['Side'] = 'Achat (Support)'
    df_bids['Volume'] = df_bids['Volume'] * -1 
    
    df_asks = pd.DataFrame(list(asks.items()), columns=['Price', 'Volume'])
    df_asks['Side'] = 'Vente (Résistance)'
    
    df_final = pd.concat([df_bids, df_asks])
    
    return spot_price, ratio, bid_wall, ask_wall, df_final, source_name

# --- INTERFACE ---

st.title("📡 Market Radar")
st.markdown("**Scanner Tactique :** Liquidité Spot & Sentiment.")

if st.button("🔄 SCANNERS LES MURS & SENTIMENT"):
    
    with st.spinner("Connexion aux flux de données..."):
        spot, ls_ratio, bid_wall, ask_wall, df_walls, source = get_crypto_data()
        
        if spot > 0:
            # Indicateur de Source (Pour savoir si on est sur Binance ou Kraken)
            if "Kraken" in source:
                st.warning(f"⚠️ Binance bloqué (IP Cloud). Données récupérées via **{source}**.")
            else:
                st.success(f"✅ Données en direct de **{source}**.")
            
            st.markdown(f"### 🎯 Prix Actuel: **${spot:,.0f}**")
            
            # Métriques
            col1, col2, col3 = st.columns(3)
            col1.metric("🛡️ Mur Achat", f"${bid_wall:,.0f}", delta=f"{((bid_wall-spot)/spot)*100:.2f}%", delta_color="normal")
            col2.metric("⚔️ Mur Vente", f"${ask_wall:,.0f}", delta=f"{((ask_wall-spot)/spot)*100:.2f}%", delta_color="inverse")
            
            # Ratio (Si dispo)
            if ls_ratio > 0:
                state = "Trop Bullish" if ls_ratio > 2.0 else ("Trop Bearish" if ls_ratio < 0.7 else "Neutre")
                col3.metric("⚖️ L/S Ratio", f"{ls_ratio:.2f}", state)
            else:
                col3.metric("⚖️ L/S Ratio", "N/A", "Non dispo sur Kraken")

            st.divider()
            
            # Graphique
            st.markdown("#### 📊 Carte de Chaleur (Liquidité Immédiate)")
            chart = alt.Chart(df_walls).mark_bar().encode(
                x=alt.X('Price', title='Prix ($)', scale=alt.Scale(zero=False)),
                y=alt.Y('Volume', title='Volume (BTC)'),
                color=alt.Color('Side', scale=alt.Scale(domain=['Achat (Support)', 'Vente (Résistance)'], range=['#00C853', '#D50000'])),
                tooltip=['Price', 'Volume', 'Side']
            ).interactive()
            st.altair_chart(chart, use_container_width=True)
            
            # Code
            st.success("✅ Code généré pour 'Bitget H1 Master'.")
            code_snippet = f"""// --- DATA TACTIQUE ({source}) ---
float binance_bid = {bid_wall}
float binance_ask = {ask_wall}
float ls_ratio = {ls_ratio if ls_ratio > 0 else 1.0}"""
            st.code(code_snippet, language="pine")
            
        else:
            st.error("Impossible de récupérer les données.")
