import streamlit as st
import pandas as pd
import json
import requests
import base64

st.set_page_config(page_title="AI 旅游团智能筛选助手", page_icon="✈️", layout="wide")

st.title("✈️ 旅游团宣传单智能分析与筛选")
st.markdown("批量上传旅游宣传图片，AI 自动提取价格、起飞地点并支持多条件筛选！")

# 已为你配置好 Groq API Key
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
                        分析这几张旅游宣传单图片。请提取所有图片中出现的所有旅游团信息，并【必须】把它们合并成一个合法的 JSON 列表返回，不要包含任何 markdown 标记之外的多余文字，格式如下：
                        [
                          {
                            "destination": "目的地，例如：海南岛、哈尔滨、上海、大连、广州澳门、重庆、张家界、北疆、南疆",
                            "tour_code": "团号，例如：SP002301",
                            "title": "路线标题或详细描述",
                            "departure_location": "起飞地点，例如：吉隆坡出发、柔佛起飞等",
                            "departure_dates": "出发日期字符串",
                            "price_numeric": 1599,
                            "price_text": "RM 1599 起"
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
                    "model": "llama-3.2-11b-vision-preview",
                    "messages": [
                        {
                            "role": "user",
                            "content": messages_content
                        }
                    ],
                    "temperature": 0.1
                }

                response = requests.post(url, headers=headers, data=json.dumps(payload))
                
                if response.status_code != 200:
                    raise Exception(f"API 请求失败: {response.text}")
                
                res_json = response.json()
                response_text = res_json['choices'][0]['message']['content'].strip()
                
                if response_text.startswith("```json"):
                    response_text = response_text[7:-3].strip()
                elif response_text.startswith("```"):
                    response_text = response_text[3:-3].strip()
                    
                st.session_state.travel_data = json.loads(response_text)
                st.success("🎉 批量分析完成！")
                
            except Exception as e:
                st.error(f"解析过程中出现错误: {e}")

if st.session_state.travel_data:
    st.markdown("---")
    st.header("🔍 旅游团智能筛选面板")
    
    df = pd.DataFrame(st.session_state.travel_data)
    
    st.sidebar.header("🎛️ 筛选条件")
    all_destinations = ["全部"] + list(df['destination'].unique())
    selected_dest = st.sidebar.selectbox("选择目的地", all_destinations)
    
    all_dept_locations = ["全部"] + list(df['departure_location'].unique())
    selected_loc = st.sidebar.selectbox("选择起飞地点", all_dept_locations)
    
    min_price = int(df['price_numeric'].min()) if not df.empty else 0
    max_price = int(df['price_numeric'].max()) if not df.empty else 10000
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
