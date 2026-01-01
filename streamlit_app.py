import streamlit as st
import ccxt
import requests
import pandas as pd
import altair as alt
import time
import statistics

# --- CONFIGURATION ---
st.set_page_config(page_title="Eagle Eye V4 (Debug)", layout="centered")
st.markdown("""<style>.stApp {background-color: #0E1117;}</style>""", unsafe_allow_html=True)

# --- LOGGING SYSTEM ---
debug_logs = []

def log(source, message, status="INFO"):
    debug_logs.append(f"[{time.strftime('%H:%M:%S')}] **{source}**: {message}")

# --- 0. UTILITAIRES & PRIX ---
def get_coingecko_price():
    """Fallback ultime pour le prix si les CEX échouent"""
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
        res = requests.get(url, timeout=3).json()
        p = res['bitcoin']['usd']
        log("CoinGecko", f"Prix récupéré: ${p}", "SUCCESS")
        return float(p)
    except Exception as e:
        log("CoinGecko", f"Échec: {str(e)}", "ERROR")
        return None

def get_usdt_rate():
    try:
        rate = float(ccxt.kraken().fetch_ticker('USDT/USD')['last'])
        return rate
    except:
        return 1.0

# --- 1. FETCHERS ---
def fetch_data(source):
    start_time = time.time()
    try:
        # --- BYBIT ---
        if source == 'Bybit':
            exch = ccxt.bybit({'enableRateLimit': True})
            ob = exch.fetch_order_book('BTC/USDT', limit=200)
            return ob, 1.0
            
        # --- OKX ---
        elif source == 'OKX':
            exch = ccxt.okx({'enableRateLimit': True})
            ob = exch.fetch_order_book('BTC/USDT', limit=200)
            return ob, 1.0

        # --- BINANCE (Proxy Hardcoded) ---
        elif source == 'Binance':
            # On tente le proxy JSON direct
            url = "https://corsproxy.io/?https://api.binance.com/api/v3/depth?symbol=BTCUSDT&limit=500"
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                # Reconstruction format CCXT
                bids = [[float(x[0]), float(x[1])] for x in data['bids']]
                asks = [[float(x[0]), float(x[1])] for x in data['asks']]
                return {'bids': bids, 'asks': asks}, 1.0
            else:
                raise Exception(f"Proxy Status {res.status_code}")
            
        # --- KRAKEN ---
        elif source == 'Kraken':
            exch = ccxt.kraken()
            ob = exch.fetch_order_book('BTC/USD', limit=500)
            return ob, 'USD'
            
        # --- COINBASE (Updated to V3) ---
        elif source == 'Coinbase':
            exch = ccxt.coinbase() # Nouvelle API standard
            ob = exch.fetch_order_book('BTC/USDT', limit=200) # Coinbase a maintenant USDT
            return ob, 1.0
            
        # --- HYPERLIQUID ---
        elif source == 'Hyperliquid':
            url = "https://api.hyperliquid.xyz/info"
            payload = {"type": "l2Book", "coin": "BTC"}
            res = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=4).json()
            bids = [[float(l['px']), float(l['sz'])] for l in res['levels'][0]]
            asks = [[float(l['px']), float(l['sz'])] for l in res['levels'][1]]
            return {'bids': bids, 'asks': asks}, 'USD'
            
    except Exception as e:
        log(source, f"Erreur: {str(e)}", "ERROR")
        return None, None
    
    return None, None

# --- 2. CORE LOGIC ---
def scan_market_v4(bucket_size=20): 
    # Reset logs
    global debug_logs
    debug_logs = []
    
    usdt_rate = get_usdt_rate()
    log("System", f"Taux USDT/USD: {usdt_rate:.4f}")
    
    sources = ['Hyperliquid', 'Kraken', 'OKX', 'Binance', 'Bybit', 'Coinbase']
    
    global_bids = {}
    global_asks = {}
    report = []
    prices_collected = []
    
    my_bar = st.progress(0, text="Initialisation...")
    
    # ÉTAPE 1 : RÉCUPÉRATION DATA
    for i, source in enumerate(sources):
        my_bar.progress((i / len(sources)), text=f"Scan {source}...")
        ob, currency = fetch_data(source)
        
        if ob and 'bids' in ob and len(ob['bids']) > 0:
            report.append(f"✅ {source}")
            log(source, f"Data OK ({len(ob['bids'])} bids)", "SUCCESS")
            
            # Détermination du taux
            rate = 1.0 if currency == 1.0 else (1.0 / usdt_rate)
            
            # On stocke le prix mid-market pour calculer la référence plus tard
            try:
                best_bid = float(ob['bids'][0][0]) * rate
                best_ask = float(ob['asks'][0][0]) * rate
                mid_price = (best_bid + best_ask) / 2
                prices_collected.append(mid_price)
            except:
                pass
            
            # Stockage temporaire des données brutes
            ob['rate_used'] = rate
            
            # --- AGREGATION IMMEDIATE ---
            # Note: On ne filtre pas encore par prix min/max pour éviter le bug "Ref Price"
            # On stocke tout, on filtrera après avoir trouvé le prix moyen
            
            for side, data in [('bids', ob['bids']), ('asks', ob['asks'])]:
                for entry in data:
                    try:
                        p_usdt = float(entry[0]) * rate
                        q = float(entry[1])
                        bucket = round(p_usdt / bucket_size) * bucket_size
                        
                        if side == 'bids':
                            global_bids[bucket] = global_bids.get(bucket, 0) + q
                        else:
                            global_asks[bucket] = global_asks.get(bucket, 0) + q
                    except: continue
                    
        else:
            report.append(f"❌ {source}")
    
    my_bar.empty()
    
    # ÉTAPE 2 : CALCUL PRIX REFERENCE ROBUSTE
    if prices_collected:
        ref_price = statistics.mean(prices_collected)
        log("System", f"Prix Référence calculé (Moyenne): ${ref_price:,.0f}")
    else:
        # Fallback ultime
        log("System", "Aucun prix CEX disponible, appel CoinGecko...")
        ref_price = get_coingecko_price()
        if not ref_price:
            ref_price = 88000.0 # Hardcoded fail-safe
            
    # ÉTAPE 3 : FILTRAGE ET DATAFRAME
    min_price = ref_price - 1500
    max_price = ref_price + 1500
    
    final_data = []
    
    for p, v in global_bids.items():
        if min_price < p < max_price and v > 0.05:
            final_data.append({'Price': p, 'Volume': -v, 'Side': 'Support'})
            
    for p, v in global_asks.items():
        if min_price < p < max_price and v > 0.05:
            final_data.append({'Price': p, 'Volume': v, 'Side': 'Resistance'})
            
    df = pd.DataFrame(final_data)
    
    # Murs
    bid_wall = ref_price
    ask_wall = ref_price
    
    if not df.empty:
        # Recherche des murs DANS la zone filtrée
        df_bids = df[df['Side'] == 'Support']
        df_asks = df[df['Side'] == 'Resistance']
        
        if not df_bids.empty:
            bid_wall = df_bids.loc[df_bids['Volume'].idxmin()]['Price'] # Min car volume négatif
        if not df_asks.empty:
            ask_wall = df_asks.loc[df_asks['Volume'].idxmax()]['Price']

    return df, report, bid_wall, ask_wall, ref_price

# --- UI ---
st.title("🦅 Eagle Eye V4 (Debug Edition)")

if st.button("LANCER LE DIAGNOSTIC"):
    df, sources, bid_wall, ask_wall, spot = scan_market_v4(bucket_size=20)
    
    st.write(" | ".join(sources))
    
    # DEBUG EXPANDER
    with st.expander("📝 Voir les Logs Détaillés (Pourquoi ça plante ?)", expanded=True):
        for line in debug_logs:
            if "ERROR" in line or "❌" in line:
                st.markdown(f":red[{line}]")
            elif "SUCCESS" in line:
                st.markdown(f":green[{line}]")
            else:
                st.write(line)

    if not df.empty:
        col1, col2, col3 = st.columns(3)
        col1.metric("Prix Ref", f"{spot:,.0f}")
        col2.metric("Support", f"{bid_wall:,.0f}")
        col3.metric("Résistance", f"{ask_wall:,.0f}")
        
        base = alt.Chart(df).encode(
            x=alt.X('Price', scale=alt.Scale(domain=[spot-1200, spot+1200]), title="Prix (USDT)"),
            tooltip=['Price', 'Volume', 'Side']
        )
        
        bars = base.mark_bar(size=15).encode(
            y='Volume',
            color=alt.Color('Side', scale=alt.Scale(range=['#00C853', '#D50000']))
        ).interactive()
        
        st.altair_chart(bars, width="stretch")
    else:
        st.error("Données vides malgré le scan. Vérifiez les logs ci-dessus.")
