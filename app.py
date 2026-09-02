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
    js = """<script>
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
            Notification.requestPermission().then(function(p) {
                if (p === "granted") {
                    new Notification("✈️ 旅游团分析完成！", {
                        body: "所有海报数据已提取完毕，快回来看结果吧！",
                        icon: "https://fav.farm/✈️"
                    });
                }
            });
        }
    }
    </script>"""
    components.html(js, height=0)

def compress_image(uploaded_file, max_size=650, quality=55):
    img = Image.open(uploaded_file)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=quality)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")

def extract_partial_items(content):
    items = []
    blocks = re.findall(r'\{[^{}]*\}', content)
    for b in blocks:
        try:
            it = json.loads(b)
            if "destination" in it or "tour_code" in it or "title" in it:
                dest = str(it.get("destination", "精选目的地")).strip()
                code = str(it.get("tour_code", "")).strip()
                title = str(it.get("title", dest + "游")).strip()
                loc = str(it.get("departure_location", "详见海报")).strip()
                dates = str(it.get("departure_dates", "见海报")).strip()
                p_raw = it.get("price_numeric", 0)
                try:
                    p_val = int(re.sub(r'[^\d]', '', str(p_raw)))
                except Exception:
                    p_val = 0
                p_text = str(it.get("price_text", ("RM " + str(p_val)) if p_val > 0 else "详见海报")).strip()
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
    prompt = "分析图片，提取所有旅游团项目，返回合法的纯 JSON 数组（含 destination, departure_location, tour_code, title, departure_dates, price_numeric, price_text 字段），不要任何解释。"

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": "Bearer " + GROQ_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "model": "qwen/qwen3.6-27b",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + encoded_string}}
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
            last_error = "请求超时(180s)"
            time.sleep(3)
            continue
        except Exception as e:
            last_error = "网络异常: " + str(e)
            time.sleep(3)
            continue
            
        if response.status_code == 200:
            content = response.json()['choices'][0]['message']['content'].strip()
            if "</think>" in content:
                content = content.split("</think>")[-1].strip()
            content = re.sub(r'```(?:json)?', '', content).strip()
            
            json_match = re.search(r'\[\s*\{.*\}\s*\]', content, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group(0))
                    if isinstance(parsed, list) and len(parsed) > 0:
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
                                "price_text": str(it.get("price_text", "RM " + str(p_val))).strip()
                            })
                        return std_list
                except Exception:
                    pass
            
            rescued_items = extract_partial_items(content)
            if rescued_items:
                return rescued_items
                
            last_error = "未能识别出旅游团格式"
        elif response.status_code == 429:
            wait_seconds = 25
            match = re.search(r'try again in ([\d\.]+)s', response.text)
            if match:
                wait_seconds = int(float(match.group(1))) + 2
            for remaining in range(wait_seconds, 0, -1):
                task_dict["status_msg"] = "⏳ 触发免费配额保护，后台等待 " + str(remaining) + " 秒继续处理 " + file_name + " ..."
                time.sleep(1)
            continue
        else:
            last_error = "API 返回错误码 " + str(response.status_code)
            time.sleep(3)
            
    raise Exception(last_error if last_error else "多次尝试仍未能获取有效数据")

def background_worker(files_data, task_dict):
    total = len(files_data)
    for idx, (f_name, f_bytes) in enumerate(files_data):
        task_dict["status_msg"] = "⚡ 后台正在解析第 " + str(idx + 1) + "/" + str(total) + " 张: " + f_name + " ..."
        try:
            data = analyze_single_image(f_bytes, f_name, task_dict)
            if data:
                task_dict["results"].extend(data)
            else:
                task_dict["errors"].append(f_name + ": 未能提取到有效数据")
        except Exception as err:
            task_dict["errors"].append(f_name + ": " + str(err))
            
        task_dict["progress"] = (idx + 1) / total
        if idx + 1 < total:
            time.sleep(3.0)
            
    task_dict["running"] = False
    task_dict["finished"] = True
    task_dict["status_msg"] = "✅ 全部图片已在后台分析完成！"

def create_html_report(df):
    cards_list = []
    for _, row in df.iterrows():
        dest = str(row.get('destination', '未知'))
        price = str(row.get('price_text', 'N/A'))
        code = str(row.get('tour_code', '无'))
        loc = str(row.get('departure_location', '详见海报'))
        dates = str(row.get('departure_dates', '见海报'))
        title = str(row.get('title', '无'))
        card = '<div class="card"><div class="card-header"><span class="dest">📍 ' + dest + '</span><span class="price">' + price + '</span></div><div class="card-body"><div class="meta-row"><span><strong>团号：</strong> ' + code + '</span><span><strong>出发地：</strong> <span class="badge">' + loc + '</span></span></div><div class="dates"><strong>📅 出发日期：</strong> ' + dates + '</div><div class="route"><strong>路线：</strong> ' + title + '</div></div></div>'
        cards_list.append(card)

    cards_html = "".join(cards_list)
    total_str = str(len(df))
    
    # 采用 Base64 编码的通用外壳，防止粘贴代码时被编辑器断行损坏
    b64_template = "PCFET0NUWVBFIGh0bWw+PGh0bWwgbGFuZz0iemgtQ04iPjxoZWFkPjxtZXRhIGNoYXJzZXQ9IlVURi04Ij48bWV0YSBuYW1lPSJ2aWV3cG9ydCIgY29udGVudD0id2lkdGg9ZGV2aWNlLXdpZHRoLCBpbml0aWFsLXNjYWxlPTEuMCI+PHRpdGxlPuaXhea4uOWbouetlumAiem4heWNlTwvdGl0bGU+PHNjcmlwdCBzcmM9Imh0dHBzOi8vY2RuLmpzZGVsaXZyLm5ldC9ucG0vaHRtbDJjYW52YXNAMS40LjEvZGlzdC9odG1sMmNhbnZhcy5taW4uanMiPjwvc2NyaXB0PjxzdHlsZT5ib2R5e2ZvbnQtZmFtaWx5Oi1hcHBsZS1zeXN0ZW0sQmxpbmtNYWNTeXN0ZW1Gb250LCJTZWdvZSBVSSIsUm9ib3RvLCJQaW5nRmFuZyBTQyIsIkhpcmFnaW5vIFNhbnMgR0IiLCJNaWNyb3NvZnQgWWFIZWkiLHNhbnMtc2VyaWY7YmFja2dyb3VuZC1jb2xvcjojZjFmNWY5O21hcmdpbjowO3BhZGRpbmc6MTZweDtjb2xvcjojMGYxNzJhO30udG9vbGJhcnttYXgtd2lkdGg6NjUwcHg7bWFyZ2luOjAgYXV0byAxNnB4IGF1dG87ZGlzcGxheTpmbGV4O2dhcDoxMHB4O30uYnRue2ZsZXg6MTtwYWRkaW5nOjEycHg7Ym9yZGVyOm5vbmU7Ym9yZGVyLXJhZGl1czo4cHg7Zm9udC1zaXplOjE1cHg7Zm9udC13ZWlnaHQ6NjAwO2N1cnNvcjpwb2ludGVyO3RleHQtYWxpZ246Y2VudGVyO30uYnRuLWltZ3tiYWNrZ3JvdW5kLWNvbG9yOiNlMTFkNDg7Y29sb3I6I2ZmZjt9LmJ0bi1wZGZ7YmFja2dyb3VuZC1jb2xvcjojMDI4NGM3O2NvbG9yOiNmZmY7fSNjYXB0dXJlLWFyZWF7bWF4LXdpZHRoOjY1MHB4O21hcmdpbjowIGF1dG87YmFja2dyb3VuZC1jb2xvcjojZmZmZmZmO3BhZGRpbmc6MjRweDtib3JkZXItcmFkaXVzOjEycHg7Ym94LXNoYWRvdzowIDRweCA2cHggLTFweCByZ2JhKDAsMCwwLDAuMSk7fS5tYWluLXRpdGxle3RleHQtYWxpZ246Y2VudGVyO2ZvbnQtc2l6ZToyMnB4O2ZvbnQtd2VpZ2h0OmJvbGQ7bWFyZ2luOjAgMCA2cHggMDt9LnN1Yi10aXRsZXt0ZXh0LWFsaWduOmNlbnRlcjtjb2xvcjojNjQ3NDhiO2ZvbnQtc2l6ZToxM3B4O21hcmdpbjowIDAgMjB
