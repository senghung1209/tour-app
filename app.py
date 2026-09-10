import streamlit as st
import pandas as pd
import datetime
import re
import os
import json
import base64
import time
import math
import struct
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
import streamlit.components.v1 as components
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="旅游团智能比价助手", page_icon="✈️", layout="wide")

# 💎 连接 Google Sheets 数据库（原生 TOML 读取 + 强制换行修复）
@st.cache_resource
def init_google_sheets_connection():
    try:
        scope = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        gcp_secrets = dict(st.secrets["gcp_service_account"])
        if "private_key" in gcp_secrets:
            gcp_secrets["private_key"] = gcp_secrets["private_key"].replace("\\n", "\n")
            
        creds = Credentials.from_service_account_info(gcp_secrets, scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open("TourPriceDB").sheet1
        return sheet
    except Exception as e:
        st.error(f"连接 Google Sheets 失败，请检查配置: {e}")
        return None

sheet_db = init_google_sheets_connection()

def load_cloud_data():
    if sheet_db is None:
        return []
    try:
        records = sheet_db.get_all_records()
        return records if isinstance(records, list) else []
    except Exception as e:
        st.error(f"读取云端数据失败: {e}")
        return []

def save_cloud_data(data_list):
    if sheet_db is None:
        return
    try:
        sheet_db.clear()
        header = [
            "agency", "destination", "tour_code", "title", 
            "departure_location", "departure_dates", "price_numeric", 
            "price_text", "shopping_status", "holiday_status", "over_days", "holiday_name"
        ]
        rows = [header]
        for item in data_list:
            row = [
                item.get("agency", ""),
                item.get("destination", ""),
                item.get("tour_code", ""),
                item.get("title", ""),
                item.get("departure_location", ""),
                item.get("departure_dates", ""),
                item.get("price_numeric", 0),
                item.get("price_text", ""),
                item.get("shopping_status", ""),
                item.get("holiday_status", ""),
                item.get("over_days", 0),
                item.get("holiday_name", "")
            ]
            rows.append(row)
        sheet_db.update(rows)
    except Exception as e:
        st.error(f"保存到云端失败: {e}")

st.sidebar.header("📌 系统工作模式")
work_mode = st.sidebar.radio("请选择空间类型", ["🌐 公共共享模式 (多人实时同步)", "👤 独立个人模式 (私有独立沙盒)"])

if work_mode == "🌐 公共共享模式 (多人实时同步)":
    if "shared_tour_data" not in st.session_state:
        st.session_state.shared_tour_data = load_cloud_data()
    active_data = st.session_state.shared_tour_data
else:
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🔐 私人专属代号设置")
    private_passcode = st.sidebar.text_input("输入你的专属代号/密码", value="my_secret_space", type="default")
    private_key_state = f"private_data_{private_passcode}"
    if private_key_state not in st.session_state:
        st.session_state[private_key_state] = load_cloud_data()
    active_data = st.session_state[private_key_state]

st.title("✈️ 旅游团智能比价助手 (Google Sheets 云端永久存储版)")

@st.cache_resource
def get_loud_wav_base64():
    sample_rate = 22050
    tones = [(850, 0.18), (0, 0.05), (1200, 0.35)]
    raw_samples = bytearray()
    for freq, duration in tones:
        n_samples = int(sample_rate * duration)
        for i in range(n_samples):
            if freq == 0:
                val = 128
            else:
                val = int(128 + 118 * math.sin(2 * math.pi * freq * i / sample_rate))
                val = max(0, min(255, val))
            raw_samples.append(val)
            
    data_size = len(raw_samples)
    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF', 36 + data_size, b'WAVE', b'fmt ',
        16, 1, 1, sample_rate, sample_rate, 1, 8, b'data', data_size
    )
    return base64.b64encode(header + raw_samples).decode('ascii')

LOUD_WAV_B64 = get_loud_wav_base64()

native_audio_html = """
<div style="background: #eff6ff; border: 1.5px solid #3b82f6; border-radius: 8px; padding: 12px; margin-bottom: 15px;">
    <div style="font-weight: bold; font-size: 14px; color: #1e40af; margin-bottom: 5px;">
        🔊 提示音与通知设置
    </div>
    <audio id="real_alert_sound" preload="auto">
        <source src="data:audio/wav;base64,AUDIO_PLACEHOLDER" type="audio/wav">
    </audio>
    <button id="direct_play_btn" style="background: #2563eb; color: white; border: none; padding: 10px 20px; border-radius: 6px; font-weight: bold; font-size: 14px; width: 100%; cursor: pointer;">
        👉 点击开启完成提示音
    </button>
</div>
<script>
document.getElementById('direct_play_btn').addEventListener('click', function(e) {
    e.preventDefault();
    if ("vibrate" in navigator) { navigator.vibrate([200, 100, 200]); }
    var audio = document.getElementById('real_alert_sound');
    if (audio) { audio.currentTime = 0; audio.volume = 1.0; audio.play().catch(function() {}); }
});
</script>
""".replace("AUDIO_PLACEHOLDER", LOUD_WAV_B64)

components.html(native_audio_html, height=140)

def trigger_play_on_done(count_num):
    js = """
    <audio id="done_alert_sound" autoplay>
        <source src="data:audio/wav;base64,AUDIO_PLACEHOLDER" type="audio/wav">
    </audio>
    <script>
    (function() {
        document.title = "🔔【分析完成! 共COUNT_PLACEHOLDER项】旅游比价";
        if ("vibrate" in navigator) { navigator.vibrate([250, 100, 250, 100, 400]); }
        var aud = document.getElementById('done_alert_sound');
        if (aud) { aud.play().catch(function(){}); }
    })();
    </script>
    """.replace("AUDIO_PLACEHOLDER", LOUD_WAV_B64).replace("COUNT_PLACEHOLDER", str(count_num))
    components.html(js, height=0)

OFFICIAL_HOLIDAYS = [
    (datetime.date(2026, 3, 20), datetime.date(2026, 3, 29), "2026 第一学期假期 (3月)"),
    (datetime.date(2026, 5, 22), datetime.date(2026, 6, 7), "2026 年中假期 (5/6月)"),
    (datetime.date(2026, 8, 28), datetime.date(2026, 9, 6), "2026 第二学期假期 (8/9月)"),
    (datetime.date(2026, 12, 4), datetime.date(2027, 1, 3), "2026 学年末大假期 (12月/1月)"),
    (datetime.date(2027, 1, 23), datetime.date(2027, 2, 16), "2027 农历新年与跨年假期")
]

API_KEYS = []
try:
    for k, v in st.secrets.items():
        if k.startswith("GEMINI_API_KEY") and v:
            clean_v = str(v).strip()
            if clean_v and clean_v not in API_KEYS:
                API_KEYS.append(clean_v)
except Exception:
    pass

PRIMARY_MODEL = "gemini-3.5-flash"
BACKUP_MODEL = "gemini-3.1-flash-lite"

if "key_index_counter" not in st.session_state:
    st.session_state.key_index_counter = 0

def get_next_api_key():
    if not API_KEYS:
        return ""
    idx = st.session_state.key_index_counter % len(API_KEYS)
    st.session_state.key_index_counter += 1
    return API_KEYS[idx]

def extract_tour_days(title_str):
    m = re.search(r'(\d+)\s*(?:天|D|d)', str(title_str))
    return int(m.group(1)) if m else 7

def evaluate_holiday_fit(departure_date_str, duration_days):
    matches = re.findall(r'(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})', str(departure_date_str))
    if not matches:
        return 'none', 0, ""

    d, mth, y = matches[0]
    try:
        d, mth, y = int(d), int(mth), int(y)
        if y < 100:
            y += 2000
    except Exception:
        return 'none', 0, ""

    try:
        dep_date = datetime.date(y, mth, d)
        ret_date = dep_date + datetime.timedelta(days=max(duration_days - 1, 0))
        for h_start, h_end, h_name in OFFICIAL_HOLIDAYS:
            if dep_date >= h_start and ret_date <= h_end:
                return 'exact', 0, h_name
            if not (ret_date < h_start or dep_date > h_end):
                over = max((h_start - dep_date).days, 0) + max((ret_date - h_end).days, 0)
                if over <= 2:
                    return 'slight_over', over, h_name
    except Exception:
        pass
    return 'none', 0, ""

def normalize_agency_name(raw_name, raw_code, raw_title, forced_agency):
    if forced_agency:
        return forced_agency
    code_str = str(raw_code).strip().upper()
    name_str = str(raw_name).strip().upper()
    title_str = str(raw_title).strip().upper()

    if code_str.isdigit() or "琦琦" in name_str or "QI" in name_str or "序号" in name_str:
        return "琦琦旅游"
    if "SP" in code_str or "豪吉" in name_str or "豪吉" in title_str:
        return "豪吉旅游"
    
    clean = re.sub(r'\(.*?\)|（.*?）', '', str(raw_name)).strip()
    return clean if clean else "豪吉旅游"

def normalize_departure_location(raw_loc, raw_title, agency="豪吉旅游"):
    s = f"{raw_loc} {raw_title}".upper()
    if any(k in s for k in ["SIN", "新加坡", "CHANGI", "SCOOT", "TR"]):
        return "🇸🇬 新加坡起飞 (SIN)"
    if any(k in s for k in ["JB", "新山", "SUBANG", "梳邦"]):
        return "🇲🇾 新山/梳邦起飞 (JB)"
    return "🇲🇾 马来西亚起飞 (KUL)"

def clean_destination_name(raw_dest):
    s = str(raw_dest or "精选路线")
    s = re.sub(r'^(?:SIN|JB|KL|KUL|SUBANG)\s*[-–—]\s*', '', s, flags=re.IGNORECASE)
    return s.strip()

def split_and_explode_dates(raw_agency, raw_dest, raw_code, raw_title, raw_loc, raw_dates_str, raw_price, shopping_status="纯玩无购物团", forced_agency=""):
    days = extract_tour_days(raw_title)
    try:
        clean_price = int(re.sub(r'[^\d]', '', str(raw_price)))
    except Exception:
        clean_price = 2999
    if clean_price < 500 or clean_price > 20000:
        clean_price = 2999

    norm_agency = normalize_agency_name(raw_agency, raw_code, raw_title, forced_agency)
    norm_loc = normalize_departure_location(raw_loc, raw_title, agency=norm_agency)
    clean_dest = clean_destination_name(raw_dest)

    date_matches = re.findall(r'(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})', str(raw_dates_str))
    if date_matches:
        date_tokens = [f"{d}/{m}/{y}" for d, m, y in date_matches]
    else:
        date_tokens = [str(raw_dates_str).strip()]

    exploded = []
    for d_token in date_tokens:
        parts_d = re.split('[/.-]', d_token)
        if len(parts_d) >= 3:
            try:
                d_val, m_val, y_val = int(parts_d[0]), int(parts_d[1]), int(parts_d[2])
                if y_val < 100:
                    y_val += 2000
                full_d_token = f"{d_val:02d}/{m_val:02d}/{y_val}"
            except Exception:
                full_d_token = str(d_token)
        else:
            full_d_token = str(d_token)

        status, over_days, hol_name = evaluate_holiday_fit(full_d_token, days)
        exploded.append({
            "agency": norm_agency,
            "destination": clean_dest,
            "tour_code": str(raw_code or "-"),
            "title": str(raw_title or ""),
            "departure_location": norm_loc,
            "departure_dates": str(full_d_token),
            "price_numeric": clean_price,
            "price_text": f"RM {clean_price}",
            "shopping_status": shopping_status,
            "holiday_status": status,
            "over_days": over_days,
            "holiday_name": hol_name
        })
    return exploded

def parse_qiqi_lines(raw_text, poster_is_pure_non_shopping=False):
    items = []
    lines = raw_text.strip().splitlines()
    for line in lines:
        line = line.strip().replace("```text", "").replace("```", "").replace("`", "").strip()
        if not line or line.startswith("#") or "序号" in line or "团费" in line:
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) >= 5:
            try:
                seq_no = re.sub(r'[^\d]', '', parts[0])
                if not seq_no:
                    continue
                tour_code = f"QIQI-{seq_no}"

                date_matches = re.findall(r'\b(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})\b', line)
                dates_str = date_matches[0] if date_matches else "13/09/2026"

                raw_days_str = parts[2] if len(parts) > 2 else ""
                raw_highlight = parts[3] if len(parts) > 3 else "超值优惠团"
                if raw_days_str and not any(k in raw_highlight for k in ["天", "D", "d"]):
                    title = f"{raw_days_str} {raw_highlight}"
                else:
                    title = raw_highlight

                col_shop = parts[5] if len(parts) > 5 else ""
                col_shop_upper = col_shop.upper()

                if poster_is_pure_non_shopping:
                    shopping_stat = "纯玩无购物团"
                elif col_shop == "" or col_shop == "-" or col_shop_upper in ["无", "NONE", "N/A"]:
                    shopping_stat = "含购物团"
                else:
                    shopping_stat = "纯玩无购物团"

                price_val = 2999
                price_matches = re.findall(r'\b\d{3,5}\b', parts[-1].replace(",", "")) if len(parts) > 0 else []
                if price_matches:
                    price_val = int(price_matches[0])
                else:
                    all_p = re.findall(r'\b\d{3,5}\b', line.replace(",", ""))
                    if all_p:
                        price_val = int(all_p[-1])

                items.append({
                    "agency": "琦琦旅游",
                    "destination": clean_destination_name(title),
                    "tour_code": tour_code,
                    "title": title,
                    "departure_location": "新加坡起飞" if "新加坡起飞" in line else "马来西亚起飞",
                    "departure_dates": dates_str,
                    "price": price_val,
                    "shopping_status": shopping_stat
                })
            except Exception:
                continue
    return items

def parse_json_response(raw_text, default_agency="豪吉旅游"):
    items = []
    try:
        clean_json = raw_text.strip()
        if "```json" in clean_json:
            clean_json = clean_json.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_json:
            clean_json = clean_json.split("
