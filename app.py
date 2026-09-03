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

# 高清中文字体自动获取（已前置定义，解决 NameError）
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

    local_font = "wqy-microhei.ttc"
    if not os.path.exists(local_font):
        try:
            url = "https://github.com/anthonyfok/fonts-wqy-microhei/raw/master/wqy-microhei.ttc"
            urllib.request.urlretrieve(url, local_font)
            return ImageFont.truetype(local_font, font_size)
        except Exception:
            pass
    return ImageFont.load_default()

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
    <div style="font-size: 13px; color: #2563eb; margin-bottom: 10px;">
        请先点击下方按钮授权系统通知权限。分析完毕后，<b>手机通知栏会弹窗提醒</b>：
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

components.html(native_audio_html, height=130)

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

def parse_haoji_text(raw_text):
    items = []
    for line in raw_text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "旅行社|目的地" in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 7:
            try:
                price_val = int(re.sub(r'[^\d]', '', parts[6]))
            except Exception:
                price_val = 0
            items.append({
                "agency": "豪吉旅游",
                "destination": parts[1] or "精选目的地",
                "tour_code": parts[2] or "-",
                "title": parts[3] or "",
                "departure_location": parts[4] or "",
                "departure_dates": parts[5] or "",
                "price": price_val
            })
    return items

def parse_qiqi_text(raw_text):
    items = []
    for line in raw_text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "序号|出发日期" in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 6:
            try:
                price_val = int(re.sub(r'[^\d]', '', parts[5]))
            except Exception:
                price_val = 0
            
            days_str = parts[2] or "6天5夜"
            title_str = f"{days_str} {parts[3]}"
            raw_dest = parts[3]
            clean_dest = raw_dest.split("+")[0].split(" ")[0].strip()
            airline = parts[4].upper()
            loc = "新加坡起飞 (SIN)" if "TR" in airline else "马来西亚起飞 (KUL)"

            items.append({
                "agency": "琦琦旅游",
                "destination": clean_dest if clean_dest else "精选目的地",
                "tour_code": f"QIQI-{parts[0]}",
                "title": title_str,
                "departure_location": loc,
                "departure_dates": parts[1],
                "price": price_val
            })
    return items

def call_gemini_vision(img_bytes, poster_type):
    if not GEMINI_API_KEY:
        st.error("未检测到 GEMINI_API_KEY")
        return []

    buf = BytesIO(img_bytes)
    base64_data = base64.b64encode(buf.getvalue()).decode('utf-8')

    if poster_type == "haoji":
        prompt = """
        你是豪吉旅游海报解析专家。请全量提取该图内的全部团期。
        规则：并列日期（如05/11, 26/11）或上下两排不同价格必须拆为独立行！
        纯文本逐行输出，竖线 | 分隔，不要代码块：
        豪吉旅游|目的地纯地名|团号(SP开头)|行程路线全称|起飞地|出发日期|纯数字价格
        """
    else:
        prompt = """
        你是琦琦旅游表格海报解析专家。请将表格内第1项到第23项全部提取出来。
        纯文本逐行输出，竖线 | 分隔，不要代码块：
        序号|出发日期(如13/09/2026)|天数(如6天5夜)|行程亮点(如江南+上海迪士尼)|航空(如TR/D7/MU)|纯数字团费
        """

    payload = {
        "contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": base64_data}}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 8192}
    }
    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}

    for model_name in [PRIMARY_MODEL, BACKUP_MODEL]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=60)
            if res.status_code == 200:
                raw_text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                if poster_type == "haoji":
                    return parse_haoji_text(raw_text)
                else:
                    return parse_qiqi_text(raw_text)
        except Exception:
            pass
    return []

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

uploaded_files = st.file_uploader("📷 上传旅行社海报图片 (支持豪吉与琦琦海报混合上传)", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

if uploaded_files:
    st.info(f"已选择 {len(uploaded_files)} 张海报图片")
    if st.button("🚀 启动独立双通道精准扫描并追加", type="primary", use_container_width=True):
        newly_extracted = []
        progress_bar = st.progress(0.0)
        status_box = st.empty()

        total_files = len(uploaded_files)

        for f_idx, f in enumerate(uploaded_files):
            img_bytes = f.getvalue()
            img = Image.open(BytesIO(img_bytes))
            w, h = img.size

            filename_upper = f.name.upper()
            if "QIQI" in filename_upper or h < w * 1.35:
                status_box.markdown(f"**[{f_idx+1}/{total_files}]** 🔍 正在独立扫描琦琦旅游超值表格...")
                progress_bar.progress(0.5)
                raw_items = call_gemini_vision(img_bytes, "qiqi")
            else:
                status_box.markdown(f"**[{f_idx+1}/{total_files}]** 🔍 正在分区域扫描豪吉海报...")
                progress_bar.progress(0.25)
                r1 = call_gemini_vision(img.crop((0, 0, w, int(h * 0.58))).tobytes(), "haoji")
                progress_bar.progress(0.70)
                r2 = call_gemini_vision(img.crop((0, int(h * 0.44), w, h)).tobytes(), "haoji")
                raw_items = r1 + r2

            progress_bar.progress(1.0)
            status_box.markdown("✨ 正在清洗数据并入库...")

            for item in raw_items:
                days = extract_tour_days(item.get("title", ""))
                d_token = item.get("departure_dates", "")
                status, over_days, hol_name = evaluate_holiday_fit(d_token, days)
                
                newly_extracted.append({
                    "agency": item.get("agency", "精选旅行社"),
                    "destination": item.get("destination", "精选目的地"),
                    "tour_code": item.get("tour_code", "-"),
                    "title": item.get("title", ""),
                    "departure_location": item.get("departure_location", "马来西亚起飞 (KUL)"),
                    "departure_dates": d_token,
                    "price_numeric": item.get("price", 0),
                    "price_text": f"RM {item.get('price', 0)}",
                    "holiday_status": status,
                    "over_days": over_days,
                    "holiday_name": hol_name
                })

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
            st.success(f"🎉 扫描全部完成！总库已更新至 **{len(st.session_state.tour_data)}** 条团期。")
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

    with st.expander(f"🛠️ 快速数据校对面板 (当前总库共有 {len(df)} 项，支持修改/增删行)", expanded=False):
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

    st.markdown(f"### 符合条件的出发选项共 **{len(filtered_df)}** 个：")
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
