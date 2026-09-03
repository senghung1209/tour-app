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

def parse_lines_robust(raw_text, poster_type):
    items = []
    for line in raw_text.strip().splitlines():
        line = line.strip().replace("```", "").replace("`", "")
        if not line or line.startswith("#") or "|" not in line or "旅行社" in line or "序号" in line:
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        try:
            if poster_type == "haoji" and len(parts) >= 5:
                price_val = 0
                for p in parts:
                    clean_p = re.sub(r'[^\d]', '', p)
                    if clean_p and len(clean_p) >= 3:
                        price_val = int(clean_p)
                        break

                tour_code = "SP-000"
                for p in parts:
                    if "SP" in p.upper():
                        tour_code = p
                        break

                dest = clean_destination_name(parts[0])
                title = parts[2] if len(parts) > 2 else dest
                loc = "🇸🇬 新加坡起飞 (SIN)" if any(k in line.upper() for k in ["SIN", "新加坡", "TR"]) else "🇲🇾 马来西亚起飞 (KUL)"
                dates = parts[4] if len(parts) > 4 else parts[len(parts) - 2]

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
                        "price_numeric": price_val if price_val > 0 else 2999,
                        "price_text": f"RM {price_val if price_val > 0 else 2999}",
                        "holiday_status": status,
                        "over_days": over_days,
                        "holiday_name": hol_name
                    })

            elif poster_type == "qiqi" and len(parts) >= 5:
                seq_no = parts[0]
                dep_date = parts[1]
                days_str = parts[2]
                highlights = parts[3]
                airline = parts[4].upper() if len(parts) > 4 else ""
                price_match = re.search(r'\d{3,5}', line)
                price_val = int(price_match.group(0)) if price_match else 2999

                dest = clean_destination_name(highlights.split("+")[0].split(" ")[0])
                title = f"{days_str} {highlights}"
                loc = "🇸🇬 新加坡起飞 (SIN)" if "TR" in airline or "新加坡" in line else "🇲🇾 马来西亚起飞 (KUL)"

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

def call_gemini_vision_debug(img_bytes, poster_type, hint=""):
    if not GEMINI_API_KEY:
        st.error("❌ 未检测到 GEMINI_API_KEY，请在 Streamlit 平台的 Secrets 中检查！")
        return []
        
    base64_data = base64.b64encode(img_bytes).decode('utf-8')

    if poster_type == "haoji":
        prompt = f"""
        你是高精度视觉专家。请提取海报中的所有旅游团期信息。{hint}
        每一行纯文本输出，必须用竖线 | 严格分隔，严禁使用代码块：
        目的地纯地名|团号(SP开头)|路线全称|起飞地|出发日期|纯数字价格
        例如：重庆|SP002376|7天6夜 重庆8D风暴线|新加坡起飞|31/12/26|2999
        """
    else:
        prompt = """
        你是琦琦旅游表格专家。请提取表格内第 1 项到第 23 项的全部团期。
        每一行纯文本输出，竖线 | 分隔，严禁代码块：
        序号|出发日期|天数|行程亮点|航空|纯数字团费
        例如：1|13/09/2026|6天5夜|江南+上海迪士尼|TR|2999
        """

    payload = {
        "contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": base64_data}}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 8192}
    }

    # 优先尝试稳定模型版本，若失败则切换备用
    candidate_models = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-3.5-flash"]
    last_error_text = ""

    for model_name in candidate_models:
        url = f"[https://generativelanguage.googleapis.com/v1beta/models/](https://generativelanguage.googleapis.com/v1beta/models/){model_name}:generateContent?key={GEMINI_API_KEY}"
        try:
            res = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=45)
            if res.status_code == 200:
                raw_text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                items = parse_lines_robust(raw_text, poster_type)
                if items:
                    return items
                else:
                    last_error_text = f"API 成功返回但解析行为空。模型原始回复前200字：\n{raw_text[:200]}"
            else:
                last_error_text = f"HTTP {res.status_code}：{res.text}"
        except Exception as err:
            last_error_text = f"请求异常：{str(err)}"

    # 将真实报错直接输出在屏幕上
    st.error(f"⚠️ 调试详情：{last_error_text}")
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

uploaded_file = st.file_uploader("📷 上传单张海报图片", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    poster_type_choice = st.radio("请确认这张海报属于哪家旅行社：", ["豪吉旅游 (拼贴海报)", "琦琦旅游 (超值表格)"], horizontal=True)
    poster_type = "haoji" if "豪吉" in poster_type_choice else "qiqi"

    if st.button("🚀 立即深度分析并入库", type="primary", use_container_width=True):
        with st.spinner("🔍 正在扫描分析中，请稍候..."):
            img_bytes = uploaded_file.getvalue()
            img = Image.open(BytesIO(img_bytes))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            w, h = img.size

            if poster_type == "haoji":
                box_top = (0, 0, w, int(h * 0.58))
                buf_top = BytesIO()
                img.crop(box_top).save(buf_top, format="JPEG", quality=90)
                r1 = call_gemini_vision_debug(buf_top.getvalue(), "haoji", "上半区：重庆、西藏、青岛、桂林、台湾、韩国")

                box_bottom = (0, int(h * 0.44), w, h)
                buf_bottom = BytesIO()
                img.crop(box_bottom).save(buf_bottom, format="JPEG", quality=90)
                r2 = call_gemini_vision_debug(buf_bottom.getvalue(), "haoji", "下半区：贵州、哈尔滨、北疆、九寨沟")

                newly_extracted = r1 + r2
            else:
                newly_extracted = call_gemini_vision_debug(img_bytes, "qiqi")

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
                st.success(f"🎉 成功提取 {len(newly_extracted)} 项！当前总库共有 **{len(st.session_state.tour_data)}** 项团期。")
                time.sleep(1.0)
                st.rerun()

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

    total_filtered_count = len(filtered_df)
    st.markdown(f"### 符合条件的出发选项共 **{total_filtered_count}** 个：")
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("📊 下载 CSV 比价清单", data=filtered_df.to_csv(index=False).encode('utf-8-sig'), file_name="智能比价清单.csv", mime="text/csv", use_container_width=True)
    with col2:
        st.download_button("🖼️ 下载高清长图 (.png)", data=generate_comparison_image(filtered_df), file_name="智能比价长图.png", mime="image/png", use_container_width=True)

    st.dataframe(filtered_df[['agency', 'destination', 'tour_code', 'departure_location', 'departure_dates', 'price_text', 'title']], use_container_width=True)

    st.markdown("#### 📋 行程比对卡片")
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
