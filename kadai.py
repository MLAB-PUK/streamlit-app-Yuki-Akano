import os
os.system("pip install FlightRadar24-API")

import streamlit as st
import pandas as pd
import pydeck as pdk
from FlightRadarAPI import FlightRadar24API
from streamlit_autorefresh import st_autorefresh

# ページの設定
st.set_page_config(page_title="プロ版 リアルタイム航空機追跡", layout="wide")
st.title("✈️ 航空機追跡システム (15秒更新)")

# 画面を5秒ごとに自動更新（ミリ秒指定なので 1000ms = 1秒）
st_autorefresh(interval=15000, key="datarefresh")

fr_api = FlightRadar24API()

# --- 1. データ取得（APIサーバーへの配慮として15秒キャッシュ） ---
@st.cache_data(ttl=15)
def fetch_flight_data():
    try:
        bounds = "50,20,120,150" # 日本周辺
        return fr_api.get_flights(bounds=bounds)
    except:
        return []

@st.cache_data(ttl=3600)
def fetch_airport_data_via_api():
    try:
        dummy_country = type('Dummy', (object,), {'value': 'Japan', 'name': 'Japan'})()
        all_airports = fr_api.get_airports(countries=[dummy_country])
        japan_airports = []
        for a in all_airports:
            lat = getattr(a, 'latitude', None)
            lon = getattr(a, 'longitude', None)
            if lat is not None and lon is not None:
                japan_airports.append({
                    "空港名": str(getattr(a, 'name', 'UNKNOWN')),
                    "IATA": str(getattr(a, 'iata', '---')),
                    "ICAO": str(getattr(a, 'icao', '---')),
                    "lat": float(lat),
                    "lon": float(lon)
                })
        return pd.DataFrame(japan_airports)
    except:
        return pd.DataFrame()

# データの準備
flights_raw = fetch_flight_data()
df_airports = fetch_airport_data_via_api()

# --- 2. サイドバー設定（航空会社フィルターのみ） ---
st.sidebar.header("🛸 フィルター設定")

# 選択肢用のリストを作成（データにある航空会社を自動抽出）
all_airlines = sorted(list(set([f.airline_icao for f in flights_raw if f.airline_icao and f.airline_icao != ""])))
all_airlines.insert(0, "ALL（すべて）")

selected_airline = st.sidebar.selectbox("航空会社 (ICAOコード) で絞り込み", all_airlines)


# --- 3. 飛行機データの整形 ＆ 高度による色分け ---
flights_list = []
for f in flights_raw:
    if f.latitude and f.longitude:
        callsign = f.callsign if f.callsign and f.callsign != "" else "UNKNOWN"
        airline = f.airline_icao if f.airline_icao else "---"
        
        # 航空会社フィルタの適用
        if selected_airline != "ALL（すべて）" and airline != selected_airline:
            continue
            
        ac_code = f.aircraft_code if f.aircraft_code else "---"
        origin = f.origin_airport_iata if f.origin_airport_iata else "---"
        dest = f.destination_airport_iata if f.destination_airport_iata else "---"
        alt = f.altitude
        
        # 高度（ft）によってアイコンの色を決定
        if alt < 5000:
            icon_color = "e74c3c" # 赤（超低空・離着陸）
        elif alt < 15000:
            icon_color = "e67e22" # オレンジ（中低空）
        elif alt < 25000:
            icon_color = "f1c40f" # 黄（中高度）
        elif alt < 35000:
            icon_color = "2ecc71" # 緑（高高度・巡航）
        else:
            icon_color = "3498db" # 青（超高高度）

        ICON_URL = f"https://img.icons8.com/ios-filled/50/{icon_color}/airplane-mode-on.png"
        
        html_text = f"""
        <div style="font-family: sans-serif; padding: 5px;">
            <b style="color: #{icon_color}; font-size: 14px;">✈️ 便名: {callsign}</b> ({ac_code})<br/>
            <b>航空会社:</b> {airline}<br/>
            <b>ルート:</b> {origin} ➔ {dest}<br/>
            <b>高度:</b> {alt:,} ft / <b>速度:</b> {f.ground_speed} kt
        </div>
        """
        
        flights_list.append({
            "lat": f.latitude,
            "lon": f.longitude,
            "方位角": f.heading,
            "html_display": html_text,
            "icon_data": {"url": ICON_URL, "width": 128, "height": 128, "anchorY": 64, "anchorX": 64, "mask": False},
            "便名": callsign, "出発空港": origin, "到着空港": dest, "高度 (ft)": alt
        })

df_flights = pd.DataFrame(flights_list)

# 空港データのツールチップ整形
airport_list = []
if not df_airports.empty:
    for _, row in df_airports.iterrows():
        html_text = f"""
        <div style="font-family: sans-serif; padding: 5px;">
            <b style="color: #f1c40f; font-size: 14px;">🏢 空港名: {row['空港名']}</b><br/>
            <b>コード:</b> {row['IATA']} / {row['ICAO']}
        </div>
        """
        airport_list.append({"lat": row['lat'], "lon": row['lon'], "html_display": html_text})
df_airports_processed = pd.DataFrame(airport_list)


# --- 4. 画面表示と地図の作成 ---
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("リアルタイム・ライブマップ")
    
    # 1. レイヤーを定義（データは最初空っぽ、または現在のデータを入れる）
    airport_layer = pdk.Layer(
        type="ScatterplotLayer",
        data=df_airports_processed,
        get_position=["lon", "lat"],
        get_radius=8000,
        get_fill_color=[150, 150, 150, 150],
        pickable=True,
    )

    flight_layer = pdk.Layer(
        type="IconLayer",
        data=df_flights,       # ← ここに新しいデータが入る
        id="flight-layer",     # ★IDをつけるのが超重要！
        get_icon="icon_data",
        get_position=["lon", "lat"],
        get_size=35,
        pickable=True,
        get_angle="方位角",
        transitions={
            "get_position": {
                "duration": 1000,          # 1秒かけて滑らかに移動
                "transitionEasing": "ease-out"
            },
            "get_angle": {
                "duration": 1000,          # 旋回も1秒かけて滑らかに
                "transitionEasing": "ease-out"
            }
        } 
    )

    view_state = pdk.ViewState(latitude=35.68, longitude=139.76, zoom=4.5, pitch=0)

    tooltip_setting = {
        "html": "{html_display}",
        "style": {"backgroundColor": "rgba(20,20,20,0.9)", "color": "white"}
    }

    # 2. 地図の土台をはじめに定義する
    deck = pdk.Deck(
        layers=[airport_layer, flight_layer],
        initial_view_state=view_state,
        tooltip=tooltip_setting,
        map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"
    )

    # 3. 【ここが魔法！】st.pydeck_chartオブジェクトを変数に格納し、データだけをアップデートする
    if "map_chart" not in st.session_state:
        # 最初の一回だけ地図を描画
        st.session_state.map_chart = st.pydeck_chart(deck)
    else:
        # 2回目以降（自動更新時）は、既存の地図の飛行機データだけを上書き
        st.session_state.map_chart.pydeck_chart(deck)

with col2:
    st.subheader("現在のステータス")
    st.metric(label="画面内の航空機数", value=f"{len(df_flights)} 機")
    
    # 高度凡例の表示
    st.markdown("""
    **🎨 高度カラー凡例:**
    * <span style='color:#3498db'>■</span> 35,000 ft〜 (超高高度)
    * <span style='color:#2ecc71'>■</span> 25,000 ft〜35,000 ft (巡航)
    * <span style='color:#f1c40f'>■</span> 15,000 ft〜25,000 ft (下降/上昇)
    * <span style='color:#e67e22'>■</span> 5,000 ft〜15,000 ft (中低空)
    * <span style='color:#e74c3c'>■</span> 〜5,000 ft (離着陸・超低空)
    """, unsafe_allow_html=True)
    
    st.subheader("航空機データ一覧")
    if not df_flights.empty:
        st.dataframe(df_flights[["便名", "出発空港", "到着空港", "高度 (ft)"]], use_container_width=True)