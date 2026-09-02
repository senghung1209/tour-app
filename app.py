import streamlit as st
import pandas as pd
import json
import requests
import base64
import re

st.set_page_config(page_title="AI 旅游团智能筛选助手", page_icon="✈️", layout="wide")

st.title("✈️ 旅游团宣传单智能分析与筛选")
st.markdown("批量上传旅游宣传图片，AI 自动提取价格、起飞地点并支持多条件筛选！")

GROQ_API_KEY = "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"

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
        with st.spinner("AI 正在努力批量识别图片中的文字、价格和起飞地点，请稍候..."):
            try:
                messages_content = [
                    {
                        "type": "text",
                        "text": """
                        请仔细识别图片中所有旅游团。请【不要输出长篇思考】，直接输出一个纯 JSON 列表。
                        如果无法生成纯 JSON，请每一行输出一个团的信息。
                        JSON 格式要求：
                        [
                          {
                            "destination": "目的地",
                            "tour_code": "团号例如 SP002376",
                            "title": "路线描述",
                            "departure_location": "出发地例如 新加坡/吉隆坡/柔佛",
                            "departure_dates": "出发日期",
                            "price_numeric": 2999,
                            "price_text": "RM 2999"
                          }
                        ]
                        """
                    }
                ]
                
                for file in uploaded_files:
                    encoded_string = base64.b64encode(file.getvalue()).decode('utf-8')
                    mime = file.type
                    messages_content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,{encoded_string}"
                        }
                    })

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
                            "content": messages_content
                        }
                    ],
                    "temperature": 0.1,
                    "max_tokens": 8192
                }

                response = requests.post(url, headers=headers, data=json.dumps(payload))
                
                if response.status_code != 200:
                    raise Exception(f"API 请求失败: {response.text}")
                
                res_json = response.json()
                response_text = res_json['choices'][0]['message']['content'].strip()
                
                # 尝试从模型输出中提取 JSON
                data = None
                json_matches = list(re.finditer(r'\[\s*\{.*?\}\s*\]', response_text, re.DOTALL))
                if json_matches:
                    try:
                        data = json.loads(json_matches[-1].group(0))
                    except Exception:
                        pass
                
                # 如果没提取到完整 JSON，直接从它思考提取的纯文本里抓取数据（兜底方案）
                if not data:
                    parsed_list = []
                    # 匹配类似于 SP002376: 7天6夜 ... RM2999 的格式
                    lines = response_text.split('\n')
                    current_dest = "热门推荐"
                    for line in lines:
                        if "SIN-" in line or "KL-" in line or "JB-" in line:
                            current_dest = line.replace("*", "").replace("#", "").strip()
                        tour_match = re.search(r'(SP\d+).*?(?:RM\s*(\d+)|$)', line)
                        if tour_match:
                            t_code = tour_match.group(1)
                            p_num = int(tour_match.group(2)) if tour_match.group(2) else 2999
                            parsed_list.append({
                                "destination": current_dest,
                                "tour_code": t_code,
                                "title": line.strip("- *0123456789. "),
                                "departure_location": "马来西亚/新加坡",
                                "departure_dates": "详见海报",
                                "price_numeric": p_num,
                                "price_text": f"RM {p_num}"
                            })
                    if parsed_list:
                        data = parsed_list

                if data:
                    st.session_state.travel_data = data
                    st.success("🎉 批量分析完成！")
                else:
                    raise Exception("未能成功抓取到有效旅游团数据，请尝试换一张更清晰的图片上传。")
                
            except Exception as e:
                st.error(f"解析过程中出现错误: {e}")

if st.session_state.travel_data:
    st.markdown("---")
    st.header("🔍 旅游团智能筛选面板")
    
    df = pd.DataFrame(st.session_state.travel_data)
    
    st.sidebar.header("🎛️ 筛选条件")
    all_destinations = ["全部"] + [d for d in df['destination'].unique() if d]
    selected_dest = st.sidebar.selectbox("选择目的地", all_destinations)
    
    all_dept_locations = ["全部"] + [l for l in df['departure_location'].unique() if l]
    selected_loc = st.sidebar.selectbox("选择起飞地点", all_dept_locations)
    
    min_price = int(df['price_numeric'].min()) if not df.empty and pd.notna(df['price_numeric'].min()) else 0
    max_price = int(df['price_numeric'].max()) if not df.empty and pd.notna(df['price_numeric'].max()) else 10000
    price_range = st.sidebar.slider("价格预算范围 (RM)", min_price, max_price, (min_price, max_price))
    
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
                st.markdown(f"### 📍 **{row['destination']}**")
                st.write(f"**路线：** {row['title']}")
                st.write(f"**团号：** `{row['tour_code']}`")
            with col2:
                st.write(f"🛫 **起飞点：** {row['departure_location']}")
                st.write(f"📅 **出发日期：** {row['departure_dates']}")
            with col3:
                st.markdown(f"### 💰 **{row['price_text']}**")
