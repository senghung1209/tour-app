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
import urllib.request
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import streamlit.components.v1 as components

st.set_page_config(page_title="跨社旅游团比价筛选中心", page_icon="✈️", layout="wide")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "tour_database.json")

def load_persisted_data():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            return []
    return []

def save_persisted_data(data):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"本地保存失败: {e}")

st.session_state.tour_data = load_persisted_data()

st.title("✈️ 跨旅行社海报聚合与横向对比中心")

@st.cache_resource
def get_loud_wav_base64():
    sample_rate = 22050
    tones = [(850, 0.18), (0, 0.05), (1200, 0.35)]
    raw_samples = bytearray()
    for freq, duration in tones:
        n_samples = int(sample_rate * duration)
        for i in range(n_samples):
            val = int(128 + 118 * math.sin(2 * math.pi * freq * i / sample_rate)) if freq > 0 else 128
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
    <div style="font-weight: bold; font-size: 14px; color: #1e40af; margin-bottom: 5px;">🔊 手机状态栏通知与完成提示音设置</div>
    <audio id="real_alert_sound" preload="auto"><source src="data:audio/wav;base64,AUDIO_PLACEHOLDER" type="audio/wav"></audio>
    <button id="direct_play_btn" style="background: #2563eb; color: white; border: none; padding: 10px 20px; border-radius: 6px; font-weight: bold; font-size: 14px; width: 100%; cursor: pointer;">👉 点击开启系统通知与测试铃声</button>
</div>
<script>
document.getElementById('direct_play_btn').addEventListener('click', function(e) {
    e.preventDefault();
    if ("vibrate" in navigator) { navigator.vibrate([200, 100, 200]); }
    var audio = document.getElementById('real_alert_sound');
    if (audio) { audio.play().catch(function() {}); }
    if ("Notification" in window) { Notification.requestPermission(); }
});
</script>
""".replace("AUDIO_PLACEHOLDER", LOUD_WAV_B64)
components.html(native_audio_html, height=100)

def trigger_play_on_done(count_num):
    js = """
    <audio id="done_alert_sound" autoplay><source src="data:audio/wav;base64,AUDIO_PLACEHOLDER" type="audio/wav"></audio>
    <script>
    (function() {
        document.title = "🔔【分析完成! 共COUNT_PLACEHOLDER项】跨社比价";
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
    (datetime.date(2026, 12, 4), datetime.date(2027, 1, 3), "2026 学年末大假期 (12月)"),
    (datetime.date(2027, 1, 23), datetime.date(2027, 2, 16), "2027 农历新年与跨年假期")
]

RAW_KEY = st.secrets.get("GEMINI_API_KEY", "")
GEMINI_API_KEY = str(RAW_KEY).strip() if RAW_KEY else ""
PRIMARY_MODEL = "gemini-3.5-flash"

def extract_tour_days(title_str):
    m = re.search(r'(\d+)\s*(?:天|D|d)', str(title_str))
    return int(m.group(1)) if m else 7

def evaluate_holiday_fit(departure_date_str, duration_days):
    matches = re.findall(r'(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?', str(departure_date_str))
    if not matches:
        return 'none', 0, ""

    d, mth, y = matches[0]
    d, mth = int(d), int(mth)
    y = int(y) + 2000 if y and int(y) < 100 else (int(y) if y else 2026)

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

def clean_destination_name(raw_dest):
    s = str(raw_dest or "精选路线")
    s = re.sub(r'^(?:SIN|JB|KL|KUL)\s*[-–—]\s*', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\d+\s*(?:天|D|d)\s*(?:\d+\s*(?:夜|晚|N|n))?', '', s)
    s = re.sub(r'\d+\s*(?:天|D|d|夜|晚|N|n)', '', s)
    return s.strip()

def parse_lines_strict(raw_text, poster_type):
    items = []
    for line in raw_text.strip().splitlines():
        line = line.strip().replace("```", "")
        if not line or line.startswith("#") or "|" not in line or "旅行社" in line or "序号" in line:
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        try:
            if poster_type == "haoji" and len(parts) >= 6:
                price_val = int(re.sub(r'[^\d]', '', parts[5] if len(parts) > 5 else parts[4]))
                tour_code = parts[1] if "SP" in parts[1].upper() else (parts[2] if len(parts) > 2 and "SP" in parts[2].upper() else "SP-000")
                dest = clean_destination_name(parts[0])
                title = parts[2] if len(parts) > 2 else dest
                loc = "🇸🇬 新加坡起飞 (SIN)" if "SIN" in line.upper() or "新加坡" in line else "🇲🇾 马来西亚起飞 (KUL)"
                dates = parts[4] if len(parts) > 4 else parts[3]

                date_tokens = re.findall(r'\b\d{1,2}[/.-]\d{1,2}(?:[/.-](\d{2,4}))?\b', dates)
                if not date_tokens:
                    date_tokens = [dates]

                for d_tok in date_tokens:
                    days = extract_tour_days(title)
                    status, over_days, hol_name = evaluate_holiday_fit(d_tok, days)
                    items.append({
                        "agency": "豪吉旅游",
                        "destination": dest,
                        "tour_code": tour_code,
                        "title": title,
                        "departure_location": loc,
                        "departure_dates": d_tok,
                        "price_numeric": price_val,
                        "price_text": f"RM {price_val}",
                        "holiday_status": status,
                        "over_days": over_days,
                        "holiday_name": hol_name
                    })

            elif poster_type == "qiqi" and len(parts) >= 6:
                seq_no = parts[0]
                dep_date = parts[1]
                days_str = parts[2]
                highlights = parts[3]
                airline = parts[4].upper()
                price_val = int(re.sub(r'[^\d]', '', parts[5]))

                dest = clean_destination_name(highlights.split("+")[0].split(" ")[0])
                title = f"{days_str} {highlights}"
                loc = "🇸🇬 新加坡起飞 (SIN)" if "TR" in airline else "🇲🇾 马来西亚起飞 (KUL)"
                
                days = extract_tour_days(days_str)
                status, over_days, hol_name = evaluate_holiday_fit(dep_date, days)

                items.append({
                    "agency": "琦琦旅游",
                    "destination": dest,
                    "tour_code": f"QIQI-{seq_no}",
                    "title": title,
                    "departure_location": loc,
                    "departure_dates": dep_date,
                    "price_numeric": price_val,
                    "price_text": f"RM {price_val}",
                    "holiday_status": status,
                    "over_days": over_days,
                    "
