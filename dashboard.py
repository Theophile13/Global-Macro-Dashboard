import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import feedparser
from datetime import datetime
import time 
from fredapi import Fred

# --- PAGE CONFIGURATION ---
st.set_page_config(layout="wide", page_title="Global Macro Dashboard")

# --- TICKER CONFIGURATION ---
YFINANCE_TICKERS = {
    # Rates & Volatility
    'US 10Y Yield': '^TNX',       
    'US 2Y Yield': '^FVX',
    'VIX': '^VIX',                
    
    # Stock Indices (Global)
    'S&P 500': '^GSPC',
    'Nasdaq 100': '^NDX',
    'Dow Jones': '^DJI',
    'Russell 2000': '^RUT',
    'CAC 40': '^FCHI',
    'DAX': '^GDAXI',
    'FTSE 100': '^FTSE',
    'Euro Stoxx 50': '^STOXX50E',
    'Nikkei 225': '^N225',
    'Hang Seng': '^HSI',
    'DXY (Dollar Index)': 'DX-Y.NYB',
    
    # Forex
    'EUR/USD': 'EURUSD=X',
    'USD/JPY': 'JPY=X',
    'GBP/USD': 'GBPUSD=X',
    
    # Commodities
    'WTI Crude Oil': 'CL=F',
    'Brent Crude Oil': 'BZ=F',
    'Nat Gas (US)': 'NG=F',
    'Gold': 'GC=F',
    'Copper': 'HG=F',
    
    # Crypto
    'Bitcoin': 'BTC-USD',
    'Ethereum': 'ETH-USD'
}

FRED_TICKERS = {
    "FED Funds Rate": "FEDFUNDS",     # OK
    "US CPI (YoY)": "CPIAUCSL",     # OK
    "ECB Deposit Rate": "ECBDFR",      # OK
    "US 10Y-2Y Spread": "T10Y2Y",      # OK
    "US NFP": "PAYEMS"               # OK (on va gérer les 2 calculs)
}

TOP_10_TICKERS = [
    "MSFT", "AAPL", "NVDA", "GOOGL", "AMZN", 
    "META", "LLY", "TSLA", "BRK-B", "AVGO"
]

# RSS Feeds
CALENDAR_RSS_URL = "https://www.forexfactory.com/calendar.php?rss=1"
NEWS_RSS_URL = 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664'

# --- DATA FETCHING FUNCTIONS ---

@st.cache_data(ttl=300)
def fetch_yfinance_data(tickers_dict):
    tickers_list = list(tickers_dict.values())
    data_hist = yf.download(tickers_list, period="1y", progress=False)
    
    if data_hist.empty:
        return pd.DataFrame() 
        
    summary = {}
    for name, ticker in tickers_dict.items():
        try:
            history_series = data_hist['Close'][ticker].dropna()
            
            if history_series.empty or len(history_series) < 67: 
                continue 

            price = history_series.iloc[-1]
            change_1d = ((price - history_series.iloc[-2]) / history_series.iloc[-2]) * 100
            change_1w = ((price - history_series.iloc[-6]) / history_series.iloc[-6]) * 100
            change_1m = ((price - history_series.iloc[-23]) / history_series.iloc[-23]) * 100
            change_3m = ((price - history_series.iloc[-67]) / history_series.iloc[-67]) * 100

            summary[name] = {
                'Price': price, 'Change 1D': change_1d, 'Change 1W': change_1w,
                'Change 1M': change_1m, 'Change 3M': change_3m, 'History': history_series
            }
        except (KeyError, IndexError):
            summary[name] = None
            
    valid_summary = {k: v for k, v in summary.items() if v is not None}
    return pd.DataFrame(valid_summary).T

# MODIFICATION ICI (fetch_fred_data)
@st.cache_data(ttl=3600)
def fetch_fred_data(tickers_dict, api_key):
    try:
        fred = Fred(api_key=api_key)
        latest_data = {}
        for name, code in tickers_dict.items():
            data = fred.get_series_latest_release(code)
            label = data.index[-1].strftime('%Y-%m') # Label commun
            
            # Calcul spécial pour NFP (variation) et CPI (variation YoY)
            if code == "PAYEMS":
                # NFP (Unité: Milliers de personnes)
                total_value = data.iloc[-1] # ex: 159,000 (milliers)
                change_value = data.iloc[-1] - data.iloc[-2] # ex: 200 (milliers)
                
                # On stocke les deux
                latest_data["US NFP Change"] = {"Value": change_value, "Date": label}
                latest_data["US NFP Total"] = {"Value": total_value, "Date": label}
                
            elif code == "CPIAUCSL":
                # Variation sur 1 an (YoY)
                latest_value = (data.iloc[-1] - data.iloc[-13]) / data.iloc[-13] * 100
                latest_data[name] = {"Value": latest_value, "Date": label}
            else:
                # Taux (FED, ECB, Spread)
                latest_value = data.iloc[-1]
                latest_data[name] = {"Value": latest_value, "Date": data.index[-1].strftime('%Y-%m-%d')}
            
        return pd.DataFrame(latest_data).T
    
    except Exception as e:
        st.error(f"Failed to load FRED data: {e}. Check API Key in secrets.")
        return pd.DataFrame()


@st.cache_data(ttl=300)
def fetch_calendar_data(rss_url):
    feed = feedparser.parse(rss_url)
    if not feed.entries:
        return pd.DataFrame(columns=["Time", "Currency", "Event", "Impact"])
    parsed_entries = []
    for item in feed.entries:
        parts = item.title.split(' | ')
        if len(parts) >= 3:
            parsed_entries.append({"Time": parts[0], "Currency": parts[1], "Event": parts[2], "Impact": parts[3] if len(parts) > 3 else ""})
    return pd.DataFrame(parsed_entries)

@st.cache_data(ttl=300)
def fetch_news_data(rss_url):
    feed = feedparser.parse(rss_url)
    return feed.entries[:5]

@st.cache_data(ttl=3600)
def fetch_stock_details(ticker_symbol):
    try:
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info
        hist = ticker.history(period="1y")
        if hist.empty:
            return None, None, 0
        perf_1y = ((hist['Close'].iloc[-1] - hist['Close'].iloc[0]) / hist['Close'].iloc[0]) * 100
        return info, hist, perf_1y
    except Exception:
        return None, None, 0

def create_sparkline_fig(data_series):
    data = data_series.dropna()
    if data.empty or len(data) < 2: return go.Figure()
    color = "green" if data.iloc[-1] > data.iloc[0] else "red"
    fill_color = 'rgba(0,255,0,0.05)' if color == 'green' else 'rgba(255,0,0,0.05)'
    fig = go.Figure(go.Scatter(y=data, mode='lines', line=dict(color=color, width=2), fill='tozeroy', fillcolor=fill_color))
    fig.update_layout(showlegend=False, height=75, xaxis_visible=False, yaxis_visible=False, yaxis_type="log",
                      margin=dict(l=0, r=0, t=0, b=0), plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
    return fig

# --- DASHBOARD DISPLAY ---

st.title("🌍 Global Macro Dashboard")
st.markdown(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

try:
    FRED_KEY = st.secrets["FRED_API_KEY"]
except KeyError:
    st.error("FRED_API_KEY not found in .streamlit/secrets.toml. FRED data will be unavailable.")
    FRED_KEY = None

with st.spinner("Loading market data (1 year)..."):
    all_data = fetch_yfinance_data(YFINANCE_TICKERS) 
    calendar_df = fetch_calendar_data(CALENDAR_RSS_URL)
    news_items = fetch_news_data(NEWS_RSS_URL)
    if FRED_KEY:
        fred_data = fetch_fred_data(FRED_TICKERS, FRED_KEY)
    else:
        fred_data = pd.DataFrame()

st.subheader("🔑 Key Metrics")
kpi_cols = st.columns(4)
# ... (le code des KPI ne change pas) ...
def display_metric(col, name, data_df):
    if name in data_df.index:
        data = data_df.loc[name]
        col.metric(label=name, value=f"{data['Price']:.2f}", delta=f"{data['Change 1D']:.2f}%")

display_metric(kpi_cols[0], 'S&P 500', all_data)
display_metric(kpi_cols[1], 'Nasdaq 100', all_data)
display_metric(kpi_cols[2], 'US 10Y Yield', all_data)
display_metric(kpi_cols[3], 'VIX', all_data)
st.divider()

col_main, col_sidebar = st.columns([2, 1])

# --- COLONNE PRINCIPALE (GAUCHE) ---
with col_main:
    
    # --- 1. Asset Overview ---
    st.subheader("📊 Asset Overview")
    
    tab_indices, tab_forex, tab_commodities, tab_crypto = st.tabs(["Indices", "Forex", "Commodities", "Crypto"])
    
    def render_tab_content(assets_list):
        for name in assets_list:
            if name in all_data.index:
                data = all_data.loc[name]
                c1, c2, c3 = st.columns([1.5, 1, 1.5])
                c1.markdown(f"**{name}**")
                c1.markdown(f"**{data['Price']:.2f}**")
                
                with c2:
                    def format_change(value, label):
                        color = "green" if value > 0 else "red"
                        return f"<span style='color:{color}; font-size: 0.9em;'>{label}: **{value:+.2f}%**</span>"
                    st.markdown(format_change(data['Change 1D'], '1D'), unsafe_allow_html=True)
                    st.markdown(format_change(data['Change 1W'], '1W'), unsafe_allow_html=True)
                    st.markdown(format_change(data['Change 1M'], '1M'), unsafe_allow_html=True)
                    st.markdown(format_change(data['Change 3M'], '3M'), unsafe_allow_html=True)

                with c3:
                    full_history = data['History']
                    tab5d, tab1m, tab1y = st.tabs(["5D", "1M", "1Y"])
                    with tab5d: st.plotly_chart(create_sparkline_fig(full_history.iloc[-5:]), use_container_width=True)
                    with tab1m: st.plotly_chart(create_sparkline_fig(full_history.iloc[-22:]), use_container_width=True)
                    with tab1y: st.plotly_chart(create_sparkline_fig(full_history), use_container_width=True)
                st.divider()

    with tab_indices:
        render_tab_content(['S&P 500', 'Nasdaq 100', 'Dow Jones', 'Russell 2000', 'CAC 40', 'DAX', 'FTSE 100', 'Euro Stoxx 50', 'Nikkei 225', 'Hang Seng', 'DXY (Dollar Index)'])
    with tab_forex:
        render_tab_content(['EUR/USD', 'USD/JPY', 'GBP/USD'])
    with tab_commodities:
        render_tab_content(['WTI Crude Oil', 'Brent Crude Oil', 'Nat Gas (US)', 'Gold', 'Copper'])
    with tab_crypto:
        render_tab_content(['Bitcoin', 'Ethereum'])

    # --- 2. Top 10 Market Caps ---
    st.divider()
    st.subheader("🌟 Top 10 US Market Caps")
    # ... (le code du Top 10 ne change pas) ...
    for i in range(0, len(TOP_10_TICKERS), 2):
        col1, col2 = st.columns(2)
        ticker1 = TOP_10_TICKERS[i]
        with col1:
            info, hist, perf_1y = fetch_stock_details(ticker1)
            if info and (hist is not None and not hist.empty):
                st.markdown(f"**{info.get('longName', ticker1)} ({ticker1})**")
                st.metric(label="Market Cap", value=f"${info.get('marketCap', 0)/1_000_000_000_000:.2f} T")
                st.metric(label="P/E Ratio", value=f"{info.get('trailingPE', 0):.2f}")
                st.metric(label="Perf. (1Y)", value=f"{perf_1y:.2f}%")
                st.plotly_chart(create_sparkline_fig(hist['Close']), use_container_width=True)
            else: st.error(f"Could not load data for {ticker1}")
        if i + 1 < len(TOP_10_TICKERS):
            ticker2 = TOP_10_TICKERS[i+1]
            with col2:
                info, hist, perf_1y = fetch_stock_details(ticker2)
                if info and (hist is not None and not hist.empty):
                    st.markdown(f"**{info.get('longName', ticker2)} ({ticker2})**")
                    st.metric(label="Market Cap", value=f"${info.get('marketCap', 0)/1_000_000_000_000:.2f} T")
                    st.metric(label="P/E Ratio", value=f"{info.get('trailingPE', 0):.2f}")
                    st.metric(label="Perf. (1Y)", value=f"{perf_1y:.2f}%")
                    st.plotly_chart(create_sparkline_fig(hist['Close']), use_container_width=True)
                else: st.error(f"Could not load data for {ticker2}")
        st.divider()

# --- COLONNE LATÉRALE (DROITE) ---
with col_sidebar:
    
    # --- 1. Agenda ---
    st.subheader("🗓️ Today's Agenda")
    # ... (le code de l'agenda ne change pas) ...
    def style_impact_cell(impact):
        if impact == '[!]': return 'color: red; font-weight: bold;'
        if impact == '[!!]': return 'color: orange;'
        return 'color: grey;'
    if calendar_df.empty:
        st.success("✅ No major events scheduled today.")
    else:
        st.dataframe(calendar_df.style.applymap(style_impact_cell, subset=['Impact']),
                       use_container_width=True, hide_index=True)
    st.markdown("[View full week calendar](https://www.forexfactory.com/calendar)", unsafe_allow_html=True)
    st.divider()

    # --- 2. News ---
    st.subheader("📰 Latest News (CNBC)")
    # ... (le code des news ne change pas) ...
    for item in news_items:
        st.markdown(f"**[{item.title}]({item.link})**")
        st.caption(f"Published: {item.published}")
        st.write("---")
        
    # --- 3. MODIFICATION ICI (Affichage FRED) ---
    st.divider()
    st.subheader("📈 Key Macro Indicators (FRED)")
    
    if fred_data.empty:
        st.warning("FRED data could not be loaded. Check API key.")
    else:
        # On trie l'index pour un affichage logique
        fred_data = fred_data.reindex([
            "FED Funds Rate", "ECB Deposit Rate", 
            "US CPI (YoY)", "US NFP Change", "US NFP Total",
            "US 10Y-2Y Spread"
        ])
        
        for index, row in fred_data.iterrows():
            if pd.isna(row['Value']):
                continue # Ne pas afficher si la donnée est NaN
                
            label = f"{index} ({row['Date']})"
            
            if index == "US NFP Change":
                # NFP Change (Unité: K)
                st.metric(label=label, value=f"{row['Value']:.0f}K")
            elif index == "US NFP Total":
                 # NFP Total (Unité: M)
                st.metric(label=label, value=f"{row['Value']/1000:.1f}M")
            else:
                # Tous les autres (CPI, Taux, Spreads)
                st.metric(label=label, value=f"{row['Value']:.2f}%")
            
            st.markdown("---") # Séparateur