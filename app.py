import streamlit as st
import pandas as pd
import json
import requests
import base64
import time
import re
from io import BytesIO
from PIL import Image
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

st.set_page_config(page_title="AI 旅游团智能筛选助手", page_icon="✈️", layout="wide")

st.title("✈️ 旅游团宣传单智能分析与筛选")
st.markdown("批量上传宣传单，精准提取目的地、起飞地点（吉隆坡/槟城/JB/SIN）、团号与价格！")

GROQ_API_KEY = "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"

def compress_image(uploaded_file, max_size=900, quality=70):
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
    分析图片，提取所有旅游团项目，返回合法的 JSON 数组，绝不要返回任何多余文字。
    格式必须完全如下：
    [
      {
        "destination": "目的地（如：武汉、青岛、内蒙古、岘港、沙坝、北京、桂林、九寨沟、江西、云南、厦门、韩国、海南）",
        "departure_location": "每个团右下角或价格旁标注的起飞城市（如：吉隆坡出发、槟城出发、新山出发、新加坡出发）",
        "tour_code": "SP开头的团号（如 SP002740）",
        "title": "行程名称或路线描述",
        "departure_dates": "海报中的出发日期",
        "price_numeric": 3199,
        "price_text": "RM 3199"
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
        "max_tokens": 4096,
        "reasoning_effort": "none"  # 彻底关闭思考模型，不输出多余废话
    }
    
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    if response.status_code != 200:
        raise Exception(f"API 请求失败: {response.text}")
    
    content = response.json()['choices'][0]['message']['content'].strip()
    
    json_match = re.search(r'\[\s*\{.*\}\s*\]', content, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except Exception:
            pass
            
    items = []
    blocks = re.findall(r'\{[^{}]*\}', content)
    for b in blocks:
        try:
            item = json.loads(b)
            if "destination" in item and "tour_code" in item:
                items.append(item)
        except Exception:
            continue
    return items

def generate_image_long(df):
    """使用 Matplotlib 动态生成一张支持中文的高清长图清单 (PNG)"""
    # 查找可用中文字体
    chinese_fonts = [f.name for f in fm.fontManager.ttflist if any(kw in f.name.lower() for kw in ['cjk', 'hei', 'song', 'sans', 'droid', 'sim'])]
    font_family = chinese_fonts[0] if chinese_fonts else 'sans-serif'
    
    row_count = max(len(df), 1)
    fig_height = 1.2 + row_count * 0.9
    fig, ax = plt.subplots(figsize=(10, fig_height), dpi=150)
    fig.patch.set_facecolor('#f8fafc')
    ax.set_facecolor('#f8fafc')
    ax.axis('off')
    
    # 绘制头部
    ax.text(0.5, 0.98, "✈️ 旅游团筛选清单", fontsize=18, weight='bold', ha='center', va='top', color='#0f172a', fontfamily=font_family)
    ax.text(0.5, 0.94, f"共筛选出 {len(df)} 个旅游团行程", fontsize=11, ha='center', va='top', color='#64748b', fontfamily=font_family)
    
    y_start = 0.88
    step = 0.86 / row_count
    
    for i, (_, row in df.reset_index().iterrows()):
        y_pos = y_start - i * step
        # 卡片背景
        rect = plt.Rectangle((0.02, y_pos - step * 0.9), 0.96, step * 0.85, facecolor='white', edgecolor='#e2e8f0', linewidth=1.2, transform=ax.transAxes, zorder=1)
        ax.add_patch(rect)
        
        # 卡片内容
        dest = str(row.get('destination', ''))
        code = str(row.get('tour_code', ''))
        price = str(row.get('price_text', ''))
        loc = str(row.get('departure_location', ''))
        dates = str(row.get('departure_dates', ''))
        title = str(row.get('title', ''))
        
        ax.text(0.05, y_pos - step * 0.25, f"📍 {dest}  |  团号: {code}", fontsize=12, weight='bold', color='#1e293b', fontfamily=font_family, zorder=2)
        ax.text(0.95, y_pos - step * 0.25, f"{price}", fontsize=13, weight='bold', color='#e11d48', ha='right', fontfamily=font_family, zorder=2)
        ax.text(0.05, y_pos - step * 0.50, f"🛫 出发地: {loc}    📅 出发日期: {dates}", fontsize=9.5, color='#475569', fontfamily=font_family, zorder=2)
        ax.text(0.05, y_pos - step * 0.72, f"路线: {title[:48]}", fontsize=9.5, color='#64748b', fontfamily=font_family, zorder=2)
        
    buf = BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.2)
    plt.close(fig)
    return buf.getvalue()

def create_html_report(df):
    html_cards = ""
    for _, row in df.iterrows():
        html_cards += f"""
        <div style="border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; margin-bottom: 12px; background-color: #ffffff; page-break-inside: avoid;">
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #f1f5f9; padding-bottom: 8px;">
                <span style="font-size: 18px; font-weight: bold; color: #0f172a;">📍 {row.get('destination', '未知')}</span>
                <span style="font-size: 18px; font-weight: bold; color: #e11d48;">{row.get('price_text', 'N/A')}</span>
            </div>
            <div style="margin-top: 8px; color: #334155; font-size: 14px;">
                <p style="margin: 4px 0;"><strong>团号：</strong> {row.get('tour_code', '无')} &nbsp;&nbsp;|&nbsp;&nbsp; <strong>出发地：</strong> <span style="color:#0284c7; font-weight: bold;">{row.get('departure_location', '详见海报')}</span></p>
                <p style="margin: 4px 0;"><strong>出发日期：</strong> {row.get('departure_dates', '见海报')}</p>
                <p style="margin: 4px 0;"><strong>行程路线：</strong> {row.get('title', '无')}</p>
            </div>
        </div>
        """
        
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>旅游团筛选清单</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #f8fafc; padding: 15px; margin: 0; }}
            .header {{ text-align: center; margin-bottom: 20px; }}
            @media print {{ body {{ background: #fff; padding: 0; }} }}
        </style>
    </head>
    <body>
        <div class="header">
            <h2 style="color: #0f172a; margin-bottom: 5px;">✈️ 旅游团筛选清单</h2>
            <p style="color: #64748b; font-size: 14px; margin-top: 0;">手机点分享->打印->另存为PDF ｜ 电脑按 Ctrl+P 保存</p>
        </div>
        <div style="max-width: 800px; margin: 0 auto;">
            {html_cards}
        </div>
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
    if st.button("🚀 开始让 AI 批量分析图片", type="primary"):
        all_results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for idx, file in enumerate(uploaded_files):
            status_text.text(f"正在极速提取第 {idx + 1}/{len(uploaded_files)} 张: {file.name} ...")
            try:
                data = analyze_single_image(file)
                if data:
                    all_results.extend(data)
            except Exception as err:
                st.warning(f"{file.name} 提示: {str(err)}")
            
            progress_bar.progress((idx + 1) / len(uploaded_files))
            if idx + 1 < len(uploaded_files):
                time.sleep(1.5)
                
        status_text.empty()
        progress_bar.empty()
        
        if all_results:
            st.session_state.travel_data = all_results
            st.success(f"🎉 提取完成！共准确获取到 {len(all_results)} 条旅游团信息！")
        else:
            st.error("未能提取出有效旅游团数据，请检查网络后重试。")

if st.session_state.travel_data:
    st.markdown("---")
    df = pd.DataFrame(st.session_state.travel_data)
    
    if 'destination' in df.columns:
        df['destination'] = df['destination'].astype(str).str.strip()
    if 'departure_location' in df.columns:
        df['departure_location'] = df['departure_location'].astype(str).str.strip()
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
    
    # 导出专区
    st.markdown("### 📥 导出筛选结果")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        img_data = generate_image_long(filtered_df)
        st.download_button(
            label="🖼️ 下载清单长图 (PNG)",
            data=img_data,
            file_name="旅游团清单.png",
            mime="image/png",
            type="primary"
        )
        
    with col2:
        html_report = create_html_report(filtered_df)
        st.download_button(
            label="📄 导出 PDF 报告 (HTML)",
            data=html_report,
            file_name="旅游团报告.html",
            mime="text/html"
        )
        
    with col3:
        csv_bytes = filtered_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📊 下载 Excel / CSV",
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
