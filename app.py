import streamlit as st
import pandas as pd
import json
import requests
import base64
import time
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from fpdf import FPDF

st.set_page_config(page_title="AI 旅游团智能筛选助手", page_icon="✈️", layout="wide")

st.title("✈️ 旅游团宣传单智能分析与筛选")
st.markdown("批量上传旅游宣传图片，AI 自动提取价格、起飞地点并支持多条件筛选与导出！")

GROQ_API_KEY = "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"

def compress_image(uploaded_file, max_size=1024, quality=75):
    img = Image.open(uploaded_file)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=quality)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")

def analyze_single_image(file):
    encoded_string = compress_image(file)
    system_prompt = (
        "你是一个专业的数据结构化提取工具。请仔细识别旅游宣传单中的每一个旅游团项目。\n"
        "要求：必须输出纯 JSON 对象，格式为 {\"tours\": [...] }，绝不要输出任何解释或多余字符。\n"
        "每个团必须包含：\n"
        "- destination: 准确的目的地城市或省份（如：重庆、云南、西藏、青岛、韩国、桂林等，不要带多余说明）\n"
        "- tour_code: 团号（如：SP002376）\n"
        "- title: 行程标题或路线描述\n"
        "- departure_location: 实际起飞/出发城市（若有 SIN 代表新加坡，KUL 代表吉隆坡，JHB 代表柔佛，若未说明写'待定'）\n"
        "- departure_dates: 出发日期列表\n"
        "- price_numeric: 纯数字价格（整数，取最低起步价，如 2999）\n"
        "- price_text: 显示价格（如 RM 2999 起）"
    )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "提取图片中的所有旅游团数据："},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded_string}"}}
            ]
        }
    ]
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "qwen/qwen3.6-27b",
        "messages": messages,
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }
    
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    if response.status_code != 200:
        return []
    
    res_json = response.json()
    content = res_json['choices'][0]['message']['content'].strip()
    
    try:
        parsed = json.loads(content)
        if "tours" in parsed and isinstance(parsed["tours"], list):
            return parsed["tours"]
        for key, val in parsed.items():
            if isinstance(val, list):
                return val
    except Exception:
        pass
    return []

def generate_image(dataframe):
    """将筛选结果动态绘制成一张高清清单长图 (PNG)"""
    width = 900
    card_height = 140
    header_height = 120
    footer_height = 50
    total_height = header_height + len(dataframe) * card_height + footer_height

    img = Image.new("RGB", (width, total_height), color=(248, 250, 252))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    # 绘制头部横幅
    draw.rectangle([(0, 0), (width, header_height - 20)], fill=(30, 41, 59))
    draw.text((30, 30), "TRAVEL TOUR SUMMARY LIST", fill=(255, 255, 255), font=font)
    draw.text((30, 60), f"Total Tours: {len(dataframe)}", fill=(148, 163, 184), font=font)

    # 循环绘制每一个旅游团卡片
    y = header_height
    for _, row in dataframe.iterrows():
        # 卡片白色背景与边框
        draw.rectangle([(30, y), (width - 30, y + card_height - 15)], fill=(255, 255, 255), outline=(226, 232, 240), width=2)
        
        dest = str(row.get('destination', 'Unknown'))
        price = str(row.get('price_text', 'N/A'))
        code = str(row.get('tour_code', 'N/A'))
        loc = str(row.get('departure_location', 'N/A'))
        dates = str(row.get('departure_dates', 'N/A'))
        title = str(row.get('title', 'N/A'))

        # 卡片文字排版
        draw.text((50, y + 15), f"[{dest}]  {code}", fill=(15, 23, 42), font=font)
        draw.text((width - 220, y + 15), f"{price}", fill=(225, 29, 72), font=font)
        draw.text((50, y + 45), f"Dept: {loc}  |  Dates: {dates}", fill=(71, 85, 105), font=font)
        draw.text((50, y + 75), f"Route: {title[:70]}", fill=(100, 116, 139), font=font)

        y += card_height

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def generate_pdf(dataframe):
    """生成 PDF 清单"""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    
    pdf.cell(0, 10, "Travel Tour Itinerary List", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 8, f"Total Tours: {len(dataframe)}", ln=True, align="C")
    pdf.ln(5)
    
    for _, row in dataframe.iterrows():
        pdf.set_fill_color(245, 247, 250)
        pdf.rect(10, pdf.get_y(), 190, 26, "F")
        
        pdf.set_font("Helvetica", "B", 12)
        dest = str(row.get('destination', 'Unknown')).encode('latin-1', 'replace').decode('latin-1')
        price = str(row.get('price_text', 'N/A')).encode('latin-1', 'replace').decode('latin-1')
        pdf.cell(120, 8, f"Destination: {dest}", ln=0)
        pdf.cell(70, 8, f"Price: {price}", ln=1, align="R")
        
        pdf.set_font("Helvetica", "", 10)
        code = str(row.get('tour_code', 'N/A')).encode('latin-1', 'replace').decode('latin-1')
        loc = str(row.get('departure_location', 'N/A')).encode('latin-1', 'replace').decode('latin-1')
        dates = str(row.get('departure_dates', 'N/A')).encode('latin-1', 'replace').decode('latin-1')
        
        pdf.cell(100, 6, f"Tour Code: {code}  |  Dept: {loc}", ln=0)
        pdf.cell(90, 6, f"Dates: {dates}", ln=1)
        
        title = str(row.get('title', 'N/A')).encode('latin-1', 'replace').decode('latin-1')
        pdf.cell(0, 6, f"Route: {title[:75]}", ln=1)
        pdf.ln(6)
        
    return bytes(pdf.output())

uploaded_files = st.file_uploader(
    "批量上传宣传图 (支持 JPG/PNG，可多选)", 
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True
)

if "travel_data" not in st.session_state:
    st.session_state.travel_data = None

if uploaded_files:
    st.success(f"已选择 {len(uploaded_files)} 张图片")
    if st.button("🚀 开始让 AI 批量分析图片", type="primary"):
        all_results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for idx, file in enumerate(uploaded_files):
            status_text.text(f"正在精准解析第 {idx + 1}/{len(uploaded_files)} 张图片: {file.name} ...")
            data = analyze_single_image(file)
            if data:
                all_results.extend(data)
            
            progress_bar.progress((idx + 1) / len(uploaded_files))
            if idx + 1 < len(uploaded_files):
                time.sleep(1.5)
                
        status_text.empty()
        progress_bar.empty()
        
        if all_results:
            st.session_state.travel_data = all_results
            st.success(f"🎉 分析完成！共准确提取出 {len(all_results)} 条旅游团信息。")
        else:
            st.error("未能提取出有效数据，请确认图片中包含清晰的旅游项目。")

if st.session_state.travel_data:
    st.markdown("---")
    
    df = pd.DataFrame(st.session_state.travel_data)
    if 'destination' in df.columns:
        df['destination'] = df['destination'].astype(str).str.replace(r'[\*\-#]', '', regex=True).str.strip()
    if 'price_numeric' in df.columns:
        df['price_numeric'] = pd.to_numeric(df['price_numeric'], errors='coerce').fillna(0).astype(int)
        
    st.header("🔍 旅游团智能筛选与导出")
    
    st.sidebar.header("🎛️ 筛选条件")
    dest_list = ["全部"] + sorted([d for d in df['destination'].unique() if d and d != "nan"])
    selected_dest = st.sidebar.selectbox("选择目的地", dest_list)
    
    loc_list = ["全部"] + sorted([l for l in df['departure_location'].unique() if l and l != "nan"])
    selected_loc = st.sidebar.selectbox("选择起飞地点", loc_list)
    
    min_val = int(df['price_numeric'].min()) if not df.empty else 0
    max_val = int(df['price_numeric'].max()) if not df.empty else 10000
    if min_val >= max_val:
        max_val = min_val + 1000
    price_range = st.sidebar.slider("价格预算范围 (RM)", min_val, max_val, (min_val, max_val))
    
    filtered_df = df.copy()
    if selected_dest != "全部":
        filtered_df = filtered_df[filtered_df['destination'] == selected_dest]
    if selected_loc != "全部":
        filtered_df = filtered_df[filtered_df['departure_location'] == selected_loc]
        
    filtered_df = filtered_df[
        (filtered_df['price_numeric'] >= price_range[0]) & 
        (filtered_df['price_numeric'] <= price_range[1])
    ]
    
    # 导出工具栏（提供图片、PDF、CSV 三种格式）
    st.markdown("### 📥 一键导出筛选结果")
    col_img, col_pdf, col_csv = st.columns(3)
    
    with col_img:
        img_bytes = generate_image(filtered_df)
        st.download_button(
            label="🖼️ 导出为长图 (PNG)",
            data=img_bytes,
            file_name="旅游团筛选清单.png",
            mime="image/png",
            type="primary"
        )
        
    with col_pdf:
        pdf_bytes = generate_pdf(filtered_df)
        st.download_button(
            label="📄 导出为 PDF 文件",
            data=pdf_bytes,
            file_name="旅游团筛选清单.pdf",
            mime="application/pdf"
        )
        
    with col_csv:
        csv_bytes = filtered_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📋 导出为表格 (CSV)",
            data=csv_bytes,
            file_name="旅游团筛选清单.csv",
            mime="text/csv"
        )
        
    st.markdown(f"### 符合条件的旅游团共 **{len(filtered_df)}** 个：")
    
    st.dataframe(
        filtered_df[['destination', 'tour_code', 'title', 'departure_location', 'departure_dates', 'price_text']],
        use_container_width=True
    )
    
    for _, row in filtered_df.iterrows():
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 2, 2])
            with c1:
                st.markdown(f"### 📍 **{row.get('destination', '未知')}**")
                st.write(f"**路线：** {row.get('title', '无')}")
                st.write(f"**团号：** `{row.get('tour_code', '无')}`")
            with c2:
                st.write(f"🛫 **起飞点：** {row.get('departure_location', '待定')}")
                st.write(f"📅 **出发日期：** {row.get('departure_dates', '见海报')}")
            with c3:
                st.markdown(f"### 💰 **{row.get('price_text', '无')}**")
