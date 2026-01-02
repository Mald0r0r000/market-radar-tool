import streamlit as st
import ccxt
import requests
import pandas as pd
import altair as alt
import statistics
import time

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Eagle Eye V7 (Auth)", layout="centered")
st.markdown("""<style>.stApp {background-color: #0E1117;}</style>""", unsafe_allow_html=True)

# --- SYSTEME DE LOGS ---
debug_logs = []
def log(source, msg, type="INFO"):
    timestamp = time.strftime('%H:%M:%S')
    debug_logs.append(f"[{timestamp}] [{type}] **{source}**: {msg}")

# --- UTILITAIRES ---
def get_usdt_rate():
    try:
        # Récupère le prix du Tether en USD via Kraken
        return float(ccxt.kraken().fetch_ticker('USDT/USD')['last'])
    except:
        return 1.0

# --- FETCHERS (RECUPERATION DES DONNEES) ---
def fetch_depth(source):
    try:
        # --- 1. BITGET (AVEC AUTHENTIFICATION) ---
        if source == 'Bitget':
            # Vérification si les secrets existent
            if "bitget" in st.secrets:
                config = {
                    'apiKey': st.secrets["bitget"]["api_key"],
                    'secret': st.secrets["bitget"]["secret"],
                    'password': st.secrets["bitget"]["password"],
                    'enableRateLimit': True
                }
                exch = ccxt.bitget(config)
                log(source, "Mode Authentifié activé", "INFO")
            else:
                # Fallback public si pas de secrets configurés
                exch = ccxt.bitget({'enableRateLimit': True})
                log(source, "Mode Public (Pas de secrets détectés)", "WARNING")
            
            return exch.fetch_order_book('BTC/USDT', limit=200), 1.0

        # --- 2. KUCOIN ---
        elif source == 'KuCoin':
            exch = ccxt.kucoin({'enableRateLimit': True})
            return exch.fetch_order_book('BTC/USDT', limit=200), 1.0

        # --- 3. GATE.IO ---
        elif source == 'Gate.io':
            exch = ccxt.gateio({'enableRateLimit': True})
            return exch.fetch_order_book('BTC/USDT', limit=200), 1.0

        # --- 4. MEXC ---
        elif source == 'MEXC':
            exch = ccxt.mexc({'enableRateLimit': True})
            return exch.fetch_order_book('BTC/USDT', limit=200), 1.0

        # --- 5. OKX ---
        elif source == 'OKX':
            exch = ccxt.okx({'enableRateLimit': True})
            return exch.fetch_order_book('BTC/USDT', limit=200), 1.0

        # --- 6. KRAKEN ---
        elif source == 'Kraken':
            exch = ccxt.kraken()
            return exch.fetch_order_book('BTC/USD', limit=200), 'USD'
            
        # --- 7. COINBASE ---
        elif source == 'Coinbase':
            exch = ccxt.coinbase()
            return exch.fetch_order_book('BTC/USDT', limit=200), 1.0
            
        # --- 8. HYPERLIQUID ---
        elif source == 'Hyperliquid':
            url = "https://api.hyperliquid.xyz/info"
            payload = {"type": "l2Book", "coin": "BTC"}
            res = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=3).json()
            bids = [[float(l['px']), float(l['sz'])] for l in res['levels'][0]]
            asks = [[float(l['px']), float(l['sz'])] for l in res['levels'][1]]
            return {'bids': bids, 'asks': asks}, 'USD'
            
    except Exception as e:
        log(source, str(e), "ERROR")
        return None, None
    
    return None, None

# --- MOTEUR D'AGREGATION ---
def scan_max_sources(bucket_size=20): 
    # Reset des logs globaux
    global debug_logs
    debug_logs = []
    
    usdt_rate = get_usdt_rate()
    log("System", f"Taux conversion USDT/USD: {usdt_rate:.4f}", "INFO")
    
    sources = ['Bitget', 'KuCoin', 'Gate.io', 'MEXC', 'OKX', 'Kraken', 'Coinbase', 'Hyperliquid']
    
    global_bids = {}
    global_asks = {}
    report = []
    prices_collected = []
    
    # Barre de progression
    my_bar = st.progress(0, text="Initialisation du scan...")
    
    for i, source in enumerate(sources):
        my_bar.progress((i / len(sources)), text=f"Connexion à {source}...")
        
        ob, currency = fetch_depth(source)
        
        if ob and 'bids' in ob and len(ob['bids']) > 0:
            report.append(f"✅ {source}")
            log(source, "Données récupérées", "SUCCESS")
            
            # Calcul du taux de conversion pour cette source
            rate = 1.0 if currency == 1.0 else (1.0 / usdt_rate)
            
            # Récupération du prix Mid-Market pour le centrage
            try:
                best_bid = float(ob['bids'][0][0])
                best_ask = float(ob['asks'][0][0])
                mid_price = ((best_bid + best_ask) / 2) * rate
                prices_collected.append(mid_price)
            except:
                pass
            
            # Agrégation des Bids
            for entry in ob['bids']:
                try:
                    p_usdt = float(entry[0]) * rate
                    q = float(entry[1])
                    bucket = round(p_usdt / bucket_size) * bucket_size
                    global_bids[bucket] = global_bids.get(bucket, 0) + q
                except: continue
            
            # Agrégation des Asks
            for entry in ob['asks']:
                try:
                    p_usdt = float(entry[0]) * rate
                    q = float(entry[1])
                    bucket = round(p_usdt / bucket_size) * bucket_size
                    global_asks[bucket] = global_asks.get(bucket, 0) + q
                except: continue
        else:
            report.append(f"❌ {source}")
            # Si pas de log d'erreur spécifique avant, on en met un générique
            if not any(source in l and "ERROR" in l for l in debug_logs):
                log(source, "Aucune donnée renvoyée (Orderbook vide ou inaccessible)", "ERROR")
        
    my_bar.empty()
    
    # Calcul du prix de référence (Moyenne des sources valides)
    if prices_collected:
        ref_price = statistics.mean(prices_collected)
    else:
        ref_price = 88000.0 # Fallback si tout échoue
    
    # Filtrage et création du DataFrame (+/- 1.5% autour du prix)
    scan_range = ref_price * 0.015 
    min_p, max_p = ref_price - scan_range, ref_price + scan_range
    
    data = []
    # On filtre le bruit (volumes < 0.02 BTC)
    for p, v in global_bids.items():
        if min_p < p < max_p and v > 0.02: 
            data.append({'Price': p, 'Volume': -v, 'Side': 'Support'})
            
    for p, v in global_asks.items():
        if min_p < p < max_p and v > 0.02:
            data.append({'Price': p, 'Volume': v, 'Side': 'Resistance'})
            
    df = pd.DataFrame(data)
    
    # Détection des murs (Plus gros volume visible)
    bid_wall, ask_wall = ref_price, ref_price
    
    if not df.empty:
        try:
            # On cherche le min volume (car négatif) pour le support
            df_bids = df[df['Side']=='Support']
            if not df_bids.empty:
                bid_wall = df_bids.loc[df_bids['Volume'].idxmin()]['Price']
                
            # On cherche le max volume pour la résistance
            df_asks = df[df['Side']=='Resistance']
            if not df_asks.empty:
                ask_wall = df_asks.loc[df_asks['Volume'].idxmax()]['Price']
        except: 
            pass

    return df, report, bid_wall, ask_wall, ref_price

# --- INTERFACE UTILISATEUR (UI) ---

st.title("🦅 Eagle Eye V7 (Bitget Auth)")
st.caption("Agrégateur de liquidité multi-marchés | USDT Calibrated")

# Affichage de l'état des clés
if "bitget" in st.secrets:
    st.success("🔑 Clés API Bitget détectées.")
else:
    st.warning("⚠️ Clés API Bitget non trouvées (Mode public limité).")

if st.button("LANCER LE SCAN"):
    df, sources, bid_wall, ask_wall, spot = scan_max_sources(bucket_size=20)
    
    st.markdown("Sources : " + " | ".join(sources))
    
    # Panneau de logs (utile pour le debug)
    with st.expander("Voir les logs de connexion"):
        for l in debug_logs:
            if "ERROR" in l: st.error(l)
            elif "WARNING" in l: st.warning(l)
            else: st.info(l)
            
    if not df.empty:
        # Métriques
        c1, c2, c3 = st.columns(3)
        c1.metric("Prix Moyen", f"${spot:,.0f}")
        c2.metric("Gros Support", f"${bid_wall:,.0f}", delta=f"{bid_wall-spot:.0f}", delta_color="normal")
        c3.metric("Grosse Résistance", f"${ask_wall:,.0f}", delta=f"{ask_wall-spot:.0f}", delta_color="normal")
        
        # Graphique Altair
        chart = alt.Chart(df).mark_bar(size=10).encode(
            x=alt.X('Price', scale=alt.Scale(domain=[spot-1200, spot+1200]), title='Prix (USDT)'),
            y=alt.Y('Volume', title='Volume (BTC)'),
            color=alt.Color('Side', scale=alt.Scale(range=['#00C853', '#D50000']), legend=None),
            tooltip=['Price', 'Volume', 'Side']
        ).interactive()
        
        st.altair_chart(chart, width="stretch")
        
        # Code Pine Script pour TradingView
        st.code(f"""// Niveaux Eagle Eye
float ee_support = {bid_wall:.2f}
float ee_resist = {ask_wall:.2f}""", language="pine")
        
    else:
        st.error("Aucune donnée récupérée. Vérifiez les logs ci-dessus.")
