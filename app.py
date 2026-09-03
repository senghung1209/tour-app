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
            val = int(128 + 118 * math.sin(2 * math.pi * freq * i / sample_rate))
            raw_samples.append(max(0, min(255, val)))
    data_size = len(raw_samples)
    header = struct.pack('<4sI4s4sIHHIIHH4sI', b'RIFF', 36 + data_size, b'WAVE', b'fmt ', 16, 1, 1, sample_rate, sample_rate, 1, 8, b'data', data_size)
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
                # 豪吉格式：目的地 | 团号(SP开头) | 路线 | 起飞地 | 出发日期 | 价格
                price_val = int(re.sub(r'[^\d]', '', parts[5] if len(parts) > 5 else parts[4]))
                tour_code = parts[1] if "SP" in parts[1].upper() else (parts[2] if len(parts) > 2 and "SP" in parts[2].upper() else "SP-000")
                dest = clean_destination_name(parts[0])
                title = parts[2] if len(parts) > 2 else dest
                loc = "🇸🇬 新加坡起飞 (SIN)" if "SIN" in line.upper() or "新加坡" in line else "🇲🇾 马来西亚起飞 (KUL)"
                dates = parts[4] if len(parts) > 4 else parts[3]

                # 拆分并列日期
                date_tokens = re.findall(r'\b\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?\b', dates)
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
                # 琦琦格式：序号 | 出发日期 | 天数 | 行程亮点 | 航空 | 团费
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
                    "holiday_name": hol_name
                })
        except Exception:
            continue
    return items

def call_gemini_vision(img_bytes, poster_type):
    if not GEMINI_API_KEY:
        return []
    base64_data = base64.b64encode(img_bytes).decode('utf-8')
    
    if poster_type == "haoji":
        prompt = """
        你是豪吉旅游海报专家。请把整张海报内所有的 61 个团期全部提取出来，绝对不能遗漏任何一个方块！
        并列日期或上下两排不同价格必须拆为独立行。
        纯文本逐行输出，竖线 | 分隔，不要代码块：
        目的地纯地名|团号(SP开头)|路线全称|起飞地|出发日期|纯数字价格
        """
    else:
        prompt = """
        你是琦琦旅游表格专家。请把表格内第 1 项到第 23 项全部提取出来。
        纯文本逐行输出，竖线 | 分隔，不要代码块：
        序号|出发日期|天数|行程亮点|航空|纯数字团费
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
            return parse_lines_strict(raw_text, poster_type)
    except Exception:
        pass
    return []

uploaded_files = st.file_uploader("📷 上传海报图片 (支持豪吉或琦琦)", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

if uploaded_files:
    if st.button("🚀 启动独立双通道全量扫描", type="primary", use_container_width=True):
        newly_extracted = []
        for f in uploaded_files:
            img_bytes = f.getvalue()
            img = Image.open(BytesIO(img_bytes))
            w, h = img.size
            
            # 自动识别是琦琦表格还是豪吉海报
            if h > w * 1.35 and not any(k in f.name.upper() for k in ["SP", "HAOGI"]):
                st.info(f"正在全幅扫描琦琦旅游表格：{f.name}")
                raw_items = call_gemini_vision(img_bytes, "qiqi")
            else:
                st.info(f"正在全幅扫描豪吉旅游拼贴海报：{f.name}")
                # 豪吉直接整张图丢给 gemini-3.5-flash，利用其超大视觉上下文一次性抓取全部 61 项
                raw_items = call_gemini_vision(img_bytes, "haoji")
            
            newly_extracted.extend(raw_items)

        if newly_extracted:
            combined = st.session_state.tour_data + newly_extracted
            seen = set()
            unique_combined = []
            for item in combined:
                marker = (item["agency"], item["tour_code"], item["departure_dates"], item["price_numeric"])
                if marker not in seen:
                    seen.add(marker)
                    unique_combined.append(item)

            st.session_state.tour_data = unique_combined
            save_persisted_data(unique_combined)
            st.success(f"🎉 扫描完成！总库共有 **{len(st.session_state.tour_data)}** 项团期。")
            time.sleep(1)
            st.rerun()

if st.session_state.tour_data:
    if st.button("🗑️ 清空总库数据", use_container_width=True):
        save_persisted_data([])
        st.session_state.tour_data = []
        st.rerun()

    df = pd.DataFrame(st.session_state.tour_data)
    st.markdown(f"### 当前总库共 **{len(df)}** 项团期：")
    st.dataframe(df[['agency', 'destination', 'tour_code', 'departure_location', 'departure_dates', 'price_text', 'title']], use_container_width=True)
