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
from PIL import Image, ImageDraw, ImageFont
import streamlit.components.v1 as components

st.set_page_config(page_title="旅游团智能比价助手", page_icon="✈️", layout="wide")

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

st.title("✈️ 旅游团智能比价助手")

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

def split_and_explode_dates(raw_agency, raw_dest, raw_code, raw_title, raw_loc, raw_dates_str, raw_price, forced_agency=""):
    days = extract_tour_days(raw_title)
    try:
        clean_price = int(re.sub(r'[^\d]', '', str(raw_price)))
    except Exception:
        clean_price = 2999
    if clean_price == 0:
        clean_price = 2999

    norm_agency = normalize_agency_name(raw_agency, raw_code, raw_title, forced_agency)
    norm_loc = normalize_departure_location(raw_loc, raw_title)
    clean_dest = clean_destination_name(raw_dest)

    date_tokens = re.findall(r'\b\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?\b', str(raw_dates_str))
    if not date_tokens:
        date_tokens = [str(raw_dates_str).strip()]

    exploded = []
    for d_token in date_tokens:
        if len(d_token.split('/')[-1]) == 2:
            pass
        elif len(d_token.split('/')) == 2:
            d_token = f"{d_token}/26"

        status, over_days, hol_name = evaluate_holiday_fit(d_token, days)
        exploded.append({
            "agency": norm_agency,
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

def parse_tolerant_lines(raw_text, default_agency="豪吉旅游"):
    clean_lines = raw_text.strip().splitlines()
    items = []
    for line in clean_lines:
        line = line.strip().replace("```text", "").replace("```", "").replace("`", "").strip()
        if not line or line.startswith("#") or "旅行社|目的地" in line or "目的地|团号" in line:
            continue
        
        parts = [p.strip() for p in line.split("|") if p.strip()]
        full_line_str = " ".join(parts) if parts else line

        code_matches = re.findall(r'\bSP[-]?\d{4,6}\b', full_line_str, re.IGNORECASE)
        if not code_matches:
            continue

        try:
            tour_code = code_matches[0].upper()
            price_val = 2999
            price_matches = re.findall(r'\b\d{3,5}\b', full_line_str.replace(",", ""))
            if price_matches:
                price_val = int(price_matches[-1])
            if price_val == 0:
                price_val = 2999

            date_matches = re.findall(r'\b\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?\b', full_line_str)
            dates_str = ", ".join(date_matches) if date_matches else "26/12/26"

            dest = parts[0] if len(parts) > 0 and not "SP" in parts[0].upper() else "精选目的地"
            title = parts[2] if len(parts) > 2 else (parts[1] if len(parts) > 1 else "精选路线")
            loc = parts[3] if len(parts) > 3 else "新加坡起飞"

            items.append({
                "agency": default_agency,
                "destination": clean_destination_name(dest),
                "tour_code": tour_code,
                "title": title,
                "departure_location": loc,
                "departure_dates": dates_str,
                "price": price_val
            })
        except Exception:
            continue
    return items

def parse_qiqi_lines(raw_text):
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

                date_matches = re.findall(r'\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b', line)
                if not date_matches:
                    date_matches = re.findall(r'\b\d{1,2}[/.-]\d{1,2}\b', line)
                dates_str = date_matches[0] if date_matches else "13/09/2026"

                title = parts[3] if len(parts) > 3 else "超值优惠团"
                price_val = 2999
                price_matches = re.findall(r'\b\d{3,5}\b', parts[5].replace(",", "")) if len(parts) > 5 else []
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
                    "departure_location": "新加坡起飞 (SIN)",
                    "departure_dates": dates_str,
                    "price": price_val
                })
            except Exception:
                continue
    return items

def call_gemini_section_scan(img_chunk, section_name):
    if not GEMINI_API_KEY:
        return []

    buf = BytesIO()
    img_chunk.save(buf, format="JPEG", quality=95)
    base64_data = base64.b64encode(buf.getvalue()).decode('utf-8')

    prompt = f"""
    你是顶级旅游海报视觉专家。当前正在专注分析【{section_name}】板块。
    请全量提取该板块内的所有团号、所有出发日期和价格！

    严格规则：
    1. 逐行输出，竖线 | 分隔，严禁任何代码块标记：
    目的地 | 团号 | 行程路线全称 | 起飞地 | 完整出发日期 | 纯数字价格
    2. 多期团必须独立分行写！
    """

    payload = {
        "contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": base64_data}}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 16384}
    }

    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}

    for model_name in [PRIMARY_MODEL, BACKUP_MODEL]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        for attempt in range(3):
            try:
                res = requests.post(url, headers=headers, json=payload, timeout=90)
                if res.status_code == 200:
                    raw_text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                    items = parse_tolerant_lines(raw_text, default_agency="豪吉旅游")
                    if items:
                        return items
                if res.status_code == 503:
                    time.sleep(3)
                    continue
            except Exception:
                time.sleep(3)
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
    draw.text((30, 24), f"旅游团比价清单 (精选有效团期 {len(df)} 项)", fill=(255, 255, 255), font=f_head)

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

uploaded_file = st.file_uploader("📷 请上传旅游海报图片", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    agency_choice = st.radio("请选择这家海报对应的旅行社：", ["豪吉旅游", "琦琦旅游"], horizontal=True)

    if st.button("🚀 一键自动提取并比价", type="primary", use_container_width=True):
        newly_extracted = []
        progress_bar = st.progress(0.0)
        status_box = st.empty()

        img = Image.open(BytesIO(uploaded_file.getvalue()))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        w, h = img.size

        if agency_choice == "琦琦旅游":
            status_box.markdown("🔍 正在全幅扫描琦琦旅游 1-23 行超值表格...")
            progress_bar.progress(0.5)
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=95)
            base64_data = base64.b64encode(buf.getvalue()).decode('utf-8')
            prompt = "请提取琦琦旅游23行表格。格式：序号 | 出发日期 | 天数 | 行程亮点 | 航空 | 团费RM"
            payload = {
                "contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": base64_data}}]}],
                "generationConfig": {"temperature": 0.0, "maxOutputTokens": 16384}
            }
            headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}
            raw_items = []
            for model_name in [PRIMARY_MODEL, BACKUP_MODEL]:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
                res = requests.post(url, headers=headers, json=payload, timeout=90)
                if res.status_code == 200:
                    raw_items = parse_qiqi_lines(res.json()["candidates"][0]["content"]["parts"][0]["text"])
                    if raw_items:
                        break
        else:
            # 💎 省份微距逐个裁剪扫描（海南岛、哈尔滨、上海、大连、广州澳门、重庆、张家界、北疆南疆）
            # 根据豪吉海报的实际坐标比例进行裁剪
            boxes = [
                ("海南岛板块", (0, int(h * 0.13), int(w * 0.35), int(h * 0.39))),
                ("哈尔滨板块(含上下及雪国列车)", (int(w * 0.32), int(h * 0.13), int(w * 0.68), int(h * 0.58))),
                ("上海板块(含右侧边缘)", (int(w * 0.65), int(h * 0.13), w, int(h * 0.53))),
                ("大连板块", (0, int(h * 0.38), int(w * 0.35), int(h * 0.68))),
                ("广州澳门板块", (int(w * 0.32), int(h * 0.53), int(w * 0.65), int(h * 0.78))),
                ("重庆板块", (int(w * 0.65), int(h * 0.51), w, int(h * 0.68))),
                ("张家界板块", (0, int(h * 0.67), int(w * 0.35), h)),
                ("北疆南疆板块", (int(w * 0.65), int(h * 0.67), w, h))
            ]

            raw_items = []
            total_boxes = len(boxes)
            for idx, (sec_name, box_coords) in enumerate(boxes):
                status_box.markdown(f"🔍 正在微距分析【{sec_name}】...")
                progress_bar.progress((idx + 1) / total_boxes)
                cropped_img = img.crop(box_coords)
                sec_items = call_gemini_section_scan(cropped_img, sec_name)
                raw_items.extend(sec_items)

        progress_bar.progress(1.0)
        status_box.markdown("✨ 正在智能清洗、日期炸开与全局排序...")

        for item in raw_items:
            rows = split_and_explode_dates(
                item.get("agency", ""),
                item.get("destination", "精选路线"),
                item.get("tour_code", "-"),
                item.get("title", ""),
                item.get("departure_location", ""),
                item.get("departure_dates", ""),
                item.get("price", 0),
                forced_agency=agency_choice
            )
            newly_extracted.extend(rows)

        if newly_extracted:
            combined = st.session_state.tour_data + newly_extracted
            unique_combined = []
            seen = set()
            for item in combined:
                key = (item["agency"], item["tour_code"], item["departure_dates"], item["price_numeric"])
                if key not in seen:
                    seen.add(key)
                    unique_combined.append(item)

            unique_combined = sorted(unique_combined, key=lambda x: (x['agency'], x['destination'], x['departure_dates']))

            st.session_state.tour_data = unique_combined
            save_persisted_data(unique_combined)
            trigger_play_on_done(len(st.session_state.tour_data))
            st.success(f"🎉 省份逐个微距扫描完成！当前总库共有 **{len(st.session_state.tour_data)}** 个精准团期供妈妈挑选。")
            time.sleep(1.0)
            st.rerun()
        else:
            st.warning("⚠️ 未能从该图中解析出有效团期，请检查图片或重新点击。")

if st.session_state.tour_data:
    if st.button("🗑️ 清空所有已保存数据 (重新开始)", use_container_width=True):
        save_persisted_data([])
        st.session_state.tour_data = []
        st.rerun()

    st.markdown("---")
    df = pd.DataFrame(st.session_state.tour_data)
    df['price_numeric'] = pd.to_numeric(df['price_numeric'], errors='coerce').fillna(0).astype(int)

    st.sidebar.header("🎛️ 妈妈专属筛选面板")
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
        filtered_df = filtered_df[filtered_df['departure_location'].str.contains("SIN|新加坡", na=False)]

    if selected_hol == "🎒 包含学校假期 (含超出2天内)":
        filtered_df = filtered_df[filtered_df['holiday_status'].isin(['exact', 'slight_over'])]
    elif selected_hol == "✨ 严格在学校假期内 (0超出)":
        filtered_df = filtered_df[filtered_df['holiday_status'] == 'exact']
    elif selected_hol == "💼 仅平时非假期":
        filtered_df = filtered_df[filtered_df['holiday_status'] == 'none']

    p_min = int(df['price_numeric'].min()) if not df.empty else 1000
    p_max = int(df['price_numeric'].max()) if not df.empty else 9000
    if p_min >= p_max:
        p_max = p_min + 100
    price_range = st.sidebar.slider("💰 团费预算范围 (RM)", min_value=p_min, max_value=p_max, value=(p_min, p_max), step=100)
    filtered_df = filtered_df[(filtered_df['price_numeric'] >= price_range[0]) & (filtered_df['price_numeric'] <= price_range[1])]

    st.markdown(f"### 符合条件的出发选项共 **{len(filtered_df)}** 个：")
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("📊 下载 CSV 比价清单", data=filtered_df.to_csv(index=False).encode('utf-8-sig'), file_name="智能比价清单.csv", mime="text/csv", use_container_width=True)
    with col2:
        st.download_button("🖼️ 下载高清长图 (.png)", data=generate_comparison_image(filtered_df), file_name="智能比价长图.png", mime="image/png", use_container_width=True)

    st.markdown("#### 📋 妈妈专属比对卡片 (点击即看)")
    for _, row in filtered_df.iterrows():
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 2, 2])
            with c1:
                st.markdown(f"### 📍 **{row['destination']}** <small style='color:gray;'>({row['agency']})</small>", unsafe_allow_html=True)
                st.write(f"**路线：** {row['title']}")
                st.write(f"**团号：** `{row['tour_code']}`")
            with c2:
                st.markdown(f"🛫 **出发地：** `{row['departure_location']}`")
                st.write(f"📅 **出发日期：** {row['departure_dates']}")
                h_stat = row['holiday_status']
                if h_stat == 'exact':
                    st.success(f"🎒 完美在校假内 ({row['holiday_name']})")
                elif h_stat == 'slight_over':
                    st.warning(f"⚠️ 包含校假，超 {row['over_days']} 天 (需请假)")
            with c3:
                st.markdown(f"### 💰 **{row['price_text']}**")
