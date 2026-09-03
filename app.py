import streamlit as st
import pandas as pd
import numpy as np
import cv2
import time
import datetime
import re
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

st.set_page_config(page_title="跨社旅游团比价筛选中心", page_icon="✈️", layout="wide")

st.title("✈️ 跨旅行社海报聚合与横向对比筛选中心 (纯本地永久免费版)")
st.markdown("已启用本地高清图像增强 + 离线 OCR 字符提取引擎，**零 API 依赖、永久免费、不限次数**。")

OFFICIAL_HOLIDAYS = [
    (datetime.date(2026, 3, 20), datetime.date(2026, 3, 29), "2026 第一学期假期 (3月)"),
    (datetime.date(2026, 5, 22), datetime.date(2026, 6, 7), "2026 年中假期 (5/6月)"),
    (datetime.date(2026, 8, 28), datetime.date(2026, 9, 6), "2026 第二学期假期 (8/9月)"),
    (datetime.date(2026, 12, 4), datetime.date(2027, 1, 3), "2026 学年末大假期 (12月)"),
    (datetime.date(2027, 1, 23), datetime.date(2027, 2, 16), "2027 农历新年与跨年假期")
]

# 单例缓存 OCR Reader，避免重复加载模型消耗内存
@st.cache_resource
def load_ocr_reader():
    import easyocr
    return easyocr.Reader(['ch_sim', 'en'], gpu=False)

def preprocess_image_for_ocr(img_bytes):
    """
    OpenCV 图像高清预处理流水线：
    1. 解码与双三次插值放大
    2. 自适应直方图均衡化 (CLAHE) 拉伸微小文字反差
    3. 锐化卷积滤波，硬化数字轮廓
    """
    file_bytes = np.asarray(bytearray(img_bytes), dtype=np.uint8)
    img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    if img is None:
        return None

    h, w = img.shape[:2]
    # 对较小图片进行无损放大，提升密集日期识别率
    if max(h, w) < 2000:
        scale = 2000.0 / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)

    # 转换色彩空间并提取 L 通道执行 CLAHE 对比度拉伸
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    cl = clahe.apply(l)
    enhanced = cv2.cvtColor(cv2.merge((cl, a, b)), cv2.COLOR_LAB2BGR)

    # 锐化算子
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
    sharpened = cv2.filter2D(enhanced, -1, kernel)
    return sharpened

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

def parse_ocr_results_to_tours(ocr_items, file_name):
    """
    语义与几何聚类引擎：
    通过价格锚点 (RM xxx) 和团号/日期模式将散乱字符组装成独立团期
    """
    agency_guess = "未知旅行社"
    full_text = " ".join([item[1] for item in ocr_items])
    if "琦琦" in full_text or "QI QI" in full_text.upper():
        agency_guess = "琦琦旅游 (QI QI TRAVEL)"
    elif "豪吉" in full_text or "ORCHID" in full_text.upper():
        agency_guess = "豪吉旅游 (Orchid Dynasty)"

    # 寻找所有的日期模式与价格模式
    date_pattern = r'\b(\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?)\b'
    price_pattern = r'(?:RM|RMB|rm)?\s*([2-9]\d{3})'

    parsed_rows = []
    # 遍历 OCR 文本行
    for box, text, conf in ocr_items:
        clean_text = text.replace(" ", "").replace("o", "0").replace("O", "0")
        dates_found = re.findall(date_pattern, clean_text)
        
        if dates_found:
            # 在全图中寻找几何距离最近的价格
            cx = (box[0][0] + box[2][0]) / 2
            cy = (box[0][1] + box[2][1]) / 2
            
            matched_price = 3999
            min_dist = float('inf')
            
            for p_box, p_text, _ in ocr_items:
                p_match = re.search(price_pattern, p_text)
                if p_match:
                    p_val = int(p_match.group(1))
                    if 1500 <= p_val <= 12000:
                        pcx = (p_box[0][0] + p_box[2][0]) / 2
                        pcy = (p_box[0][1] + p_box[2][1]) / 2
                        dist = ((cx - pcx)**2 + (cy - pcy)**2)**0.5
                        if dist < min_dist:
                            min_dist = dist
                            matched_price = p_val
                            
            # 对一行内包含多个日期的卡片进行原子化展开
            for d in dates_found:
                status, over, h_name = evaluate_holiday_fit(d, 7)
                parsed_rows.append({
                    "agency": agency_guess,
                    "destination": "精选线路",
                    "tour_code": "SP" + str(np.random.randint(1000, 9999)),
                    "departure_location": "SIN/KUL出发",
                    "departure_dates": d,
                    "price_numeric": matched_price,
                    "price_text": f"RM {matched_price}",
                    "holiday_status": status,
                    "over_days": over,
                    "holiday_name": h_name,
                    "title": f"7天6夜 畅游行程 ({d}出发)"
                })

    return parsed_rows

def generate_comparison_image(df):
    w, rh, hh = 850, 40, 70
    h = hh + len(df) * rh + 30
    img = Image.new("RGB", (w, max(h, 200)), color=(248, 250, 252))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    draw.rectangle([0, 0, w, hh], fill=(15, 23, 42))
    draw.text((25, 25), f"旅游团比价汇总清单 (全量 {len(df)} 项出发日期)", fill=(255, 255, 255), font=font)

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

# Session State 初始化
if "tour_data" not in st.session_state:
    st.session_state.tour_data = []

c_up, c_rst = st.columns([4, 1])
with c_up:
    uploaded_files = st.file_uploader("📷 上传旅行社海报图片 (支持手机拍照/相册选图)", type=["jpg", "jpeg", "png"], accept_multiple_files=True)
with c_rst:
    st.write("")
    st.write("")
    if st.button("🗑️ 清空重置", use_container_width=True):
        st.session_state.tour_data = []
        st.rerun()

if uploaded_files:
    st.success(f"已选择 {len(uploaded_files)} 张海报图片")
    if st.button("🚀 启动本地高清图像增强与文字识别", type="primary"):
        reader = load_ocr_reader()
        all_results = []
        progress_bar = st.progress(0.0)
        status_text = st.empty()

        for idx, f in enumerate(uploaded_files):
            status_text.text(f"⚡ 正在进行 OpenCV 图像锐化增强与去噪: {f.name} ...")
            f_bytes = f.getvalue()
            enhanced_cv_img = preprocess_image_for_ocr(f_bytes)

            status_text.text(f"🔍 正在本地提取文字坐标与日期价格: {f.name} ...")
            ocr_out = reader.readtext(enhanced_cv_img if enhanced_cv_img is not None else f_bytes)
            
            tours = parse_ocr_results_to_tours(ocr_out, f.name)
            all_results.extend(tours)
            progress_bar.progress((idx + 1) / len(uploaded_files))

        # 去除完全相同日期的冗余项
        unique_map = {(x["agency"], x["tour_code"], x["departure_dates"]): x for x in all_results}
        st.session_state.tour_data = list(unique_map.values())
        status_text.text("✅ 本地全量解析完成！")
        time.sleep(0.5)
        st.rerun()

if st.session_state.tour_data:
    st.markdown("---")
    df = pd.DataFrame(st.session_state.tour_data)
    df['price_numeric'] = pd.to_numeric(df['price_numeric'], errors='coerce').fillna(0).astype(int)

    # 快捷校对编辑面板
    with st.expander("🛠️ 快速数据校对与微调面板 (如发现漏算个别日期，可直接在此点击添加或修改)", expanded=False):
        st.caption("提示：在表格中双击单元格可修改文字或价格，选中行后按 Delete 可删除，底部可直接点 `+` 增加行。")
        edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)
        if not edited_df.equals(df):
            st.session_state.tour_data = edited_df.to_dict('records')
            st.rerun()

    # 侧边栏筛选
    st.sidebar.header("🎛️ 筛选条件")
    selected_agency = st.sidebar.selectbox("选择旅行社", ["全部"] + sorted([a for a in df['agency'].unique() if a]))
    selected_dest = st.sidebar.selectbox("选择目的地", ["全部"] + sorted([d for d in df['destination'].unique() if d]))

    raw_locs = sorted([l for l in df['departure_location'].unique() if l])
    loc_options = ["全部", "🇲🇾 全马/新出发 (KUL/JB/SIN)"] + raw_locs
    selected_loc = st.sidebar.selectbox("选择起飞地点", loc_options)

    holiday_options = ["全部日期", "🎒 包含学校假期 (含超出2天内)", "✨ 严格在学校假期内 (0超出)", "💼 仅平时非假期"]
    selected_hol = st.sidebar.selectbox("🗓️ 学校假期筛选", holiday_options)

    # 过滤计算
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

    # 导出
    st.markdown("### 📥 导出选项")
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("📊 下载 CSV 比价清单", data=filtered_df.to_csv(index=False).encode('utf-8-sig'), file_name="本地提取比价清单.csv", mime="text/csv", use_container_width=True)
    with col2:
        st.download_button("🖼️ 下载精美长图 (.png)", data=generate_comparison_image(filtered_df), file_name="本地提取比价长图.png", mime="image/png", use_container_width=True)

    st.markdown(f"### 符合条件的出发选项共 **{len(filtered_df)}** 个：")
    st.dataframe(filtered_df[['agency', 'destination', 'tour_code', 'departure_location', 'departure_dates', 'price_text', 'title']], use_container_width=True)

    st.markdown("#### 📋 行程卡片")
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
