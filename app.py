import streamlit as st
import pandas as pd
import json
import requests
import base64
import time
import re
from io import BytesIO
from PIL import Image

st.set_page_config(page_title="AI 旅游团智能筛选助手", page_icon="✈️", layout="wide")

st.title("✈️ 旅游团宣传单智能分析与筛选")
st.markdown("批量上传旅游宣传图片，AI 自动提取价格、起飞地点并支持多条件筛选！")

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
    prompt = """
    请提取这张宣传单中的所有旅游团项目，以合法的 JSON 数组格式输出，不要包含任何多余文字。
    每个对象包含以下字段：
    [
      {
        "destination": "目的地城市或省份",
        "tour_code": "团号",
        "title": "行程路线标题",
        "departure_location": "起飞地点(如新加坡/吉隆坡/柔佛/待定)",
        "departure_dates": "出发日期",
        "price_numeric": 2999,
        "price_text": "RM 2999 起"
      }
    ]
    """
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "qwen/qwen3.6-27b",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded_string}"}}
                ]
            }
        ],
        "temperature": 0.1,
        "max_tokens": 4096
    }
    
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    if response.status_code != 200:
        return []
    
    content = response.json()['choices'][0]['message']['content'].strip()
    
    # 清洗掉思考过程
    if "</think>" in content:
        content = content.split("</think>")[-1].strip()
    content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
    
    # 正则提取 JSON
    match = re.search(r'\[\s*\{.*?\}\s*\]', content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
            
    # 兜底行提取
    fallback = []
    lines = content.split("\n")
    cur_dest = "热门"
    for line in lines:
        if any(tag in line for tag in ["SIN-", "KL-", "JB-", "目的地"]):
            cur_dest = re.sub(r'[#*]', '', line).strip()
        code_match = re.search(r'(SP\d+)', line)
        if code_match:
            price_match = re.search(r'RM\s*(\d+)', line)
            p_val = int(price_match.group(1)) if price_match else 1999
            fallback.append({
                "destination": cur_dest,
                "tour_code": code_match.group(1),
                "title": line.strip("- *0123456789. "),
                "departure_location": "待定",
                "departure_dates": "见海报",
                "price_numeric": p_val,
                "price_text": f"RM {p_val}"
            })
    return fallback

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
            status_text.text(f"正在分析第 {idx + 1}/{len(uploaded_files)} 张图片: {file.name} ...")
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
            st.success(f"🎉 识别完成！共获取 {len(all_results)} 条旅游团信息。")
        else:
            st.error("未能提取出有效数据，请检查图片清晰度或重新点击分析。")

if st.session_state.travel_data:
    st.markdown("---")
    df = pd.DataFrame(st.session_state.travel_data)
    
    if 'destination' in df.columns:
        df['destination'] = df['destination'].astype(str).str.replace(r'[\*\-#]', '', regex=True).str.strip()
    if 'price_numeric' in df.columns:
        df['price_numeric'] = pd.to_numeric(df['price_numeric'], errors='coerce').fillna(0).astype(int)
        
    st.header("🔍 旅游团智能筛选面板")
    
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
    
    # 导出区域
    st.markdown("### 📥 导出数据")
    csv_bytes = filtered_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📋 下载结果表格 (CSV / Excel 可打开)",
        data=csv_bytes,
        file_name="旅游团筛选清单.csv",
        mime="text/csv",
        type="primary"
    )
    
    st.markdown(f"### 符合条件的旅游团共 **{len(filtered_df)}** 个：")
    
    # 表格展示
    st.dataframe(
        filtered_df[['destination', 'tour_code', 'title', 'departure_location', 'departure_dates', 'price_text']],
        use_container_width=True
    )
    
    # 卡片明细
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
