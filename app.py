import streamlit as st
import pandas as pd
import datetime
import re
import os
import json
import threading
import time
import urllib.request
import base64
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import streamlit.components.v1 as components

st.set_page_config(page_title="跨社旅游团比价筛选中心", page_icon="✈️", layout="wide")

DB_FILE = "tour_database.json"
TASK_STATUS_FILE = "task_status.json"

def load_persisted_data():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_persisted_data(data):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def get_task_status():
    if os.path.exists(TASK_STATUS_FILE):
        try:
            with open(TASK_STATUS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"running": False, "msg": ""}
    return {"running": False, "msg": ""}

def set_task_status(running, msg=""):
    try:
        with open(TASK_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump({"running": running, "msg": msg}, f)
    except Exception:
        pass

if "tour_data" not in st.session_state:
    st.session_state.tour_data = load_persisted_data()

st.title("✈️ 跨旅行社海报聚合与横向对比中心")

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

def split_and_explode_dates(raw_agency, raw_dest, raw_code, raw_title, raw_loc, raw_dates_str, raw_price):
    days = extract_tour_days(raw_title)
    try:
        clean_price = int(re.sub(r'[^\d]', '', str(raw_price)))
    except Exception:
        clean_price = 0

    norm_loc = normalize_departure_location(raw_loc, raw_title)
    date_tokens = re.findall(r'\b\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?\b', str(raw_dates_str))
    if not date_tokens:
        date_tokens = [str(raw_dates_str).strip()]

    exploded = []
    for d_token in date_tokens:
        status, over_days, hol_name = evaluate_holiday_fit(d_token, days)
        exploded.append({
            "agency": str(raw_agency or "精选旅行社"),
            "destination": str(raw_dest or "精选路线"),
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

def parse_compact_lines(raw_text):
    clean_lines = raw_text.strip().splitlines()
    items = []
    for line in clean_lines:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("`") or "旅行社|目的地" in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 7:
            try:
                price_val = int(re.sub(r'[^\d]', '', parts[6]))
            except Exception:
                price_val = 0
            items.append({
                "agency": parts[0] or "精选旅行社",
                "destination": parts[1] or "精选目的地",
                "tour_code": parts[2] or "-",
                "title": parts[3] or "",
                "departure_location": parts[4] or "",
                "departure_dates": parts[5] or "",
                "price": price_val
            })
    return items

def call_gemini_vision_chunk(img_chunk, chunk_name):
    if not GEMINI_API_KEY:
        return []

    buf = BytesIO()
    img_chunk.save(buf, format="JPEG", quality=90)
    base64_data = base64.b64encode(buf.getvalue()).decode('utf-8')

    prompt = f"""
    你是极其严谨的旅游海报视觉专家。当前正在识别海报的【{chunk_name}】。
    请地毯式遍历当前图像包含的每一个色块小方块（涵盖重庆、西藏、青岛、桂林、台湾、韩国、贵州、哈尔滨、北疆、九寨沟等），不能漏掉任何一个团期！

    规则：
    1. 多日期拆分：若一个小方块写有多个出发日（例如 12/10/26, 25/5/27 对应 RM6999），必须按每个单独的出发日拆分成独立的一行！
    2. 旅行社：若海报含 SP 编号或豪吉标志，统一写“豪吉旅游”；表格型海报按其真实标头（如“琦琦旅游”）写。
    3. 起飞地点：含 SIN/新加坡/酷航 填“新加坡起飞 (SIN)”；含 JB/新山 填“新山出发 (JB)”；默认填“马来西亚起飞 (KUL)”。
    4. 逐行纯文本输出，字段用竖线 | 分隔，严禁 markdown 标记与额外说明：
    旅行社|目的地|团号|行程路线全称|起飞地|出发日期|纯数字价格
    """

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": base64_data
                        }
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 8192
        }
    }

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }

    for model_name in [PRIMARY_MODEL, BACKUP_MODEL]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        for attempt in range(2):
            try:
                res = requests.post(url, headers=headers, json=payload, timeout=50)
                if res.status_code == 200:
                    res_json = res.json()
                    raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
                    return parse_compact_lines(raw_text)
                if res.status_code == 503:
                    continue
                else:
                    break
            except requests.exceptions.Timeout:
                break
    return []

# 后台离线异步扫描函数（手机切走也继续在服务器跑）
def background_worker(files_data):
    try:
        set_task_status(True, "🚀 服务器后台正在极速扫描...")
        newly_extracted = []

        for f_bytes in files_data:
            img = Image.open(BytesIO(f_bytes))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            w, h = img.size

            if h > w * 1.2:
                # 25% 宽幅安全重叠，确保韩国/贵州/北疆绝对不被切断
                overlap = int(h * 0.25)
                mid_h = h // 2

                box_top = (0, 0, w, mid_h + overlap)
                box_bottom = (0, max(0, mid_h - overlap), w, h)

                set_task_status(True, "🔍 正在扫描上半区 (重庆/西藏/青岛/桂林/台湾/韩国)...")
                r1 = call_gemini_vision_chunk(img.crop(box_top), "上半区")

                set_task_status(True, "🔍 正在扫描下半区 (韩国/贵州/哈尔滨/北疆/九寨沟)...")
                r2 = call_gemini_vision_chunk(img.crop(box_bottom), "下半区")

                raw_items = r1 + r2
            else:
                set_task_status(True, "🔍 正在全幅扫描表格海报...")
                raw_items = call_gemini_vision_chunk(img, "全图")

            for item in raw_items:
                rows = split_and_explode_dates(
                    item.get("agency", "精选旅行社"),
                    item.get("destination", "精选路线"),
                    item.get("tour_code", "-"),
                    item.get("title", ""),
                    item.get("departure_location", ""),
                    item.get("departure_dates", ""),
                    item.get("price", 0)
                )
                newly_extracted.extend(rows)

        if newly_extracted:
            current_data = load_persisted_data()
            combined = current_data + newly_extracted
            seen = set()
            unique_combined = []
            for item in combined:
                marker = (item["agency"], item["title"], item["departure_dates"], item["price_numeric"])
                if marker not in seen:
                    seen.add(marker)
                    unique_combined.append(item)
            save_persisted_data(unique_combined)

        set_task_status(False, "FINISHED")
    except Exception as e:
        set_task_status(False, f"ERROR: {e}")

# 检查后台是否有正在跑的任务
task_info = get_task_status()
if task_info["running"]:
    st.warning(f"⚡ **后台正在自动运算中**：{task_info['msg']}")
    st.caption("你可以随意切去刷抖音/FB，服务器后台正在独立运行！稍后回来看即可。")
    time.sleep(3)
    st.rerun()

@st.cache_resource
def get_chinese_font(font_size=14):
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

def generate_comparison_image(df):
    w, rh, hh = 920, 38, 70
    h = hh + len(df) * rh + 30
    img = Image.new("RGB", (w, max(h, 200)), color=(248, 250, 252))
    draw = ImageDraw.Draw(img)
    font = get_chinese_font(13)
    title_font = get_chinese_font(20)

    draw.rectangle([0, 0, w, hh], fill=(15, 23, 42))
    draw.text((25, 22), f"旅游团比价汇总清单 (共 {len(df)} 项有效出发日期)", fill=(255, 255, 255), font=title_font)

    y = hh + 10
    draw.rectangle([15, y, w - 15, y + 28], fill=(226, 232, 240))
    cols = [("旅行社", 25), ("目的地", 160), ("团号", 250), ("出发日期", 350), ("价格", 460), ("起飞地", 550), ("行程名称", 700)]
    for name, x in cols:
        draw.text((x, y + 6), name, fill=(30, 41, 59), font=font)

    y += 35
    for _, r in df.iterrows():
        draw.text((25, y), str(r['agency'])[:9], fill=(71, 85, 105), font=font)
        draw.text((160, y), str(r['destination'])[:6], fill=(15, 23, 42), font=font)
        draw.text((250, y), str(r['tour_code'])[:10], fill=(71, 85, 105), font=font)
        draw.text((350, y), str(r['departure_dates'])[:12], fill=(30, 41, 59), font=font)
        draw.text((460, y), str(r['price_text']), fill=(220, 38, 38), font=font)
        draw.text((550, y), str(r['departure_location'])[:12], fill=(2, 132, 199), font=font)
        draw.text((700, y), str(r['title'])[:16], fill=(71, 85, 105), font=font)
        y += rh

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

uploaded_files = st.file_uploader("📷 上传旅行社海报图片 (已支持后台托管运行，可自由切出网页)", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

if uploaded_files:
    st.info(f"已选择 {len(uploaded_files)} 张海报图片")
    if st.button("🚀 启动后台离线提取 (点完即可切走刷抖音/FB)", type="primary", use_container_width=True):
        files_data = [f.getvalue() for f in uploaded_files]
        # 启动后台守护线程运行，不受浏览器切出影响
        t = threading.Thread(target=background_worker, args=(files_data,), daemon=True)
        t.start()
        st.rerun()

# 始终从磁盘持久化读取最新数据
st.session_state.tour_data = load_persisted_data()

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

    loc_options = ["全部", "🇲🇾 马来西亚起飞 (KUL)", "🇸🇬 新加坡起飞 (SIN)", "🇲🇾 新山出发 (JB)"]
    selected_loc = st.sidebar.selectbox("选择起飞地点", loc_options)

    selected_hol = st.sidebar.selectbox("🗓️ 学校假期筛选", ["全部日期", "🎒 包含学校假期 (含超出2天内)", "✨ 严格在学校假期内 (0超出)", "💼 仅平时非假期"])

    filtered_df = df.copy()
    if selected_agency != "全部":
        filtered_df = filtered_df[filtered_df['agency'] == selected_agency]
    if selected_dest != "全部":
        filtered_df = filtered_df[filtered_df['destination'] == selected_dest]
    if selected_loc != "全部":
        filtered_df = filtered_df[filtered_df['departure_location'] == selected_loc]

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
        st.download_button("🖼️ 下载精美长图 (.png)", data=generate_comparison_image(filtered_df), file_name="智能比价长图.png", mime="image/png", use_container_width=True)

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
