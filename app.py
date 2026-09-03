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
from PIL import Image
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
    except Exception:
        pass

if "tour_data" not in st.session_state:
    st.session_state.tour_data = load_persisted_data()

st.title("✈️ 跨旅行社海报聚合与横向对比中心")

# 铃声与通知组件
@st.cache_resource
def get_loud_wav_base64():
    sample_rate = 22050
    tones = [(850, 0.18), (0, 0.05), (1200, 0.35)]
    raw_samples = bytearray()
    for freq, duration in tones:
        n_samples = int(sample_rate * duration)
        for i in range(n_samples):
            val = int(128 + 118 * math.sin(2 * math.pi * freq * i / sample_rate))
            raw_samples.append(max(0, min(255, val)))
    data_size = len(raw_samples)
    header = struct.pack('<4sI4s4sIHHIIHH4sI', b'RIFF', 36 + data_size, b'WAVE', b'fmt ', 16, 1, 1, sample_rate, sample_rate, 1, 8, b'data', data_size)
    return base64.b64encode(header + raw_samples).decode('ascii')

LOUD_WAV_B64 = get_loud_wav_base64()

audio_html = f"""
<div style="background: #eff6ff; border: 1.5px solid #3b82f6; border-radius: 8px; padding: 12px; margin-bottom: 15px;">
    <div style="font-weight: bold; font-size: 14px; color: #1e40af; margin-bottom: 5px;">🔊 提示音与状态栏通知通道</div>
    <audio id="real_alert_sound" preload="auto"><source src="data:audio/wav;base64,{LOUD_WAV_B64}" type="audio/wav"></audio>
    <button id="direct_play_btn" style="background: #2563eb; color: white; border: none; padding: 10px 20px; border-radius: 6px; font-weight: bold; font-size: 14px; width: 100%; cursor: pointer;">👉 点击激活声音与通知权限</button>
</div>
<script>
document.getElementById('direct_play_btn').addEventListener('click', function(e) {{
    e.preventDefault();
    if ("vibrate" in navigator) {{ navigator.vibrate([200, 100, 200]); }}
    var audio = document.getElementById('real_alert_sound');
    if (audio) {{ audio.play().catch(function() {{}}); }}
    if ("Notification" in window) {{ Notification.requestPermission(); }}
}});
</script>
"""
components.html(audio_html, height=110)

OFFICIAL_HOLIDAYS = [
    (datetime.date(2026, 3, 20), datetime.date(2026, 3, 29), "2026 第一学期假期 (3月)"),
    (datetime.date(2026, 5, 22), datetime.date(2026, 6, 7), "2026 年中假期 (5/6月)"),
    (datetime.date(2026, 8, 28), datetime.date(2026, 9, 6), "2026 第二学期假期 (8/9月)"),
    (datetime.date(2026, 12, 4), datetime.date(2027, 1, 3), "2026 学年末大假期 (12月)"),
    (datetime.date(2027, 1, 23), datetime.date(2027, 2, 16), "2027 农历新年与跨年假期")
]

RAW_KEY = st.secrets.get("GEMINI_API_KEY", "")
GEMINI_API_KEY = str(RAW_KEY).strip() if RAW_KEY else ""

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

def parse_text_robust(raw_text):
    items = []
    for line in raw_text.strip().splitlines():
        line = line.strip().replace("```", "")
        if not line or line.startswith("#") or "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 6:
            try:
                # 判断是豪吉还是琦琦格式
                if "SP" in parts[2].upper() or "豪吉" in parts[0] or len(parts) >= 7:
                    price_val = int(re.sub(r'[^\d]', '', parts[6] if len(parts) > 6 else parts[5]))
                    items.append({
                        "agency": "豪吉旅游",
                        "destination": parts[1] or "精选目的地",
                        "tour_code": parts[2] or "-",
                        "title": parts[3] or "",
                        "departure_location": "🇸🇬 新加坡起飞 (SIN)" if "SIN" in parts[4].upper() or "新加坡" in parts[4] else "🇲🇾 马来西亚起飞 (KUL)",
                        "departure_dates": parts[5],
                        "price": price_val
                    })
                else:
                    price_val = int(re.sub(r'[^\d]', '', parts[5]))
                    raw_dest = parts[3].split("+")[0].split(" ")[0].strip()
                    airline = parts[4].upper()
                    items.append({
                        "agency": "琦琦旅游",
                        "destination": raw_dest if raw_dest else "精选目的地",
                        "tour_code": f"QIQI-{parts[0]}",
                        "title": f"{parts[2]} {parts[3]}",
                        "departure_location": "🇸🇬 新加坡起飞 (SIN)" if "TR" in airline else "🇲🇾 马来西亚起飞 (KUL)",
                        "departure_dates": parts[1],
                        "price": price_val
                    })
            except Exception:
                continue
    return items

def call_gemini_vision(img_bytes):
    if not GEMINI_API_KEY:
        return []
    base64_data = base64.b64encode(img_bytes).decode('utf-8')
    prompt = """
    请全量提取图中的所有旅游团期信息。
    支持豪吉旅游（格式：豪吉旅游|目的地|团号SP开头|行程路线|起飞地|出发日期|价格）或琦琦旅游表格（格式：序号|出发日期|天数|行程亮点|航空|价格）。
    每一行以竖线 | 分隔，严禁代码块标记：
    """
    payload = {
        "contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": base64_data}}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 8192}
    }
    url = f"[https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key=](https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key=){GEMINI_API_KEY}"
    try:
        res = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=60)
        if res.status_code == 200:
            raw_text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
            return parse_text_robust(raw_text)
    except Exception:
        pass
    return []

# 文件上传组件
uploaded_file = st.file_uploader("📷 上传单张海报图片（推荐单张上传以保证秒级响应）", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    st.image(uploaded_file, caption="已上传海报预览", width=300)
    if st.button("🚀 立即开始分析并入库", type="primary"):
        with st.spinner("🔍 正在调用 AI 视觉深度解析中..."):
            img_bytes = uploaded_file.getvalue()
            raw_items = call_gemini_vision(img_bytes)
            
            newly_extracted = []
            for item in raw_items:
