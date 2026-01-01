import streamlit as st
import ccxt
import requests
import pandas as pd
import altair as alt

# --- CONFIGURATION ---
st.set_page_config(page_title="Eagle Eye Heatmap", layout="centered")
st.markdown("""<style>.stApp {background-color: #0E1117;}</style>""", unsafe_allow_html=True)

# --- UTILITAIRES ---
def get_usdt_rate():
    try:
        # On tente de récupérer le taux, sinon 1:1 par défaut
        return float(ccxt.kraken().fetch_ticker('USDT/USD')['last'])
    except:
        return 1.0

# --- FETCHERS ---
def get_depth(source):
    try:
        if source == 'Binance':
            exch = ccxt.binance()
            # Binance nécessite souvent un rechargement des marchés pour bien mapper les symboles
            exch.load_markets() 
            pair = 'BTC/USDT'
            return exch.fetch_order_book(pair, limit=1000), 1.0 
            
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
            # Hyperliquid est propre, mais on sécurise quand même
            bids = [[float(l['px']), float(l['sz'])] for l in res['levels'][0]]
            asks = [[float(l['px']), float(l['sz'])] for l in res['levels'][1]]
            return {'bids': bids, 'asks': asks}, 'USD'
    except Exception as e:
        # Utile pour le debug: print(f"Erreur {source}: {e}")
        return None, None

# --- CORE LOGIC ---
def scan_market(bucket_size=20): 
    usdt_rate = get_usdt_rate()
    sources = ['Binance', 'Kraken', 'Coinbase', 'Hyperliquid']
    
    global_bids = {}
    global_asks = {}
    report = []
    
    # Prix de référence
    try:
        ref_price = float(ccxt.binance().fetch_ticker('BTC/USDT')['last'])
    except:
        ref_price = 88000.0 # Fallback
    
    my_bar = st.progress(0, text="Deep Scan en cours...")
    
    for i, source in enumerate(sources):
        ob, currency = get_depth(source)
        
        if ob and 'bids' in ob and 'asks' in ob:
            report.append(f"✅ {source}")
            rate = 1.0 if currency == 1.0 else (1.0 / usdt_rate)
            
            # Paramètres de scan (+/- 3% autour du prix pour garder le graph lisible)
            min_price = ref_price * 0.97
            max_price = ref_price * 1.03
            
            # --- CORRECTION DE LA BOUCLE ---
            for side, data in [('bids', ob['bids']), ('asks', ob['asks'])]:
                for entry in data:
                    # Sécurité : On prend uniquement les index 0 et 1
                    # entry peut être [Prix, Qty] ou [Prix, Qty, Timestamp]
                    try:
                        price = float(entry[0])
                        qty = float(entry[1])
                    except:
                        continue # Si format incompréhensible, on saute
                    
                    p_usdt = price * rate
                    
                    if min_price < p_usdt < max_price:
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
    # On filtre les volumes nuls ou très faibles pour nettoyer le graph
    for p, v in global_bids.items():
        if v > 0.1: data.append({'Price': p, 'Volume': -v, 'Side': 'Support'})
    for p, v in global_asks.items():
        if v > 0.1: data.append({'Price': p, 'Volume': v, 'Side': 'Resistance'})
        
    df = pd.DataFrame(data)
    
    if df.empty:
        return df, report, ref_price, ref_price, ref_price

    # Calcul des murs
    bid_wall = max(global_bids, key=global_bids.get) if global_bids else ref_price
    ask_wall = max(global_asks, key=global_asks.get) if global_asks else ref_price
    
    return df, report, bid_wall, ask_wall, ref_price

# --- UI ---
st.title("🦅 Eagle Eye Heatmap (V2)")
st.caption("Binance + Kraken + Coinbase + Hyperliquid | Granularité: 20$")

if st.button("SCAN DEEP LIQUIDITY"):
    df, sources, bid_wall, ask_wall, spot = scan_market(bucket_size=20)
    
    st.write(" | ".join(sources))
    
    if not df.empty:
        col1, col2, col3 = st.columns(3)
        col1.metric("Prix Actuel", f"{spot:,.0f}")
        col2.metric("Gros Support", f"{bid_wall:,.0f}", delta=f"{bid_wall-spot:.0f}")
        col3.metric("Grosse Résistance", f"{ask_wall:,.0f}", delta=f"{ask_wall-spot:.0f}")

        # Chart amélioré
        # Domaine X dynamique pour centrer le graph
        min_dom = spot * 0.985
        max_dom = spot * 1.015
        
        base = alt.Chart(df).encode(
            x=alt.X('Price', scale=alt.Scale(domain=[min_dom, max_dom]), title="Prix (USDT)"),
            tooltip=['Price', 'Volume', 'Side']
        )
        
        bars = base.mark_bar(size=15).encode(
            y='Volume',
            color=alt.Color('Side', scale=alt.Scale(range=['#00C853', '#D50000']))
        ).interactive()
        
        st.altair_chart(bars, width="stretch") # Correction syntaxe deprecated
        st.success(f"Spread Analyse: La liquidité est concentrée entre {bid_wall:.0f} et {ask_wall:.0f}.")
    else:
        st.warning("Aucune donnée récupérée. Vérifiez votre connexion internet ou les API.")
