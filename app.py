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
st.markdown("批量上传宣传单，极速提取目的地、起飞地点（吉隆坡/槟城/JB/SIN）、团号与价格！")

GROQ_API_KEY = "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"

def compress_image(uploaded_file, max_size=520, quality=50):
    """极限压缩尺寸，单图 Token 降至 1500 左右，彻底摆脱 8000 TPM 限流等待"""
    img = Image.open(uploaded_file)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.thumbnail((max_size, max_size), Image.Resampling.BILINEAR)
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=quality)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")

def analyze_single_image(file, status_placeholder):
    encoded_string = compress_image(file)
    
    # 采用紧凑缩写 key，极大减少输出 Token 数量，提升 3 倍以上生成速度
    prompt = """
    从海报中提取所有旅游团，直接输出紧凑 JSON 数组，严禁任何解释：
    [
      {
        "d": "目的地(如武汉/青岛/内蒙古/海南/云南)",
        "l": "起飞地(如吉隆坡出发/槟城出发/新山出发/新加坡出发)",
        "c": "SP团号(如SP002740)",
        "t": "行程标题",
        "dt": "出发日期",
        "p": 3199
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
        "temperature": 0.0,
        "max_tokens": 1800,
        "reasoning_effort": "none"
    }
    
    for attempt in range(2):
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        
        if response.status_code == 200:
            content = response.json()['choices'][0]['message']['content'].strip()
            json_match = re.search(r'\[\s*\{.*\}\s*\]', content, re.DOTALL)
            raw_items = []
            if json_match:
                try:
                    raw_items = json.loads(json_match.group(0))
                except Exception:
                    pass
            if not raw_items:
                for b in re.findall(r'\{[^{}]*\}', content):
                    try:
                        it = json.loads(b)
                        if "c" in it or "tour_code" in it:
                            raw_items.append(it)
                    except Exception:
                        continue
            
            # 字段映射还原为标准格式
            standard_items = []
            for item in raw_items:
                dest = item.get("d") or item.get("destination") or "未知目的地"
                loc = item.get("l") or item.get("departure_location") or "详见海报"
                code = item.get("c") or item.get("tour_code") or "SP000000"
                title = item.get("t") or item.get("title") or f"{dest}精选游"
                dates = item.get("dt") or item.get("departure_dates") or "详见海报"
                price = item.get("p") or item.get("price_numeric") or 0
                try:
                    price = int(price)
                except Exception:
                    price = 0
                    
                standard_items.append({
                    "destination": str(dest).strip(),
                    "departure_location": str(loc).strip(),
                    "tour_code": str(code).strip(),
                    "title": str(title).strip(),
                    "departure_dates": str(dates).strip(),
                    "price_numeric": price,
                    "price_text": f"RM {price}" if price > 0 else "详见海报"
                })
            return standard_items
            
        elif response.status_code == 429:
            wait_seconds = 15
            match = re.search(r'try again in ([\d\.]+)s', response.text)
            if match:
                wait_seconds = int(float(match.group(1))) + 1
            for remaining in range(wait_seconds, 0, -1):
                status_placeholder.warning(f"⏳ 额度协调中，稍候 {remaining} 秒自动处理 {file.name} ...")
                time.sleep(1)
            continue
        else:
            raise Exception(f"API 异常 ({response.status_code}): {response.text}")
            
    return []

def create_html_report(df):
    cards_html = ""
    for _, row in df.iterrows():
        cards_html += f"""
        <div class="card">
            <div class="card-header">
                <span class="dest">📍 {row.get('destination', '未知')}</span>
                <span class="price">{row.get('price_text', 'N/A')}</span>
            </div>
            <div class="card-body">
                <div class="meta-row">
                    <span><strong>团号：</strong> {row.get('tour_code', '无')}</span>
                    <span><strong>出发地：</strong> <span class="badge">{row.get('departure_location', '详见海报')}</span></span>
                </div>
                <div class="dates"><strong>📅 出发日期：</strong> {row.get('departure_dates', '见海报')}</div>
                <div class="route"><strong>路线：</strong> {row.get('title', '无')}</div>
            </div>
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>旅游团筛选清单</title>
        <script src="https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js"></script>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
                background-color: #f1f5f9;
                margin: 0;
                padding: 16px;
                color: #0f172a;
            }}
            .toolbar {{
                max-width: 650px;
                margin: 0 auto 16px auto;
                display: flex;
                gap: 10px;
            }}
            .btn {{
                flex: 1;
                padding: 12px;
                border: none;
                border-radius: 8px;
                font-size: 15px;
                font-weight: 600;
                cursor: pointer;
                text-align: center;
            }}
            .btn-img {{ background-color: #e11d48; color: #fff; }}
            .btn-pdf {{ background-color: #0284c7; color: #fff; }}
            #capture-area {{
                max-width: 650px;
                margin: 0 auto;
                background-color: #ffffff;
                padding: 24px;
                border-radius: 12px;
                box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
            }}
            .main-title {{
                text-align: center;
                font-size: 22px;
                font-weight: bold;
                margin: 0 0 6px 0;
            }}
            .sub-title {{
                text-align: center;
                color: #64748b;
                font-size: 13px;
                margin: 0 0 20px 0;
            }}
            .card {{
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                padding: 14px;
                margin-bottom: 12px;
                background: #f8fafc;
                page-break-inside: avoid;
            }}
            .card-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-bottom: 1px solid #e2e8f0;
                padding-bottom: 8px;
                margin-bottom: 8px;
            }}
            .dest {{ font-size: 17px; font-weight: bold; color: #1e293b; }}
            .price {{ font-size: 18px; font-weight: bold; color: #e11d48; }}
            .card-body {{ font-size: 13.5px; line-height: 1.6; }}
            .meta-row {{ display: flex; justify-content: space-between; margin-bottom: 4px; }}
            .badge {{ color: #0284c7; font-weight: 600; }}
            .dates {{ color: #334155; margin-bottom: 4px; }}
            .route {{ color: #475569; }}
            @media print {{
                .toolbar {{ display: none; }}
                body {{ background: #fff; padding: 0; }}
                #capture-area {{ box-shadow: none; padding: 0; }}
            }}
        </style>
    </head>
    <body>
        <div class="toolbar">
            <button class="btn btn-img" onclick="saveAsImage()">🖼️ 保存为手机长图</button>
            <button class="btn btn-pdf" onclick="window.print()">📄 另存为 PDF 文件</button>
        </div>
        <div id="capture-area">
            <div class="main-title">✈️ 旅游团筛选清单</div>
            <div class="sub-title">共筛选出 {len(df)} 个精选行程</div>
            {cards_html}
        </div>
        <script>
            function saveAsImage() {{
                const target = document.getElementById('capture-area');
                html2canvas(target, {{ scale: 2, useCORS: true }}).then(canvas => {{
                    const link = document.createElement('a');
                    link.download = '旅游团清单长图.png';
                    link.href = canvas.toDataURL('image/png');
                    link.click();
                }});
            }}
        </script>
    </body>
    </html>
    """

uploaded_files = st.file_uploader(
    "批量上传宣传图 (支持 JPG/PNG，可多选)", 
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True
)

if "travel_data" not in st.session_state:
    st.session_state.travel_data = None

if uploaded_files:
    st.success(f"已选择 {len(uploaded_files)} 张图片")
    if st.button("🚀 开始极速分析图片", type="primary"):
        all_results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        start_time = time.time()
        for idx, file in enumerate(uploaded_files):
            status_text.info(f"⚡ 正在极速分析第 {idx + 1}/{len(uploaded_files)} 张: {file.name} ...")
            data = analyze_single_image(file, status_text)
            if data:
                all_results.extend(data)
            progress_bar.progress((idx + 1) / len(uploaded_files))
            if idx + 1 < len(uploaded_files):
                time.sleep(0.5)
                
        status_text.empty()
        progress_bar.empty()
        cost_time = round(time.time() - start_time, 1)
        
        if all_results:
            st.session_state.travel_data = all_results
            st.success(f"🎉 分析完成！耗时仅 {cost_time} 秒，共提取出 {len(all_results)} 条旅游团信息！")
        else:
            st.error("未能提取出有效旅游团数据，请重试。")

if st.session_state.travel_data:
    st.markdown("---")
    df = pd.DataFrame(st.session_state.travel_data)
    
    st.header("🔍 旅游团智能筛选面板")
    
    st.sidebar.header("🎛️ 筛选条件")
    dest_list = ["全部"] + sorted([d for d in df['destination'].unique() if d and d != "nan"])
    selected_dest = st.sidebar.selectbox("选择目的地", dest_list)
    
    raw_locs = sorted([l for l in df['departure_location'].unique() if l and l != "nan"])
    loc_list = ["全部", "🇲🇾 全马来西亚出发 (包含吉隆坡/新山/槟城)"] + raw_locs
    selected_loc = st.sidebar.selectbox("选择起飞地点", loc_list)
    
    min_val = int(df['price_numeric'].min()) if not df.empty else 0
    max_val = int(df['price_numeric'].max()) if not df.empty else 10000
    if min_val >= max_val:
        max_val = min_val + 1000
    price_range = st.sidebar.slider("价格预算范围 (RM)", min_val, max_val, (min_val, max_val))
    
    filtered_df = df.copy()
    if selected_dest != "全部":
        filtered_df = filtered_df[filtered_df['destination'] == selected_dest]
        
    if selected_loc == "🇲🇾 全马来西亚出发 (包含吉隆坡/新山/槟城)":
        malaysia_keywords = ["吉隆坡", "新山", "JB", "槟城", "柔佛", "KUL", "PEN", "JHB", "马来西亚"]
        filtered_df = filtered_df[filtered_df['departure_location'].apply(
            lambda loc: any(kw in str(loc) for kw in malaysia_keywords)
        )]
    elif selected_loc != "全部":
        filtered_df = filtered_df[filtered_df['departure_location'] == selected_loc]
        
    filtered_df = filtered_df[
        (filtered_df['price_numeric'] >= price_range[0]) & 
        (filtered_df['price_numeric'] <= price_range[1])
    ]
    
    st.markdown("### 📥 导出筛选结果")
    col1, col2 = st.columns(2)
    
    with col1:
        html_report = create_html_report(filtered_df)
        st.download_button(
            label="📄 下载长图 / PDF 报告文件 (HTML)",
            data=html_report,
            file_name="旅游团筛选清单.html",
            mime="text/html",
            type="primary"
        )
        
    with col2:
        csv_bytes = filtered_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📊 下载 Excel / CSV 表格",
            data=csv_bytes,
            file_name="旅游团清单.csv",
            mime="text/csv"
        )
        
    st.markdown(f"### 符合条件的旅游团共 **{len(filtered_df)}** 个：")
    
    display_cols = [c for c in ['destination', 'tour_code', 'departure_location', 'departure_dates', 'price_text', 'title'] if c in filtered_df.columns]
    st.dataframe(filtered_df[display_cols], use_container_width=True)
    
    for _, row in filtered_df.iterrows():
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 2, 2])
            with c1:
                st.markdown(f"### 📍 **{row.get('destination', '未知')}**")
                st.write(f"**路线：** {row.get('title', '无')}")
                st.write(f"**团号：** `{row.get('tour_code', '无')}`")
            with c2:
                st.markdown(f"🛫 **出发地：** `{row.get('departure_location', '详见海报')}`")
                st.write(f"📅 **出发日期：** {row.get('departure_dates', '见海报')}")
            with c3:
                st.markdown(f"### 💰 **{row.get('price_text', '无')}**")
