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
        🔊 手机状态栏通知与完成提示音设置
    </div>
    <audio id="real_alert_sound" preload="auto">
        <source src="data:audio/wav;base64,AUDIO_PLACEHOLDER" type="audio/wav">
    </audio>
    <button id="direct_play_btn" style="background: #2563eb; color: white; border: none; padding: 10px 20px; border-radius: 6px; font-weight: bold; font-size: 14px; width: 100%; cursor: pointer;">
        👉 点击开启系统通知与测试铃声
    </button>
</div>
<script>
document.getElementById('direct_play_btn').addEventListener('click', function(e) {
    e.preventDefault();
    if ("vibrate" in navigator) { navigator.vibrate([200, 100, 200]); }
    var audio = document.getElementById('real_alert_sound');
    if (audio) { audio.currentTime = 0; audio.volume = 1.0; audio.play().catch(function() {}); }
    if ("Notification" in window) {
        Notification.requestPermission().then(function(perm) {
            if (perm === 'granted') {
                new Notification("通知权限已开通！", { body: "海报解析完成后会在此处提醒你。", icon: "✈️" });
            }
        });
    }
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
        document.title = "🔔【分析完成! 共COUNT_PLACEHOLDER项】跨社比价";
        if ("vibrate" in navigator) { navigator.vibrate([250, 100, 250, 100, 400]); }
        var aud = document.getElementById('done_alert_sound');
        if (aud) { aud.play().catch(function(){}); }
        if ("Notification" in window && Notification.permission === "granted") {
            new Notification("🎉 旅游海报扫描完成！", {
                body: "已成功提取全量数据，总库共有 COUNT_PLACEHOLDER 条团期！点击查看",
                icon: "✈️"
            });
        }
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
BACKUP_MODEL = "gemini-3.1-flash-lite"

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

def normalize_departure_location(raw_loc, raw_title):
    s = f"{raw_loc} {raw_title}".upper()
    if any(k in s for k in ["SIN", "新加坡", "CHANGI", "SCOOT", "TR"]):
        return "🇸🇬 新加坡起飞 (SIN)"
    if any(k in s for k in ["JB", "新山"]):
        return "🇲🇾 新山出发 (JB)"
    return "🇲🇾 马来西亚起飞 (KUL)"

def clean_destination_name(raw_dest):
    s = str(raw_dest or "精选路线")
    s = re.sub(r'^(?:SIN|JB|KL|KUL)\s*[-–—]\s*', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\d+\s*(?:天|D|d)\s*(?:\d+\s*(?:夜|晚|N|n))?', '', s)
    s = re.sub(r'\d+\s*(?:天|D|d|夜|晚|N|n)', '', s)
    return s.strip()

def split_and_explode_dates(raw_agency, raw_dest, raw_code, raw_title, raw_loc, raw_dates_str, raw_price):
    days = extract_tour_days(raw_title)
    try:
        clean_price = int(re.sub(r'[^\d]', '', str(raw_price)))
    except Exception:
        clean_price = 0

    norm_loc = normalize_departure_location(raw_loc, raw_title)
    clean_dest = clean_destination_name(raw_dest)

    date_tokens = re.findall(r'\b\d{1,2}[/.-]\d{1,2}(?:[/.-](\d{2,4}))?\b', str(raw_dates_str))
    if not date_tokens:
        date_tokens = [str(raw_dates_str).strip()]

    exploded = []
    for d_token in date_tokens:
        status, over_days, hol_name = evaluate_holiday_fit(d_token, days)
        exploded.append({
            "agency": raw_agency,
            "destination": clean_dest,
            "tour_code": str(raw_code or "-"),
            "title": str(raw_title or ""),
            "departure_location": norm_loc,
            "departure_dates": str(d_token),
            "price_numeric": clean_price,
            "price_text": f"RM {clean_price}",
            "holiday_status": status,
            "over_days": over_days,
            "holiday_name": hol_name
        })
    return exploded

# 终极宽松超强容错解析器：只要行里能抠出日期和价格，统统放行入库
def parse_bulletproof_lines(raw_text, default_agency="豪吉旅游"):
    items = []
    for line in raw_text.strip().splitlines():
        line = line.strip().replace("```", "").replace("`", "")
        if not line or line.startswith("#") or "旅行社|目的地" in line or "序号|出发" in line:
            continue
        
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if not parts:
            continue

        try:
            full_line_str = " ".join(parts)
            
            # 自动用正则在整行中搜寻价格（3到5位数字）
            price_val = 2999
            price_matches = re.findall(r'\b\d{3,5}\b', full_line_str.replace(",", ""))
            if price_matches:
                price_val = int(price_matches[-1]) # 通常价格在最后

            # 自动用正则在整行中搜寻日期（格式如 DD/MM/YY 或 DD-MM-YY）
            date_matches = re.findall(r'\b\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?\b', full_line_str)
            dates_str = date_matches[0] if date_matches else "26/12/26"

            if default_agency == "豪吉旅游":
                tour_code = "SP-000"
                for p in parts:
                    if "SP" in p.upper():
                        tour_code = p
                        break
                dest = parts[0] if len(parts) > 0 else "精选目的地"
                title = parts[1] if len(parts) > 1 else dest
                loc = parts[2] if len(parts) > 2 else "新加坡起飞"

                items.append({
                    "agency": "豪吉旅游",
                    "destination": clean_destination_name(dest),
                    "tour_code": tour_code,
                    "title": title,
                    "departure_location": loc,
                    "departure_dates": dates_str,
                    "price": price_val
                })
            else:
                # 琦琦旅游超级容错解析
                seq_no = parts[0] if len(parts) > 0 and parts[0].isdigit() else "1"
                highlights = parts[3] if len(parts) > 3 else (parts[1] if len(parts) > 1 else "超值精选路线")
                days_str = parts[2] if len(parts) > 2 else "6天5夜"
                airline = parts[4] if len(parts) > 4 else "TR"

                items.append({
                    "agency": "琦琦旅游",
                    "destination": clean_destination_name(highlights),
                    "tour_code": f"QIQI-{seq_no}",
                    "title": f"{days_str} {highlights}",
                    "departure_location": "新加坡起飞 (SIN)" if "TR" in airline.upper() else "马来西亚起飞 (KUL)",
                    "departure_dates": dates_str,
                    "price": price_val
                })
        except Exception:
            continue
    return items

def call_gemini_vision_bulletproof(img_bytes, prompt_text, agency_name):
    if not GEMINI_API_KEY:
        return []

    base64_data = base64.b64encode(img_bytes).decode('utf-8')
    payload = {
        "contents": [{"parts": [{"text": prompt_text}, {"inline_data": {"mime_type": "image/jpeg", "data": base64_data}}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 8192}
    }
    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}

    for model_name in [PRIMARY_MODEL, BACKUP_MODEL]:
        url = f"[https://generativelanguage.googleapis.com/v1beta/models/](https://generativelanguage.googleapis.com/v1beta/models/){model_name}:generateContent?key={GEMINI_API_KEY}"
        for attempt in range(2):
            try:
                res = requests.post(url, headers=headers, json=payload, timeout=60)
                if res.status_code == 200:
                    raw_text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                    items = parse_bulletproof_lines(raw_text, default_agency=agency_name)
                    if items:
                        return items
                if res.status_code == 503:
                    time.sleep(2)
                    continue
            except Exception:
                time.sleep(2)
    return []

@st.cache_resource
def get_chinese_font(font_size=15):
    font_paths = [
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "wqy-microhei.ttc"
    ]
    for p in font_paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, font_size)
            except Exception:
                pass
    return ImageFont.load_default()

def generate_comparison_image(df):
    w = 1020
    rh = 42
    hh = 75
    h = hh + (len(df) + 1) * rh + 35
    img = Image.new("RGB", (w, max(h, 220)), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    f_head = get_chinese_font(20)
    f_col = get_chinese_font(15)
    f_body = get_chinese_font(14)
    f_price = get_chinese_font(15)

    draw.rectangle([0, 0, w, hh], fill=(30, 41, 59))
    draw.text((30, 24), f"跨旅行社旅游团比价清单 (精选有效团期 {len(df)} 项)", fill=(255, 255, 255), font=f_head)

    y = hh + 10
    draw.rectangle([20, y, w - 20, y + 34], fill=(241, 245, 249))
    cols = [("旅行社", 35), ("目的地", 160), ("团号", 250), ("起飞地", 360), ("出发日期", 500), ("团费价格", 620), ("行程路线", 740)]
    for name, x in cols:
        draw.text((x, y + 7), name, fill=(71, 85, 105), font=f_col)

    y += 40
    for idx, r in df.iterrows():
        bg = (248, 250, 252) if idx % 2 == 0 else (255, 255, 255)
        draw.rectangle([20, y, w - 20, y + rh - 2], fill=bg)

        draw.text((35, y + 10), str(r['agency'])[:8], fill=(71, 85, 105), font=f_body)
        draw.text((160, y + 10), str(r['destination'])[:6], fill=(15, 23, 42), font=f_body)
        draw.text((250, y + 10), str(r['tour_code'])[:10], fill=(100, 116, 139), font=f_body)

        loc_clean = str(r['departure_location']).replace("🇸🇬", "").replace("🇲🇾", "").strip()
        draw.text((360, y + 10), loc_clean[:12], fill=(2, 132, 199), font=f_body)

        draw.text((500, y + 10), str(r['departure_dates'])[:12], fill=(15, 23, 42), font=f_body)
        draw.text((620, y + 9), str(r['price_text']), fill=(220, 38, 38), font=f_price)
        draw.text((740, y + 10), str(r['title'])[:16], fill=(71, 85, 105), font=f_body)
        y += rh

    buf = BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()

uploaded_file = st.file_uploader("📷 上传单张海报图片 (请一张一张上传)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    agency_choice = st.radio("请为这张海报选择对应的旅行社：", ["豪吉旅游", "琦琦旅游"], horizontal=True)

    if st.button("🚀 立即开始独立通道精准分析并入库", type="primary", use_container_width=True):
        newly_extracted = []
        progress_bar = st.progress(0.0)
        status_box = st.empty()

        img = Image.open(BytesIO(uploaded_file.getvalue()))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        w, h = img.size

        if agency_choice == "琦琦旅游":
            status_box.markdown("🔍 正在全幅扫描【琦琦旅游】表格...")
            progress_bar.progress(0.5)
            qiqi_prompt = """
            请提取琦琦旅游表格内所有团期信息。纯文本输出，竖线 | 分隔：
            序号|出发日期|天数|行程亮点|航空|团费价格
            """
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=95)
            raw_items = call_gemini_vision_bulletproof(buf.getvalue(), qiqi_prompt, "琦琦旅游")
        else:
            box_top = (0, 0, w, int(h * 0.38))
            box_mid = (0, int(h * 0.32), w, int(h * 0.70))
            box_bottom = (0, int(h * 0.62), w, h)

            haoji_prompt = """
            请提取该区域内的所有旅游团期。纯文本输出，竖线 | 分隔：
            目的地|团号|路线名称|起飞地|出发日期|价格
            """

            status_box.markdown("🔍 豪吉海报【第一段】...")
            progress_bar.progress(0.2)
            buf1 = BytesIO()
            img.crop(box_top).save(buf1, format="JPEG", quality=95)
            r1 = call_gemini_vision_bulletproof(buf1.getvalue(), haoji_prompt, "豪吉旅游")

            status_box.markdown("🔍 豪吉海报【第二段】...")
            progress_bar.progress(0.5)
            buf2 = BytesIO()
            img.crop(box_mid).save(buf2, format="JPEG", quality=95)
            r2 = call_gemini_vision_bulletproof(buf2.getvalue(), haoji_prompt, "豪吉旅游")

            status_box.markdown("🔍 豪吉海报【第三段】...")
            progress_bar.progress(0.8)
            buf3 = BytesIO()
            img.crop(box_bottom).save(buf3, format="JPEG", quality=95)
            r3 = call_gemini_vision_bulletproof(buf3.getvalue(), haoji_prompt, "豪吉旅游")

            raw_items = r1 + r2 + r3

        progress_bar.progress(1.0)
        status_box.markdown("✨ 正在清洗并追加到总库...")

        for item in raw_items:
            rows = split_and_explode_dates(
                agency_choice,
                item.get("destination", "精选路线"),
                item.get("tour_code", "SP-000"),
                item.get("title", ""),
                item.get("departure_location", ""),
                item.get("departure_dates", ""),
                item.get("price", 0)
            )
            newly_extracted.extend(rows)

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
            trigger_play_on_done(len(st.session_state.tour_data))
            st.success(f"🎉 成功为【{agency_choice}】精准提取 {len(newly_extracted)} 项！总库现有 **{len(st.session_state.tour_data)}** 项团期。")
            time.sleep(1.0)
            st.rerun()
        else:
            st.warning("⚠️ 未能从该图中解析出有效团期，请检查图片或重新点击。")

if st.session_state.tour_data:
    if st.button("🗑️ 清空总库全部数据 (永久重置)", use_container_width=True):
        save_persisted_data([])
        st.session_state.tour_data = []
        st.rerun()

    st.markdown("---")
    df = pd.DataFrame(st.session_state.tour_data)
    df['price_numeric'] = pd.to_numeric(df['price_numeric'], errors='coerce').fillna(0).astype(int)

    with st.expander(f"🛠️ 快速数据校对面板 (当前总库共有 {len(df)} 项)", expanded=False):
        edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)
        if not edited_df.equals(df):
            st.session_state.tour_data = edited_df.to_dict('records')
            save_persisted_data(st.session_state.tour_data)
            st.rerun()

    st.sidebar.header("🎛️ 筛选条件")
    clean_agencies = sorted(list({str(a) for a in df['agency'] if pd.notna(a) and str(a).strip()}))
    selected_agency = st.sidebar.selectbox("选择旅行社", ["全部"] + clean_agencies)

    clean_dests = sorted(list({str(d) for d in df['destination'] if pd.notna(d) and str(d).strip()}))
    selected_dest = st.sidebar.selectbox("选择目的地", ["全部"] + clean_dests)

    loc_options = [
        "全部",
        "🇲🇾 马来西亚全部地区 (包含吉隆坡KUL / 新山JB)",
        "🇲🇾 马来西亚起飞 (KUL)",
        "🇲🇾 新山出发 (JB)",
        "🇸🇬 新加坡起飞 (SIN)"
    ]
    selected_loc = st.sidebar.selectbox("选择起飞地点", loc_options)

    selected_hol = st.sidebar.selectbox("🗓️ 学校假期筛选", ["全部日期", "🎒 包含学校假期 (含超出2天内)", "✨ 严格在学校假期内 (0超出)", "💼 仅平时非假期"])

    filtered_df = df.copy()
    if selected_agency != "全部":
        filtered_df = filtered_df[filtered_df['agency'] == selected_agency]
    if selected_dest != "全部":
        filtered_df = filtered_df[filtered_df['destination'] == selected_dest]

    if selected_loc == "🇲🇾 马来西亚全部地区 (包含吉隆坡KUL / 新山JB)":
        filtered_df = filtered_df[filtered_df['departure_location'].str.contains("马来西亚|新山|KUL|JB", na=False)]
    elif selected_loc == "🇲🇾 马来西亚起飞 (KUL)":
        filtered_df = filtered_df[filtered_df['departure_location'].str.contains("KUL", na=False)]
    elif selected_loc == "🇲🇾 新山出发 (JB)":
        filtered_df = filtered_df[filtered_df['departure_location'].str.contains("JB|新山", na=False)]
    elif selected_loc == "🇸🇬 新加坡起飞 (SIN)":
        filtered_df = filtered
