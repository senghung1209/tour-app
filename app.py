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

def compress_image(uploaded_file, max_size=800, quality=70):
    """黄金分辨率 800px：既能看清文字细节，又不会撑爆 Token 限制"""
    img = Image.open(uploaded_file)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=quality)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")

def analyze_single_image(file, status_placeholder):
    encoded_string = compress_image(file)
    
    prompt = """
    仔细提取海报中所有旅游团项目，返回纯 JSON 数组，严禁包含任何前缀、解释或标记：
    [
      {
        "destination": "目的地(如武汉/青岛/内蒙古/沙坝/北京/桂林/九寨沟/江西/云南/厦门/韩国/海南)",
        "departure_location": "起飞城市(如吉隆坡出发/槟城出发/新山出发/新加坡出发，未写填马来西亚出发)",
        "tour_code": "SP团号(如SP002740)",
        "title": "天数与行程标题",
        "departure_dates": "出发日期(如01/11/26)",
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
        "max_tokens": 3000,
        "reasoning_effort": "none"
    }
    
    for attempt in range(3):
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        
        if response.status_code == 200:
            content = response.json()['choices'][0]['message']['content'].strip()
            
            # 清理可能存在的思考标签或 markdown
            if "</think>" in content:
                content = content.split("</think>")[-1].strip()
            content = re.sub(r'```(?:json)?', '', content).strip()
            
            # 1. 尝试直接整段 JSON 数组匹配
            json_match = re.search(r'\[\s*\{.*\}\s*\]', content, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group(0))
                except Exception:
                    pass
            
            # 2. 尝试单个 JSON 块汇总
            items = []
            for b in re.findall(r'\{[^{}]*\}', content):
                try:
                    item = json.loads(b)
                    if "destination" in item or "tour_code" in item:
                        items.append(item)
                except Exception:
                    continue
            if items:
                return items
                
            raise Exception(f"模型未返回合规数据，返回内容片段：{content[:200]}")
            
        elif response.status_code == 429:
            # 遭遇官方 8000 TPM 限流，读取等待时间
            wait_seconds = 20
            match = re.search(r'try again in ([\d\.]+)s', response.text)
            if match:
                wait_seconds = int(float(match.group(1))) + 2
            
            for remaining in range(wait_seconds, 0, -1):
                status_placeholder.warning(f"⏳ 触发免费额度保护，倒计时 {remaining} 秒后自动继续处理 {file.name} ...")
                time.sleep(1)
            continue
        else:
            raise Exception(f"API 请求失败 ({response.status_code}): {response.text}")
            
    raise Exception("多次请求超时，请重试。")

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
        <script src="[https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js](https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js)"></script>
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
        errors = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        start_time = time.time()
        for idx, file in enumerate(uploaded_files):
            status_text.info(f"⚡ 正在分析第 {idx + 1}/{len(uploaded_files)} 张: {file.name} ...")
            try:
                data = analyze_single_image(file, status_text)
                if data:
                    all_results.extend(data)
            except Exception as err:
                errors.append(f"{file.name}: {str(err)}")
            
            progress_bar.progress((idx + 1) / len(uploaded_files))
            # 正常无 429 时，仅需微小缓冲 1.5 秒
            if idx + 1 < len(uploaded_files):
