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

st.title("✈️ 跨旅行社海报聚合与横向对比中心 (Qwen2.5-VL 视觉版)")
st.markdown("通过 Hugging Face Serverless Vision API 驱动，支持识别任意全新排版海报并自动展开独立出发日。")

OFFICIAL_HOLIDAYS = [
    (datetime.date(2026, 3, 20), datetime.date(2026, 3, 29), "2026 第一学期假期 (3月)"),
    (datetime.date(2026, 5, 22), datetime.date(2026, 6, 7), "2026 年中假期 (5/6月)"),
    (datetime.date(2026, 8, 28), datetime.date(2026, 9, 6), "2026 第二学期假期 (8/9月)"),
    (datetime.date(2026, 12, 4), datetime.date(2027, 1, 3), "2026 学年末大假期 (12月)"),
    (datetime.date(2027, 1, 23), datetime.date(2027, 2, 16), "2027 农历新年与跨年假期")
]

# 安全获取 Token（不留明文字符串，防止 GitHub 拦截）
HF_TOKEN = st.secrets.get("HF_TOKEN", "")
# Hugging Face 最新官方 Serverless 路由终端
API_URL = "https://router.huggingface.co/hf-inference/v1/chat/completions"

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

def split_and_explode_dates(raw_agency, raw_dest, raw_code, raw_title, raw_loc, raw_dates_str, raw_price):
    days = extract_tour_days(raw_title)
    try:
        clean_price = int(re.sub(r'[^\d]', '', str(raw_price)))
    except Exception:
        clean_price = 0

    date_tokens = re.findall(r'\b\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?\b', str(raw_dates_str))
    if not date_tokens:
        date_tokens = [str(raw_dates_str).strip()]

    exploded = []
    for d_token in date_tokens:
        status, over_days, hol_name = evaluate_holiday_fit(d_token, days)
        exploded.append({
            "agency": raw_agency,
            "destination": raw_dest,
            "tour_code": raw_code,
            "title": raw_title,
            "departure_location": raw_loc,
            "departure_dates": d_token,
            "price_numeric": clean_price,
            "price_text": f"RM {clean_price}",
            "holiday_status": status,
            "over_days": over_days,
            "holiday_name": hol_name
        })
    return exploded

def call_huggingface_vision(image_bytes):
    if not HF_TOKEN:
        raise ValueError("未检测到 HF_TOKEN，请在 Streamlit 后台 Secrets 中配置 HF_TOKEN")

    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {
        "Authorization": f"Bearer {HF_TOKEN}",
        "Content-Type": "application/json"
    }

    prompt = """
    你是一个专业旅游海报解析引擎。请分析此海报并提取所有旅游行程选项。
    遇到一个行程下有多个出发日期（例如 '14/10, 18/10'），请在 departure_dates 字段中将它们全部保留并用逗号隔开。
    只返回合法纯 JSON 格式列表，不要包含任何 markdown 标记、解释或代码块外皮：
    [
      {
        "agency": "旅行社名称",
        "destination": "目的地",
        "tour_code": "团号代码",
        "title": "路线标题",
        "departure_location": "起飞地点(如 SIN/KUL/JB)",
        "departure_dates": "全部出发日期(如 26/10, 28/10)",
        "price": 2999
      }
    ]
    """

    payload = {
        "model": "Qwen/Qwen2.5-VL-7B-Instruct",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                    }
                ]
            }
        ],
        "max_tokens": 4096,
        "temperature": 0.1
    }

    last_err = ""
    for attempt in range(3):
        try:
            res = requests.post(API_URL, headers=headers, json=payload, timeout=60)
            if res.status_code == 200:
                content = res.json()["choices"][0]["message"]["content"]
                clean_json = re.search(r'\[.*\]', content, re.DOTALL)
                if clean_json:
                    return json.loads(clean_json.group(0))
                return json.loads(content)
            elif res.status_code == 503:
                time.sleep(8)
            else:
                last_err = f"HTTP {res.status_code}: {res.text}"
                time.sleep(2)
        except Exception as ex:
            last_err = str(ex)
            time.sleep(2)

    raise RuntimeError(f"API 请求失败: {last_err}")

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
    cols = [("旅行社", 25), ("目的地", 160), ("团号", 240), ("出发日期", 330), ("价格", 440), ("行程名称", 540)]
    for name, x in cols:
        draw.text((x, y + 7), name, fill=(30, 41, 59), font=font)

    y += 35
    for _, r in df.iterrows():
        draw.text((25, y), str(r['agency'])[:10], fill=(71, 85, 105), font=font)
        draw.text((160, y), str(r['destination'])[:6], fill=(15, 23, 42), font=font)
        draw.text((240, y), str(r['tour_code'])[:10], fill=(71, 85, 105), font=font)
        draw.text((330, y), str(r['departure_dates'])[:12], fill=(30, 41, 59), font=font)
        draw.text((440, y), str(r['price_text']), fill=(220, 38, 38), font=font)
        draw.text((540, y), str(r['title'])[:22], fill=(71, 85, 105), font=font)
        y += rh

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

if "tour_data" not in st.session_state:
    st.session_state.tour_data = []

c_up, c_rst = st.columns([4, 1])
with c_up:
    uploaded_files = st.file_uploader("📷 上传海报图片 (支持任意新海报，可多选)", type=["jpg", "jpeg", "png"], accept_multiple_files=True)
with c_rst:
    st.write("")
    st.write("")
    if st.button("🗑️ 清空重置", use_container_width=True):
        st.session_state.tour_data = []
        st.rerun()

if uploaded_files:
    st.success(f"已选择 {len(uploaded_files)} 张海报图片")
    if st.button("🚀 启动视觉 AI 智能解析比价", type="primary"):
        all_exploded = []
        progress_bar = st.progress(0.0)
        status_text = st.empty()
        has_error = False

        for idx, f in enumerate(uploaded_files):
            status_text.text(f"🔍 正在由 Qwen2.5-VL 解析海报: {f.name} ...")
            try:
                raw_items = call_huggingface_vision(f.getvalue())
                for item in raw_items:
                    rows = split_and_explode_dates(
                        item.get("agency", "精选旅行社"),
                        item.get("destination", "精选路线"),
                        item.get("tour_code", "-"),
                        item.get("title", ""),
                        item.get("departure_location", "SIN/KUL出发"),
                        item.get("departure_dates", ""),
                        item.get("price", 0)
                    )
                    all_exploded.extend(rows)
            except Exception as e:
                has_error = True
                st.error(f"处理 {f.name} 时发生错误: {e}")

            progress_bar.progress((idx + 1) / len(uploaded_files))

        if not has_error and all_exploded:
            unique_dict = {(x["agency"], x["tour_code"], x["departure_dates"]): x for x in all_exploded}
            st.session_state.tour_data = list(unique_dict.values())
            status_text.text("✅ 解析完成！")
            st.rerun()
        elif not has_error and not all_exploded:
            status_text.text("⚠️ 未能从海报提取到有效团期数据。")

if st.session_state.tour_data:
    st.markdown("---")
    df = pd.DataFrame(st.session_state.tour_data)
    df['price_numeric'] = pd.to_numeric(df['price_numeric'], errors='coerce').fillna(0).astype(int)

    # 快捷校对编辑面板
    with st.expander("🛠️ 快速数据校对面板 (双击可修改文字/价格，可自主增删行)", expanded=False):
        edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)
        if not edited_df.equals(df):
            st.session_state.tour_data = edited_df.to_dict('records')
            st.rerun()

    # 侧边栏筛选器
    st.sidebar.header("🎛️ 筛选条件")
    selected_agency = st.sidebar.selectbox("选择旅行社", ["全部"] + sorted([a for a in df['agency'].unique() if a]))
    selected_dest = st.sidebar.selectbox("选择目的地", ["全部"] + sorted([d for d in df['destination'].unique() if d]))

    raw_locs = sorted([l for l in df['departure_location'].unique() if l])
    loc_options = ["全部", "🇲🇾 全马/新出发 (KUL/JB/SIN)"] + raw_locs
    selected_loc = st.sidebar.selectbox("选择起飞地点", loc_options)

    selected_hol = st.sidebar.selectbox("🗓️ 学校假期筛选", ["全部日期", "🎒 包含学校假期 (含超出2天内)", "✨ 严格在学校假期内 (0超出)", "💼 仅平时非假期"])

    filtered_df = df.copy()
    if selected_agency != "全部":
        filtered_df = filtered_df[filtered_df['agency'] == selected_agency]
    if selected_dest != "全部":
        filtered_df = filtered_df[filtered_df['destination'] == selected_dest]

    if selected_loc == "🇲🇾 全马/新出发 (KUL/JB/SIN)":
        kw = ["KUL", "吉隆坡", "JB", "新山", "SIN", "新加坡"]
        filtered_df = filtered_df[filtered_df['departure_location'].apply(lambda l: any(k in str(l) for k in kw))]
    elif selected_loc != "全部":
        filtered_df = filtered_df[filtered_df['departure_location'] == selected_loc]

    if selected_hol == "🎒 包含学校假期 (含超出2天内)":
        filtered_df = filtered_df[filtered_df['holiday_status'].isin(['exact', 'slight_over'])]
    elif selected_hol == "✨ 严格在学校假期内 (0超出)":
        filtered_df = filtered_df[filtered_df['holiday_status'] == 'exact']
    elif selected_hol == "💼 仅平时非假期":
        filtered_df = filtered_df[filtered_df['holiday_status'] == 'none']

    p_min = int(df['price_numeric'].min()) if not df.empty else 1000
    p_max = int(df['price_numeric'].max()) if not df.empty else 9000
    price_range = st.sidebar.slider("💰 团费预算范围 (RM)", min_value=p_min, max_value=p_max, value=(p_min, p_max), step=100)
    filtered_df = filtered_df[(filtered_df['price_numeric'] >= price_range[0]) & (filtered_df['price_numeric'] <= price_range[1])]

    st.markdown("### 📥 导出选项")
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("📊 下载 CSV 比价清单", data=filtered_df.to_csv(index=False).encode('utf-8-sig'), file_name="视觉解析比价清单.csv", mime="text/csv", use_container_width=True)
    with col2:
        st.download_button("🖼️ 下载精美长图 (.png)", data=generate_comparison_image(filtered_df), file_name="视觉解析比价长图.png", mime="image/png", use_container_width=True)

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
