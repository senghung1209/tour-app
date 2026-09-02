import streamlit as st
import pandas as pd
import json
import requests
import base64
import time
import re
import threading
from io import BytesIO
from PIL import Image
import streamlit.components.v1 as components

st.set_page_config(page_title="AI 旅游团智能筛选助手", page_icon="✈️", layout="wide")

st.title("✈️ 旅游团宣传单智能分析与筛选")
st.markdown("支持后台运行与完成提醒！上传海报后点击开始，即使切出应用，处理完毕也会弹窗与发声提醒。")

GROQ_API_KEY = "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"

# 全局状态管理
if "task_state" not in st.session_state:
    st.session_state.task_state = {
        "running": False,
        "finished": False,
        "notified": False,
        "progress": 0.0,
        "status_msg": "",
        "results": [],
        "errors": []
    }

def trigger_notification():
    """触发手机/电脑浏览器的系统通知与提示音"""
    components.html("""
    <script>
    function notifyUser() {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'sine';
            osc.frequency.setValueAtTime(587.33, ctx.currentTime);
            osc.frequency.setValueAtTime(880, ctx.currentTime + 0.15);
            gain.gain.setValueAtTime(0.3, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.6);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start();
            osc.stop(ctx.currentTime + 0.6);
        } catch(e) {}

        if ("Notification" in window) {
            if (Notification.permission === "granted") {
                new Notification("✈️ 旅游团分析完成！", {
                    body: "所有海报数据已提取完毕，快回来看结果吧！",
                    icon: "https://fav.farm/✈️"
                });
            } else if (Notification.permission !== "denied") {
                Notification.requestPermission().then(permission => {
                    if (permission === "granted") {
                        new Notification("✈️ 旅游团分析完成！", {
                            body: "所有海报数据已提取完毕，快回来看结果吧！",
                            icon: "https://fav.farm/✈️"
                        });
                    }
                });
            }
        }
    }
    notifyUser();
    </script>
    """, height=0)

def compress_image(uploaded_file, max_size=650, quality=55):
    img = Image.open(uploaded_file)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=quality)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")

def extract_partial_items(content):
    """强化容错：从任意断裂、未闭合或残缺的文本中抽取出所有旅游团对象"""
    items = []
    # 匹配每一个独立的 JSON object
    blocks = re.findall(r'\{[^{}]*\}', content)
    for b in blocks:
        try:
            it = json.loads(b)
            # 只要包含目的地或团号任意一个，即为有效卡片
            if "destination" in it or "tour_code" in it or "title" in it:
                dest = str(it.get("destination", "精选目的地")).strip()
                code = str(it.get("tour_code", "")).strip()
                title = str(it.get("title", f"{dest}游")).strip()
                loc = str(it.get("departure_location", "详见海报")).strip()
                dates = str(it.get("departure_dates", "见海报")).strip()
                
                # 价格抽取与转换
                p_raw = it.get("price_numeric", 0)
                try:
                    p_val = int(re.sub(r'[^\d]', '', str(p_raw)))
                except Exception:
                    p_val = 0
                
                p_text = str(it.get("price_text", f"RM {p_val}" if p_val > 0 else "详见海报")).strip()
                
                items.append({
                    "destination": dest if dest else "精选目的地",
                    "tour_code": code,
                    "title": title,
                    "departure_location": loc if loc else "详见海报",
                    "departure_dates": dates,
                    "price_numeric": p_val,
                    "price_text": p_text
                })
        except Exception:
            continue
    return items

def analyze_single_image(file_bytes, file_name, task_dict):
    encoded_string = compress_image(BytesIO(file_bytes))
    
    prompt = """
    分析图片，提取所有旅游团项目，返回 JSON 数组：
    [
      {
        "destination": "目的地（如：武汉、青岛、内蒙古、岘港、沙坝、北京、桂林、九寨沟、江西、云南、厦门、韩国、海南）",
        "departure_location": "起飞城市（如：吉隆坡出发、槟城出发、新山出发、新加坡出发）",
        "tour_code": "SP开头的团号（如 SP002740）",
        "title": "行程名称或路线描述",
        "departure_dates": "出发日期",
        "price_numeric": 3199,
        "price_text": "RM 3199"
      }
    ]
    注意：只输出合法的 JSON 数组，不要任何多余解释。
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
        "reasoning_effort": "none"
    }
    
    last_error = ""
    for attempt in range(4):
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=180)
        except requests.exceptions.Timeout:
            last_error = "请求超时(180s)，可能当前并发较高"
            time.sleep(3)
            continue
        except Exception as e:
            last_error = f"网络异常: {str(e)}"
            time.sleep(3)
            continue
            
        if response.status_code == 200:
            content = response.json()['choices'][0]['message']['content'].strip()
            
            if "</think>" in content:
                content = content.split("</think>")[-1].strip()
            content = re.sub(r'```(?:json)?', '', content).strip()
            
            # 1. 尝试直接整段 JSON 数组解析
            json_match = re.search(r'\[\s*\{.*\}\s*\]', content, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group(0))
                    if isinstance(parsed, list) and len(parsed) > 0:
                        # 规整字段
                        std_list = []
                        for it in parsed:
                            p_val = it.get("price_numeric", 0)
                            try:
                                p_val = int(re.sub(r'[^\d]', '', str(p_val)))
                            except Exception:
                                p_val = 0
                            std_list.append({
                                "destination": str(it.get("destination", "精选目的地")).strip(),
                                "tour_code": str(it.get("tour_code", "")).strip(),
                                "title": str(it.get("title", "")).strip(),
                                "departure_location": str(it.get("departure_location", "详见海报")).strip(),
                                "departure_dates": str(it.get("departure_dates", "见海报")).strip(),
                                "price_numeric": p_val,
                                "price_text": str(it.get("price_text", f"RM {p_val}")).strip()
                            })
                        return std_list
                except Exception:
                    pass
            
            # 2. 如果整段解析失败（常见于末尾被截断），使用容错抽取器抢救每一个独立的团对象
            rescued_items = extract_partial_items(content)
            if rescued_items:
                return rescued_items
                
            # 3. 如果以上还是空，尝试用正则兜底抽取文字行
            fallback_items = []
            for line in content.split('\n'):
                sp = re.search(r'(SP\d{4,7})', line)
                if sp:
                    p = re.search(r'RM\s*(\d+)', line)
                    p_val = int(p.group(1)) if p else 0
                    fallback_items.append({
                        "destination": "精选目的地",
                        "tour_code": sp.group(1),
                        "title": line.strip("- *#"),
                        "departure_location": "详见海报",
                        "departure_dates": "见海报",
                        "price_numeric": p_val,
                        "price_text": f"RM {p_val}" if p_val > 0 else "详见海报"
                    })
            if fallback_items:
                return fallback_items
                
            last_error = f"未能识别出旅游团格式，AI 返回片段：{content[:120]}"
            
        elif response.status_code == 429:
            wait_seconds = 25
            match = re.search(r'try again in ([\d\.]+)s', response.text)
            if match:
                wait_seconds = int(float(match.group(1))) + 2
            
            for remaining in range(wait_seconds, 0, -1):
                task_dict["status_msg"] = f"⏳ 触发免费配额保护，后台等待 {remaining} 秒继续处理 {file_name} ..."
                time.sleep(1)
            continue
        else:
            last_error = f"API 返回错误码 {response.status_code}: {response.text[:150]}"
            time.sleep(3)
            
    raise Exception(last_error if last_error else "多次尝试仍未能获取有效数据")

def background_worker(files_data, task_dict):
    total = len(files_data)
    for idx, (f_name, f_bytes) in enumerate(files_data):
        task_dict["status_msg"] = f"⚡ 后台正在解析第 {idx + 1}/{total} 张: {f_name} ..."
        try:
            data = analyze_single_image(f_bytes, f_name, task_dict)
            if data:
                task_dict["results"].extend(data)
            else:
                task_dict["errors"].append(f"{f_name}: 未能提取到有效数据")
        except Exception as err:
            task_dict["errors"].append(f"{f_name}: {str(err)}")
            
        task_dict["progress"] = (idx + 1) / total
        # 多图之间增加 3 秒间隔，平滑 Token 消耗曲线
        if idx + 1 < total:
            time.sleep(3.0)
            
    task_dict["running"] = False
    task_dict["finished"] = True
    task_dict["status_msg"] = "✅ 全部图片已在后台分析完成！"

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
                align-items
