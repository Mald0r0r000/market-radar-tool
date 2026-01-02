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
            if "bitget" in st.secrets:
                config = {
                    'apiKey': st.secrets["bitget"]["api_key"],
                    'secret': st.secrets["bitget"]["secret"],
                    'password': st.secrets["bitget"]["password"],
                    'enableRateLimit': True
                }
                exch = ccxt.bitget(config)
            else:
                exch = ccxt.bitget({'enableRateLimit': True})
            
            return exch.fetch_order_book('BTC/USDT', limit=200), 1.0

        # --- 2. KUCOIN (CORRECTION LIMIT) ---
        elif source == 'KuCoin':
            exch = ccxt.kucoin({'enableRateLimit': True})
            # KuCoin impose limit=20 ou limit=100 strictement
            return exch.fetch_order_book('BTC/USDT', limit=100), 1.0

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

# --- MOTEUR D'AGREGATION (V9 - Buffer 300$) ---
def scan_max_sources(bucket_size=20): 
    global debug_logs
    debug_logs = []
    
    # Récupération du taux pour conversion USD -> USDT
    usdt_rate = get_usdt_rate()
    log("System", f"Taux conversion (1 USD = {1/usdt_rate:.4f} USDT)", "INFO")
    
    sources = ['Bitget', 'KuCoin', 'Gate.io', 'MEXC', 'OKX', 'Kraken', 'Coinbase', 'Hyperliquid']
    
    global_bids = {}
    global_asks = {}
    report = []
    prices_collected = []
    
    my_bar = st.progress(0, text="Scan global en cours...")
    
    for i, source in enumerate(sources):
        my_bar.progress((i / len(sources)), text=f"Analyse {source}...")
        
        ob, currency = fetch_depth(source)
        
        if ob and 'bids' in ob and len(ob['bids']) > 0:
            report.append(f"✅ {source}")
            
            # Facteur de conversion (1.0 si déjà USDT, sinon calculé)
            rate = 1.0 if currency == 1.0 else (1.0 / usdt_rate)
            
            try:
                # On convertit le prix mid-market en USDT pour la moyenne
                mid = ((float(ob['bids'][0][0]) + float(ob['asks'][0][0])) / 2) * rate
                prices_collected.append(mid)
            except: pass
            
            # --- AGRÉGATION NORMALISÉE EN USDT ---
            for entry in ob['bids']:
                try:
                    p_usdt = float(entry[0]) * rate # Conversion
                    q = float(entry[1])
                    bucket = round(p_usdt / bucket_size) * bucket_size
                    global_bids[bucket] = global_bids.get(bucket, 0) + q
                except: continue
            
            for entry in ob['asks']:
                try:
                    p_usdt = float(entry[0]) * rate # Conversion
                    q = float(entry[1])
                    bucket = round(p_usdt / bucket_size) * bucket_size
                    global_asks[bucket] = global_asks.get(bucket, 0) + q
                except: continue
        else:
            report.append(f"❌ {source}")
        
    my_bar.empty()
    
    # Prix de Référence (Moyenne de tous les échanges en USDT)
    ref_price = statistics.mean(prices_collected) if prices_collected else 88000.0
    
    # On regarde large (+/- 2000$) pour le graphique
    scan_range = 2000 
    min_p, max_p = ref_price - scan_range, ref_price + scan_range
    
    data = []
    # Filtre graphique : on enlève les toutes petites barres (< 0.05 BTC) pour la lisibilité
    for p, v in global_bids.items():
        if min_p < p < max_p and v > 0.05: 
            data.append({'Price': p, 'Volume': -v, 'Side': 'Support'})
    for p, v in global_asks.items():
        if min_p < p < max_p and v > 0.05:
            data.append({'Price': p, 'Volume': v, 'Side': 'Resistance'})
            
    df = pd.DataFrame(data)
    
    # --- LOGIQUE INTELLIGENTE DES MURS ---
    bid_wall, ask_wall = ref_price, ref_price
    
    # BUFFER AUGMENTÉ : 500$
    # On ignore tout ce qui est à moins de 300$ du prix actuel (Zone de Scalping)
    # Pour trouver les vrais murs de "Swing"
    noise_buffer = 500 
    
    if not df.empty:
        try:
            # Recherche du plus gros volume SOUS (Prix - 300$)
            df_bids = df[(df['Side']=='Support') & (df['Price'] < (ref_price - noise_buffer))]
            if not df_bids.empty:
                bid_wall = df_bids.loc[df_bids['Volume'].idxmin()]['Price']
            else:
                # Fallback : Si pas de mur loin, on prend le max local
                bid_wall = df[df['Side']=='Support']['Price'].min()

            # Recherche du plus gros volume AU-DESSUS de (Prix + 300$)
            df_asks = df[(df['Side']=='Resistance') & (df['Price'] > (ref_price + noise_buffer))]
            if not df_asks.empty:
                ask_wall = df_asks.loc[df_asks['Volume'].idxmax()]['Price']
            else:
                 ask_wall = df[df['Side']=='Resistance']['Price'].max()
                 
        except Exception as e: 
            log("System", f"Erreur murs: {e}", "WARNING")

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
