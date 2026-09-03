import streamlit as st
import pandas as pd
import datetime
import re
import json
import base64
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

st.set_page_config(page_title="跨社旅游团比价筛选中心", page_icon="✈️", layout="wide")

st.title("✈️ 跨旅行社海报聚合与横向对比中心")
st.caption("🚀 已适配豪吉旅游拼贴海报与琦琦长表，支持分批增量累加。")

OFFICIAL_HOLIDAYS = [
    (datetime.date(2026, 3, 20), datetime.date(2026, 3, 29), "2026 第一学期假期 (3月)"),
    (datetime.date(2026, 5, 22), datetime.date(2026, 6, 7), "2026 年中假期 (5/6月)"),
    (datetime.date(2026, 8, 28), datetime.date(2026, 9, 6), "2026 第二学期假期 (8/9月)"),
    (datetime.date(2026, 12, 4), datetime.date(2027, 1, 3), "2026 学年末大假期 (12月)"),
    (datetime.date(2027, 1, 23), datetime.date(2027, 2, 16), "2027 农历新年与跨年假期")
]

RAW_KEY = st.secrets.get("GEMINI_API_KEY", "")
GEMINI_API_KEY = str(RAW_KEY).strip() if RAW_KEY else ""
LOCKED_MODEL = "gemini-3.5-flash"

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

def safe_parse_json(raw_text):
    clean_text = raw_text.strip()
    clean_text = re.sub(r'^```json\s*', '', clean_text, flags=re.MULTILINE)
    clean_text = re.sub(r'^```\s*', '', clean_text, flags=re.MULTILINE)
    
    match = re.search(r'\[.*\]', clean_text, re.DOTALL)
    if match:
        clean_text = match.group(0)
    
    try:
        return json.loads(clean_text)
    except Exception:
        clean_text_fixed = re.sub(r',\s*([\]}])', r'\1', clean_text)
        return json.loads(clean_text_fixed)

def call_gemini_vision_direct(image_bytes):
    if not GEMINI_API_KEY:
        raise ValueError("未检测到 GEMINI_API_KEY，请在 Streamlit 后台 Secrets 中配置")

    img = Image.open(BytesIO(image_bytes))
    if img.mode != 'RGB':
        img = img.convert('RGB')
    w, h = img.size
    if max(w, h) > 1800:
        scale = 1800.0 / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    base64_data = base64.b64encode(buf.getvalue()).decode('utf-8')

    prompt = """
    你是一个专业高精度旅游海报提取引擎。
    海报特征识别：
    1. 旅行社识别：若海报包含多格拼贴团期（例如包含 SP 开头的团号、或者联系人SIONG/ALEX），该海报旅行社统一命名为“豪吉旅游”；若是表格型海报（如琦琦），则按其实际标题命名。
    2. 多价格拆分规则：一个小方块里如果有不同的出发日期对应不同价格（例如某个团期写着 17/11/26 卖 3299，15/12/26 卖 3999），请务必拆分为多条独立数据项输出！
    3. 出发地点判断：
       - 标题带 SIN、新加坡、或航司酷航(Scoot)的，写“新加坡起飞 (SIN)”
       - 标题带 JB、新山的，写“新山出发 (JB)”
       - 标题带 KL 或默认的，写“马来西亚起飞 (KUL)”
    4. 务必输出标准 JSON 数组，严禁任何 markdown 标签，字符串内不要包含未经转义的双引号：
    [
      {
        "agency": "旅行社名称(如 豪吉旅游 / 琦琦旅游)",
        "destination": "目的地(如 重庆/贵州/北疆/西藏/哈尔滨/九寨沟)",
        "tour_code": "团号(如 SP002376)",
        "title": "行程路线名(如 7天6夜 重庆8D风采线)",
        "departure_location": "起飞地",
        "departure_dates": "出发日期(如 31/12/2026)",
        "price": 2999
      }
    ]
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
            "maxOutputTokens": 8192,
            "response_mime_type": "application/json"
        }
    }

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{LOCKED_MODEL}:generateContent?key={GEMINI_API_KEY}"
    res = requests.post(url, headers=headers, json=payload, timeout=60)
    
    if res.status_code == 200:
        res_json = res.json()
        raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
        return safe_parse_json(raw_text)
    else:
        raise RuntimeError(f"API 响应错误 (HTTP {res.status_code}): {res.text[:120]}")

def generate_comparison_image(df):
    w, rh, hh = 850, 40, 70
    h = hh + len(df) * rh + 30
    img = Image.new("RGB", (w, max(h, 200)), color=(248, 250, 252))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    draw.rectangle([0, 0, w, hh], fill=(15, 23, 42))
    draw.text((25, 25), f"旅游团比价汇总清单 (共 {len(df)} 项出发日期)", fill=(255, 255, 255), font=font)

    y = hh + 10
    draw.rectangle([15, y, w - 15, y + 28], fill=(226, 232, 240))
    cols = [("旅行社", 25), ("目的地", 160), ("团号", 240), ("出发日期", 330), ("价格", 440), ("起飞地", 530), ("行程名称", 670)]
    for name, x in cols:
        draw.text((x, y + 7), name, fill=(30, 41, 59), font=font)

    y += 35
    for _, r in df.iterrows():
        draw.text((25, y), str(r['agency'])[:10], fill=(71, 85, 105), font=font)
        draw.text((160, y), str(r['destination'])[:6], fill=(15, 23, 42), font=font)
        draw.text((240, y), str(r['tour_code'])[:10], fill=(71, 85, 105), font=font)
        draw.text((330, y), str(r['departure_dates'])[:12], fill=(30, 41, 59), font=font)
        draw.text((440, y), str(r['price_text']), fill=(220, 38, 38), font=font)
        draw.text((530, y), str(r['departure_location'])[:12], fill=(2, 132, 199), font=font)
        draw.text((670, y), str(r['title'])[:16], fill=(71, 85, 105), font=font)
        y += rh

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

if "tour_data" not in st.session_state:
    st.session_state.tour_data = []

uploaded_files = st.file_uploader("📷 上传旅行社海报图片 (支持长表/拼贴海报，分批多次追加)", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

if uploaded_files:
    st.info(f"已选择 {len(uploaded_files)} 张海报图片")
    if st.button("🚀 极速解析并追加到总库", type="primary", use_container_width=True):
        newly_extracted = []
        progress_bar = st.progress(0.0)
        status_text = st.empty()
        has_error = False

        for idx, f in enumerate(uploaded_files):
            status_text.info(f"⚡ [{idx+1}/{len(uploaded_files)}] 正在解析: `{f.name}` ...")
            try:
                raw_items = call_gemini_vision_direct(f.getvalue())
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
            except Exception as e:
                has_error = True
                status_text.error(f"处理 {f.name} 时提示: {e}")

            progress_bar.progress((idx + 1) / len(uploaded_files))

        if not has_error and newly_extracted:
            combined = st.session_state.tour_data + newly_extracted
            seen = set()
            unique_combined = []
            for item in combined:
                marker = (item["agency"], item["title"], item["departure_dates"], item["price_numeric"])
                if marker not in seen:
                    seen.add(marker)
                    unique_combined.append(item)

            st.session_state.tour_data = unique_combined
            st.success(f"🎉 解析完成！成功追加数据，当前总库共计 {len(st.session_state.tour_data)} 项出发日期。")
            st.rerun()

if st.session_state.tour_data:
    if st.button("🗑️ 清空总库全部数据", use_container_width=True):
        st.session_state.tour_data = []
        st.rerun()

    st.markdown("---")
    df = pd.DataFrame(st.session_state.tour_data)
    df['price_numeric'] = pd.to_numeric(df['price_numeric'], errors='coerce').fillna(0).astype(int)

    with st.expander(f"🛠️ 快速数据校对面板 (当前总库共有 {len(df)} 项，可直接修改/增删行)", expanded=False):
        edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)
        if not edited_df.equals(df):
            st.session_state.tour_data = edited_df.to_dict('records')
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
