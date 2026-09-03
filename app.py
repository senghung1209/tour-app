import streamlit as st
import pandas as pd
import time
import datetime
import re
import json
import base64
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

st.set_page_config(page_title="跨社旅游团比价筛选中心", page_icon="✈️", layout="wide")

st.title("✈️ 跨旅行社海报聚合与横向对比中心 (Gemini 官方极速版)")
st.markdown("已接入 Google 官方新一代视觉通道，已加固长表 23 行全量提取，起飞地清晰拆分。")

OFFICIAL_HOLIDAYS = [
    (datetime.date(2026, 3, 20), datetime.date(2026, 3, 29), "2026 第一学期假期 (3月)"),
    (datetime.date(2026, 5, 22), datetime.date(2026, 6, 7), "2026 年中假期 (5/6月)"),
    (datetime.date(2026, 8, 28), datetime.date(2026, 9, 6), "2026 第二学期假期 (8/9月)"),
    (datetime.date(2026, 12, 4), datetime.date(2027, 1, 3), "2026 学年末大假期 (12月)"),
    (datetime.date(2027, 1, 23), datetime.date(2027, 2, 16), "2027 农历新年与跨年假期")
]

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

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
    if any(k in s for k in ["新加坡", "SIN", "CHANGI", "TR"]):
        return "🇸🇬 新加坡起飞 (SIN)"
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

@st.cache_data(ttl=3600)
def get_available_gemini_models():
    list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    headers = {"x-goog-api-key": GEMINI_API_KEY}
    candidates = []
    try:
        res = requests.get(list_url, headers=headers, timeout=10)
        if res.status_code == 200:
            models_data = res.json().get("models", [])
            for m in models_data:
                methods = m.get("supportedGenerationMethods", [])
                if "generateContent" in methods:
                    name = m.get("name", "").replace("models/", "")
                    candidates.append(name)
    except Exception:
        pass
    
    if candidates:
        flash_models = [m for m in candidates if "flash" in m]
        other_models = [m for m in candidates if "flash" not in m]
        return flash_models + other_models

    return ["gemini-3.5-flash", "gemini-3.7-flash", "gemini-3.8-flash", "gemini-2.5-flash"]

def call_gemini_official_vision(image_bytes):
    if not GEMINI_API_KEY:
        raise ValueError("未检测到 GEMINI_API_KEY，请在 Streamlit 后台 Secrets 中配置")

    img = Image.open(BytesIO(image_bytes))
    if img.mode != 'RGB':
        img = img.convert('RGB')
    w, h = img.size
    if max(w, h) > 2000:
        scale = 2000.0 / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=90)
    base64_data = base64.b64encode(buf.getvalue()).decode('utf-8')

    prompt = """
    你是一个专业的高精度旅游海报表格提取引擎。请仔细逐行阅读海报表格，提取所有行，绝不能有任何跳行或遗漏！
    重要规则：
    1. 表格内有多少个序号行（例如序号 1 到 23），就必须提取出整整多少条数据对象！
    2. 如果某行特别标注“新加坡起飞”或航空公司是 TR，departure_location 标为“新加坡起飞 (SIN)”；否则统一填写“马来西亚起飞 (KUL)”。
    3. 行程若有多个出发日，全部写在 departure_dates 字段中，用逗号隔开。
    4. 务必输出合法的纯 JSON 数组，严禁任何 Markdown 外皮或注释：
    [
      {
        "agency": "旅行社名称(如 琦琦旅游/豪吉旅游)",
        "destination": "目的地(如 江南/张家界/九寨沟)",
        "tour_code": "团号或序号",
        "title": "行程亮点全称",
        "departure_location": "新加坡起飞 (SIN) 或 马来西亚起飞 (KUL)",
        "departure_dates": "出发日期(如 13/09/2026)",
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

    available_models = get_available_gemini_models()
    last_error = ""

    for model_name in available_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=60)
            if res.status_code == 200:
                res_json = res.json()
                raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
                clean_json = re.search(r'\[.*\]', raw_text, re.DOTALL)
                if clean_json:
                    return json.loads(clean_json.group(0))
                return json.loads(raw_text)
            else:
                last_error = f"{model_name} HTTP {res.status_code}: {res.text[:140]}"
        except Exception as ex:
            last_error = f"{model_name} 异常: {str(ex)}"

    raise RuntimeError(f"Google 官方 API 调用失败: {last_error}")

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

c_up, c_rst = st.columns([4, 1])
with c_up:
    uploaded_files = st.file_uploader("📷 上传旅行社海报图片 (支持任意新海报，可多选)", type=["jpg", "jpeg", "png"], accept_multiple_files=True)
with c_rst:
    st.write("")
    st.write("")
    if st.button("🗑️ 清空重置", use_container_width=True):
        st.session_state.tour_data = []
        st.rerun()

if uploaded_files:
    st.success(f"已选择 {len(uploaded_files)} 张海报图片")
    if st.button("🚀 启动 Google 官方视觉极速比价", type="primary"):
        all_exploded = []
        progress_bar = st.progress(0.0)
        status_text = st.empty()
        has_error = False

        for idx, f in enumerate(uploaded_files):
            status_text.text(f"🔍 正在由 Gemini 逐行完整解析: {f.name} ...")
            try:
                raw_items = call_gemini_official_vision(f.getvalue())
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
                    all_exploded.extend(rows)
            except Exception as e:
                has_error = True
                st.error(f"解析 {f.name} 时提示: {e}")

            progress_bar.progress((idx + 1) / len(uploaded_files))
            time.sleep(1)  # 平滑控制请求间隔，避免触发 RPM

        if not has_error and all_exploded:
            # 去除过度去重，完整保留海报所有行
            st.session_state.tour_data = all_exploded
            status_text.text("✅ 全部海报解析完成！")
            st.rerun()
        elif not has_error and not all_exploded:
            status_text.text("⚠️ 未能从海报提取到有效团期数据。")

if st.session_state.tour_data:
    st.markdown("---")
    df = pd.DataFrame(st.session_state.tour_data)
    df['price_numeric'] = pd.to_numeric(df['price_numeric'], errors='coerce').fillna(0).astype(int)

    with st.expander("🛠️ 快速数据校对面板 (双击可修改文字/价格，可自主增删行)", expanded=False):
        edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)
        if not edited_df.equals(df):
            st.session_state.tour_data = edited_df.to_dict('records')
            st.rerun()

    st.sidebar.header("🎛️ 筛选条件")
    
    clean_agencies = sorted(list({str(a) for a in df['agency'] if pd.notna(a) and str(a).strip()}))
    selected_agency = st.sidebar.selectbox("选择旅行社", ["全部"] + clean_agencies)

    clean_dests = sorted(list({str(d) for d in df['destination'] if pd.notna(d) and str(d).strip()}))
    selected_dest = st.sidebar.selectbox("选择目的地", ["全部"] + clean_dests)

    loc_options = ["全部", "🇲🇾 马来西亚起飞 (KUL)", "🇸🇬 新加坡起飞 (SIN)"]
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

    st.markdown("### 📥 导出选项")
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("📊 下载 CSV 比价清单", data=filtered_df.to_csv(index=False).encode('utf-8-sig'), file_name="智能比价清单.csv", mime="text/csv", use_container_width=True)
    with col2:
        st.download_button("🖼️ 下载精美长图 (.png)", data=generate_comparison_image(filtered_df), file_name="智能比价长图.png", mime="image/png", use_container_width=True)

    st.markdown(f"### 符合条件的出发选项共 **{len(filtered_df)}** 个：")
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
