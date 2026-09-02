import streamlit as st
import pandas as pd
import json
import requests
import base64
import re
import time
from io import BytesIO
from PIL import Image

st.set_page_config(page_title="AI 旅游团智能筛选助手", page_icon="✈️", layout="wide")

st.title("✈️ 旅游团宣传单智能分析与筛选")
st.markdown("批量上传旅游宣传图片，AI 自动提取价格、起飞地点并支持多条件筛选！")

GROQ_API_KEY = "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"

def compress_image(uploaded_file, max_size=900, quality=70):
    """等比缩小图片尺寸与体积，确保单图占用极低 Token"""
    img = Image.open(uploaded_file)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=quality)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")

def analyze_single_image(file):
    """单张图片识别，隔离单次 Token 开销"""
    encoded_string = compress_image(file)
    prompt = """
    请识别该旅游宣传单中的所有旅游团。请【绝对不要输出长篇思考】，直接输出一个 JSON 数组。
    格式要求：
    [
      {
        "destination": "目的地",
        "tour_code": "团号例如 SP002376",
        "title": "路线描述",
        "departure_location": "出发地点例如 吉隆坡/新加坡/柔佛",
        "departure_dates": "出发日期",
        "price_numeric": 2999,
        "price_text": "RM 2999"
      }
    ]
    """
    messages_content = [
        {"type": "text", "text": prompt},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{encoded_string}"}
        }
    ]
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "qwen/qwen3.6-27b",
        "messages": [{"role": "user", "content": messages_content}],
        "temperature": 0.1,
        "max_tokens": 2048
    }
    
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    if response.status_code != 200:
        return []
    
    res_json = response.json()
    response_text = res_json['choices'][0]['message']['content'].strip()
    
    # 优先解析 JSON
    json_matches = list(re.finditer(r'\[\s*\{.*?\}\s*\]', response_text, re.DOTALL))
    if json_matches:
        try:
            return json.loads(json_matches[-1].group(0))
        except Exception:
            pass
            
    # 兜底文本行解析
    fallback_list = []
    lines = response_text.split('\n')
    current_dest = "精选推荐"
    for line in lines:
        if any(prefix in line for prefix in ["SIN-", "KL-", "JB-", "目的地"]):
            current_dest = line.replace("*", "").replace("#", "").strip()
        tour_match = re.search(r'(SP\d+).*?(?:RM\s*(\d+)|$)', line)
        if tour_match:
            t_code = tour_match.group(1)
            p_num = int(tour_match.group(2)) if tour_match.group(2) else 1999
            fallback_list.append({
                "destination": current_dest,
                "tour_code": t_code,
                "title": line.strip("- *0123456789. "),
                "departure_location": "马来西亚/新加坡",
                "departure_dates": "详见海报",
                "price_numeric": p_num,
                "price_text": f"RM {p_num}"
            })
    return fallback_list

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
            try:
                data = analyze_single_image(file)
                if data:
                    all_results.extend(data)
            except Exception as err:
                st.warning(f"图片 {file.name} 解析跳过: {err}")
            
            progress_bar.progress((idx + 1) / len(uploaded_files))
            # 多张处理时每张间隔 1.5 秒，避免触碰 Groq 速率限制
            if idx + 1 < len(uploaded_files):
                time.sleep(1.5)
                
        status_text.empty()
        progress_bar.empty()
        
        if all_results:
            st.session_state.travel_data = all_results
            st.success(f"🎉 批量分析完成！共识别出 {len(all_results)} 个旅游团信息。")
        else:
            st.error("未能从上传的图片中解析出有效信息，请检查图片清晰度。")

if st.session_state.travel_data:
    st.markdown("---")
    st.header("🔍 旅游团智能筛选面板")
    
    df = pd.DataFrame(st.session_state.travel_data)
    
    st.sidebar.header("🎛️ 筛选条件")
    all_destinations = ["全部"] + [str(d) for d in df['destination'].unique() if pd.notna(d)]
    selected_dest = st.sidebar.selectbox("选择目的地", all_destinations)
    
    all_dept_locations = ["全部"] + [str(l) for l in df['departure_location'].unique() if pd.notna(l)]
    selected_loc = st.sidebar.selectbox("选择起飞地点", all_dept_locations)
    
    min_val = int(df['price_numeric'].min()) if not df.empty and pd.notna(df['price_numeric'].min()) else 0
    max_val = int(df['price_numeric'].max()) if not df.empty and pd.notna(df['price_numeric'].max()) else 10000
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
    
    st.markdown(f"### 找到符合条件的旅游团共 **{len(filtered_df)}** 个：")
    
    for index, row in filtered_df.iterrows():
        with st.container(border=True):
            col1, col2, col3 = st.columns([3, 2, 2])
            with col1:
                st.markdown(f"### 📍 **{row.get('destination', '未知')}**")
                st.write(f"**路线：** {row.get('title', '无')}")
                st.write(f"**团号：** `{row.get('tour_code', '无')}`")
            with col2:
                st.write(f"🛫 **起飞点：** {row.get('departure_location', '无')}")
                st.write(f"📅 **出发日期：** {row.get('departure_dates', '无')}")
            with col3:
                st.markdown(f"### 💰 **{row.get('price_text', '无')}**")
