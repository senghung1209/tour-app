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

st.sidebar.header("📌 系统工作模式")
work_mode = st.sidebar.radio("请选择空间类型", ["🌐 公共共享模式 (多人实时同步)", "👤 独立个人模式 (私有独立沙盒)"])

if work_mode == "🌐 公共共享模式 (多人实时同步)":
    if "shared_tour_data" not in st.session_state:
        st.session_state.shared_tour_data = load_persisted_data()
    active_data = st.session_state.shared_tour_data
else:
    if "private_tour_data" not in st.session_state:
        st.session_state.private_tour_data = []
    active_data = st.session_state.private_tour_data

st.title("✈️ 旅游团智能比价助手 (稳定抗压版)")

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

RAW_KEY = st.secrets.get("GEMINI_API_KEY", "")
GEMINI_API_KEY = str(RAW_KEY).strip() if RAW_KEY else ""
PRIMARY_MODEL = "gemini-3.5-flash"
BACKUP_MODEL = "gemini-3.1-flash-lite"

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
    s = re.sub(r'\d+\s*(?:天|D|d)\s*(?:\d+\s*(?:夜|晚|N|n))?', '', s)
    s = re.sub(r'\d+\s*(?:天|D|d|夜|晚|N|n)', '', s)
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

                title = parts[3] if len(parts) > 3 else "超值优惠团"
                
                col_shop = parts[5] if len(parts) > 5 else ""
                if poster_is_pure_non_shopping:
                    shopping_stat = "纯玩无购物团"
                elif "无购物" in col_shop or "纯玩" in col_shop:
                    shopping_stat = "纯玩无购物团"
                elif col_shop == "" or col_shop == "-" or len(col_shop) < 2:
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
            clean_json = clean_json.split("```")[1].split("```")[0].strip()
        
        data = json.loads(clean_json)
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list):
                    for row in v:
                        if isinstance(row, dict):
                            items.append({
                                "agency": default_agency,
                                "destination": row.get("destination", k),
                                "tour_code": row.get("tour_code", "-"),
                                "title": row.get("title", ""),
                                "departure_location": row.get("departure_location", "新加坡起飞"),
                                "departure_dates": row.get("departure_dates", ""),
                                "price": row.get("price", 2999),
                                "shopping_status": row.get("shopping_status", "纯玩无购物团")
                            })
        elif isinstance(data, list):
            for row in data:
                if isinstance(row, dict):
                    items.append({
                        "agency": default_agency,
                        "destination": row.get("destination", "精选目的地"),
                        "tour_code": row.get("tour_code", "-"),
                        "title": row.get("title", ""),
                        "departure_location": row.get("departure_location", "新加坡起飞"),
                        "departure_dates": row.get("departure_dates", ""),
                        "price": row.get("price", 2999),
                        "shopping_status": row.get("shopping_status", "纯玩无购物团")
                    })
    except Exception:
        pass
    return items

def call_gemini_cluster_agent(img_chunk, cluster_name):
    if not GEMINI_API_KEY:
        return []

    enhancer = ImageEnhance.Contrast(img_chunk)
    img_chunk = enhancer.enhance(1.6)
    enhancer_sharp = ImageEnhance.Sharpness(img_chunk)
    img_chunk = enhancer_sharp.enhance(2.0)

    buf = BytesIO()
    img_chunk.save(buf, format="JPEG", quality=95)
    base64_data = base64.b64encode(buf.getvalue()).decode('utf-8')

    prompt = (
        f"你是一位拥有顶级视觉审计能力的旅游海报专家。当前正在审核【{cluster_name}】板块。\n"
        "【绝对完美提取铁律】：\n"
        "1. 请把该板块里所有的团号、路线、起飞地、每一个出发日期（必须完整包含真实年份，如 DD/MM/YYYY）、以及对应的团费（RM）100%全量提取出来！\n"
        "2. 输出规范：必须返回严格合法的纯 JSON 数组格式（不附加任何 markdown 额外说明）：\n"
        "[\n"
        '  {"destination": "北京", "tour_code": "SP002579", "title": "7天6夜 天津 北京京津奇遇记", "departure_location": "新加坡起飞 (SIN)", "departure_dates": "21/11/2026", "price": 3299, "shopping_status": "纯玩无购物团"},\n'
        "  ...\n"
        "]"
    )

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
                    items = parse_json_response(raw_text, default_agency="豪吉旅游")
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

if "file_uploader_key" not in st.session_state:
    st.session_state.file_uploader_key = 0

col_up_1, col_up_2 = st.columns([4, 1])
with col_up_2:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🗑️ 一键清除所有照片", use_container_width=True):
        st.session_state.file_uploader_key += 1
        st.rerun()

with col_up_1:
    uploaded_files = st.file_uploader(
        "📷 请上传旅游海报图片（支持一次性选择多张图片批量处理）", 
        type=["jpg", "jpeg", "png"], 
        accept_multiple_files=True,
        key=f"uploader_{st.session_state.file_uploader_key}"
    )

if uploaded_files:
    agency_choice = st.radio("请选择这些海报对应的旅行社：", ["豪吉旅游", "琦琦旅游", "其他新旅行社"], horizontal=True)

    if st.button("🚀 启动批量无缝全量一键提取", type="primary", use_container_width=True):
        newly_extracted = []
        progress_bar = st.progress(0.0)
        status_box = st.empty()

        total_files = len(uploaded_files)
        for f_idx, uploaded_file in enumerate(uploaded_files):
            status_box.markdown(f"📦 正在处理第 **{f_idx + 1} / {total_files}** 张海报 ({uploaded_file.name})...")
            progress_bar.progress((f_idx) / total_files)

            img = Image.open(BytesIO(uploaded_file.getvalue()))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            w, h = img.size

            if agency_choice == "琦琦旅游":
                buf = BytesIO()
                img.save(buf, format="JPEG", quality=95)
                base64_data = base64.b64encode(buf.getvalue()).decode('utf-8')
                
                # 智能检测整张海报是否全程无购物
                check_prompt = "请用一句话回答：这张海报标题、底部或角落是否写着‘全程无购物站’或‘无购物’？只回答‘是’或‘否’。"
                check_payload = {
                    "contents": [{"parts": [{"text": check_prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": base64_data}}]}],
                    "generationConfig": {"temperature": 0.0, "maxOutputTokens": 50}
                }
                headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}
                poster_is_pure = False
                try:
                    chk_res = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{PRIMARY_MODEL}:generateContent?key={GEMINI_API_KEY}", headers=headers, json=check_payload, timeout=20)
                    if chk_res.status_code == 200:
                        ans = chk_res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                        if "是" in ans:
                            poster_is_pure = True
                except Exception:
                    pass

                prompt = "请提取琦琦旅游表格。格式：序号 | 出发日期 (完整包含真实的日/月/年如DD/MM/YYYY) | 天数 | 行程亮点 | 航空 | 无购物站 | 团费RM"
                payload = {
                    "contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": base64_data}}]}],
                    "generationConfig": {"temperature": 0.0, "maxOutputTokens": 16384}
                }
                raw_items = []
                for model_name in [PRIMARY_MODEL, BACKUP_MODEL]:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
                    res = requests.post(url, headers=headers, json=payload, timeout=90)
                    if res.status_code == 200:
                        raw_items = parse_qiqi_lines(res.json()["candidates"][0]["content"]["parts"][0]["text"], poster_is_pure_non_shopping=poster_is_pure)
                        if raw_items:
                            break
            else:
                clusters = [
                    ("左上聚落", (0, 0, int(w * 0.42), int(h * 0.55))),
                    ("中上聚落", (int(w * 0.25), 0, int(w * 0.75), int(h * 0.55))),
                    ("右上聚落", (int(w * 0.58), 0, w, int(h * 0.55))),
                    ("左下聚落", (0, int(h * 0.42), int(w * 0.42), h)),
                    ("中下聚落", (int(w * 0.25), int(h * 0.42), int(w * 0.75), h)),
                    ("右下聚落", (int(w * 0.58), int(h * 0.42), w, h))
                ]

                raw_items = []
                for cluster_name, box_coords in clusters:
                    cropped_img = img.crop(box_coords)
                    cluster_items = call_gemini_cluster_agent(cropped_img, cluster_name)
                    raw_items.extend(cluster_items)

            for item in raw_items:
                rows = split_and_explode_dates(
                    item.get("agency", agency_choice),
                    item.get("destination", "精选路线"),
                    item.get("tour_code", "-"),
                    item.get("title", ""),
                    item.get("departure_location", ""),
                    item.get("departure_dates", ""),
                    item.get("price", 2999),
                    shopping_status=item.get("shopping_status", "纯玩无购物团"),
                    forced_agency=agency_choice
                )
                newly_extracted.extend(rows)

            # 💎 关键防洪缓冲：处理多张大图时自动停顿 0.5 秒，绝对不超时
            time.sleep(0.5)

        progress_bar.progress(1.0)
        status_box.markdown("✨ 正在进行全局去重与【绝对价格从低到高】严格升序排序...")

        if newly_extracted:
            if work_mode == "🌐 公共共享模式 (多人实时同步)":
                combined = st.session_state.shared_tour_data + newly_extracted
            else:
                combined = st.session_state.private_tour_data + newly_extracted

            unique_combined = []
            seen = set()
            for item in combined:
                key = (item["agency"], item["tour_code"], item["departure_dates"], item["price_numeric"])
                if key not in seen:
                    seen.add(key)
                    unique_combined.append(item)

            unique_combined = sorted(unique_combined, key=lambda x: (x['destination'], x['price_numeric'], x['departure_dates']))

            if work_mode == "🌐 公共共享模式 (多人实时同步)":
                st.session_state.shared_tour_data = unique_combined
                save_persisted_data(unique_combined)
            else:
                st.session_state.private_tour_data = unique_combined

            trigger_play_on_done(len(unique_combined))
            st.success(f"🎉 批量提取完成！当前【{work_mode}】共有 **{len(unique_combined)}** 个精准团期（已按价格从低到高排好）。")
            time.sleep(1.0)
            st.rerun()
        else:
            st.warning("⚠️ 未能从上传的图片中解析出有效团期，请检查图片或重新点击。")

current_display_data = st.session_state.shared_tour_data if work_mode == "🌐 公共共享模式 (多人实时同步)" else st.session_state.private_tour_data

if current_display_data:
    if st.button(f"🗑️ 清空当前【{work_mode}】的数据库记录", use_container_width=True):
        if work_mode == "🌐 公共共享模式 (多人实时同步)":
            save_persisted_data([])
            st.session_state.shared_tour_data = []
        else:
            st.session_state.private_tour_data = []
        st.rerun()

    st.markdown("---")
    df = pd.DataFrame(current_display_data)
    df['price_numeric'] = pd.to_numeric(df['price_numeric'], errors='coerce').fillna(0).astype(int)

    df = df.sort_values(by=['destination', 'price_numeric', 'departure_dates'], ascending=[True, True, True])

    st.sidebar.header("🎛️ 高级筛选面板")
    clean_agencies = sorted(list({str(a) for a in df['agency'] if pd.notna(a) and str(a).strip()}))
    selected_agency = st.sidebar.selectbox("选择旅行社", ["全部"] + clean_agencies)

    clean_dests = sorted(list({str(d) for d in df['destination'] if pd.notna(d) and str(d).strip()}))
    selected_dest = st.sidebar.selectbox("选择目的地", ["全部"] + clean_dests)

    loc_options = [
        "全部",
        "🇲🇾 马来西亚全部地区 (包含吉隆坡KUL / 新山JB / 梳邦)",
        "🇲🇾 马来西亚起飞 (KUL)",
        "🇲🇾 新山/梳邦出发 (JB)",
        "🇸🇬 新加坡起飞 (SIN)"
    ]
    selected_loc = st.sidebar.selectbox("选择起飞地点", loc_options)

    selected_hol = st.sidebar.selectbox("🗓️ 学校假期筛选", ["全部日期", "🎒 包含学校假期 (含超出2天内)", "✨ 严格在学校假期内 (0超出)", "💼 仅平时非假期"])

    selected_shop = st.sidebar.selectbox("🛒 购物属性筛选", ["全部团", "✨ 仅看纯玩无购物团", "🛍️ 仅看含购物团"])

    filtered_df = df.copy()
    if selected_agency != "全部":
        filtered_df = filtered_df[filtered_df['agency'] == selected_agency]
    if selected_dest != "全部":
        filtered_df = filtered_df[filtered_df['destination'] == selected_dest]

    if selected_loc == "🇲🇾 马来西亚全部地区 (包含吉隆坡KUL / 新山JB / 梳邦)":
        filtered_df = filtered_df[filtered_df['departure_location'].str.contains("马来西亚|新山|梳邦|KUL|JB", na=False)]
    elif selected_loc == "🇲🇾 马来西亚起飞 (KUL)":
        filtered_df = filtered_df[filtered_df['departure_location'].str.contains("KUL|马来西亚", na=False)]
    elif selected_loc == "🇲🇾 新山/梳邦出发 (JB)":
        filtered_df = filtered_df[filtered_df['departure_location'].str.contains("JB|新山|梳邦", na=False)]
    elif selected_loc == "🇸🇬 新加坡起飞 (SIN)":
        filtered_df = filtered_df[filtered_df['departure_location'].str.contains("SIN|新加坡", na=False)]

    if selected_hol == "🎒 包含学校假期 (含超出2天内)":
        filtered_df = filtered_df[filtered_df['holiday_status'].isin(['exact', 'slight_over'])]
    elif selected_hol == "✨ 严格在学校假期内 (0超出)":
        filtered_df = filtered_df[filtered_df['holiday_status'] == 'exact']
    elif selected_hol == "💼 仅平时非假期":
        filtered_df = filtered_df[filtered_df['holiday_status'] == 'none']

    if selected_shop == "✨ 仅看纯玩无购物团":
        filtered_df = filtered_df[filtered_df['shopping_status'] == '纯玩无购物团']
    elif selected_shop == "🛍️ 仅看含购物团":
        filtered_df = filtered_df[filtered_df['shopping_status'] == '含购物团']

    p_min = int(df['price_numeric'].min()) if not df.empty else 1000
    p_max = int(df['price_numeric'].max()) if not df.empty else 9000
    if p_min >= p_max:
        p_max = p_min + 100
    price_range = st.sidebar.slider("💰 团费预算范围 (RM)", min_value=p_min, max_value=p_max, value=(p_min, p_max), step=100)
    filtered_df = filtered_df[(filtered_df['price_numeric'] >= price_range[0]) & (filtered_df['price_numeric'] <= price_range[1])]

    filtered_df = filtered_df.sort_values(by=['destination', 'price_numeric', 'departure_dates'], ascending=[True, True, True])

    st.markdown(f"### 符合条件的出发选项共 **{len(filtered_df)}** 个（已按团费价格从低到高精细排序）：")
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("📊 下载 CSV 比价清单", data=filtered_df.to_csv(index=False).encode('utf-8-sig'), file_name="智能比价清单.csv", mime="text/csv", use_container_width=True)
    with col2:
        st.download_button("🖼️ 下载高清长图 (.png)", data=generate_comparison_image(filtered_df), file_name="智能比价长图.png", mime="image/png", use_container_width=True)

    st.markdown("#### 📋 旅游团比对详情卡片 (已按价格由低到高排列)")
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
                shop_stat = row.get('shopping_status', '纯玩无购物团')
                if shop_stat == '纯玩无购物团':
                    st.markdown("🟢 `纯玩无购物`")
                else:
                    st.markdown("🟠 `含购物站点`")
                
                h_stat = row['holiday_status']
                if h_stat == 'exact':
                    st.success(f"🎒 完美在校假内 ({row['holiday_name']})")
                elif h_stat == 'slight_over':
                    st.warning(f"⚠️ 包含校假，超 {row['over_days']} 天 (需请假)")
            with c3:
                st.markdown(f"### 💰 **{row['price_text']}**")
