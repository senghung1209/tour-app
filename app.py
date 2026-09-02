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
    js = (
        "<script>\n"
        "try {\n"
        "  var ctx = new (window.AudioContext || window.webkitAudioContext)();\n"
        "  var osc = ctx.createOscillator();\n"
        "  var gain = ctx.createGain();\n"
        "  osc.type = 'sine';\n"
        "  osc.frequency.setValueAtTime(587.33, ctx.currentTime);\n"
        "  osc.frequency.setValueAtTime(880, ctx.currentTime + 0.15);\n"
        "  gain.gain.setValueAtTime(0.3, ctx.currentTime);\n"
        "  gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.6);\n"
        "  osc.connect(gain);\n"
        "  gain.connect(ctx.destination);\n"
        "  osc.start();\n"
        "  osc.stop(ctx.currentTime + 0.6);\n"
        "} catch(e) {}\n"
        "if ('Notification' in window) {\n"
        "  if (Notification.permission === 'granted') {\n"
        "    new Notification('✈️ 旅游团分析完成！', { body: '所有海报数据已提取完毕！' });\n"
        "  } else if (Notification.permission !== 'denied') {\n"
        "    Notification.requestPermission().then(function(p) {\n"
        "      if (p === 'granted') {\n"
        "        new Notification('✈️ 旅游团分析完成！', { body: '所有海报数据已提取完毕！' });\n"
        "      }\n"
        "    });\n"
        "  }\n"
        "}\n"
        "</script>\n"
    )
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
                
                raw_text = it.get("price_text")
                if raw_text:
                    p_text = str(raw_text).strip()
                elif p_val > 0:
                    p_text = "RM " + str(p_val)
                else:
                    p_text = "详见海报"

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
    prompt = "分析图片提取所有旅游团项目，返回纯JSON数组，包含字段：destination, departure_location, tour_code, title, departure_dates, price_numeric, price_text。严禁输出任何多余说明。"

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
                            p_raw = it.get("price_numeric", 0)
                            try:
                                p_val = int(re.sub(r'[^\d]', '', str(p_raw)))
                            except Exception:
                                p_val = 0
                            
                            dest_str = str(it.get("destination", "精选目的地")).strip()
                            code_str = str(it.get("tour_code", "")).strip()
                            title_str = str(it.get("title", "")).strip()
                            loc_str = str(it.get("departure_location", "详见海报")).strip()
                            date_str = str(it.get("departure_dates", "见海报")).strip()
                            
                            raw_price_str = it.get("price_text")
                            if raw_price_str:
                                final_price_str = str(raw_price_str).strip()
                            elif p_val > 0:
                                final_price_str = "RM " + str(p_val)
                            else:
                                final_price_str = "详见海报"

                            std_list.append({
                                "destination": dest_str,
                                "tour_code": code_str,
                                "title": title_str,
                                "departure_location": loc_str,
                                "departure_dates": date
