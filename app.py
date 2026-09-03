import streamlit as st
import pandas as pd
import json
import requests
import base64
import time
import re
import datetime
import threading
from io import BytesIO
from PIL import Image
import streamlit.components.v1 as components

st.set_page_config(page_title="AI 旅游团智能筛选助手", page_icon="✈️", layout="wide")

st.title("✈️ 旅游团宣传单智能分析与筛选")
st.markdown("支持后台不中断运行、2026官方学校假期精确实装（支持最多超出2天提醒）！")

GROQ_API_KEY = "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"

# 严格匹配官方 2026 学年日历
OFFICIAL_2026_HOLIDAYS = [
    (datetime.date(2026, 3, 20), datetime.date(2026, 3, 29), "2026 第一学期假期 (3月)"),
    (datetime.date(2026, 5, 22), datetime.date(2026, 6, 7), "2026 年中假期 (5/6月)"),
    (datetime.date(2026, 8, 28), datetime.date(2026, 9, 6), "2026 第二学期假期 (8/9月)"),
    (datetime.date(2026, 12, 4), datetime.date(2027, 1, 3), "2026 学年末大假期 (12月)")
]

def extract_tour_days(title_str):
    """从路线或标题提取行程天数（如 8D6N, 8天6晚 -> 8）"""
    m = re.search(r'(\d+)\s*(?:天|D|d)', str(title_str))
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    return 1

def evaluate_holiday_fit(departure_date_str, duration_days):
    """
    精确比对 2026 官方假期：
    - status: 'exact' (完全在假期内), 'slight_over' (超出<=2天), 'none' (不符合)
    - over_days: 超出天数
    - name: 假期名称
    """
    matches = re.findall(r'(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?', str(departure_date_str))
    if not matches:
        return 'none', 0, ""

    best_status = 'none'
    min_over = 999
    matched_name = ""

    for d, mth, y in matches:
        d = int(d)
        mth = int(mth)
        if not y:
            y = 2026
        else:
            y = int(y)
            if y < 100:
                y += 2000
        try:
            dep_date = datetime.date(y, mth, d)
            ret_date = dep_date + datetime.timedelta(days=max(duration_days - 1, 0))
            
            for h_start, h_end, h_name in OFFICIAL_2026_HOLIDAYS:
                # 情况1：完全在假期内
                if dep_date >= h_start and ret_date <= h_end:
                    return 'exact', 0, h_name
                
                # 情况2：有重叠但稍有超出
                if not (ret_date < h_start or dep_date > h_end):
                    early_days = max((h_start - dep_date).days, 0)
                    late_days = max((ret_date - h_end).days, 0)
                    total_over = early_days + late_days
                    if total_over <= 2 and total_over < min_over:
                        min_over = total_over
                        best_status = 'slight_over'
                        matched_name = h_name
        except Exception:
            continue

    if best_status == 'slight_over':
        return 'slight_over', min_over, matched_name
    return 'none', 0, ""

def make_tour_dict(dest, code, title, loc, dates, price_num, price_txt):
    days = extract_tour_days(title)
    status, over_days, hol_name = evaluate_holiday_fit(dates, days)
    
    d = dict()
    d["destination"] = dest
    d["tour_code"] = code
    d["title"] = title
    d["departure_location"] = loc
    d["departure_dates"] = dates
    d["price_numeric"] = price_num
    d["price_text"] = price_txt
    d["holiday_status"] = status
    d["over_days"] = over_days
    d["holiday_name"] = hol_name
    return d

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

                item = make_tour_dict(
                    dest if dest else "精选目的地",
                    code,
                    title,
                    loc if loc else "详见海报",
                    dates,
                    p_val,
                    p_text
                )
                items.append(item)
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

                            entry = make_tour_dict(
                                dest_str,
                                code_str,
                                title_str,
                                loc_str,
                                date_str,
                                p_val,
                                final_price_str
                            )
                            std_list.append(entry)
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
                task_dict["status_msg"] = "⏳ 触发配额保护，后台等待 " + str(remaining) + " 秒继续处理 " + file_name + " ..."
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
    cards = []
    for _, row in df.iterrows():
        d = str(row.get('destination', '未知'))
        p = str(row.get('price_text', 'N/A'))
        c = str(row.get('tour_code', '无'))
        l = str(row.get('departure_location', '详见海报'))
        dt = str(row.get('departure_dates', '见海报'))
        t = str(row.get('title', '无'))
        
        status = row.get('holiday_status')
        over = row.get('over_days', 0)
        hname = row.get('holiday_name', '')
        
        hol_badge = ""
        if status == 'exact':
            hol_badge = " &nbsp;|&nbsp; <span style='color:#16a34a; font-weight:bold;'>🎒 完美在校假内 (" + hname + ")</span>"
        elif status == 'slight_over':
            hol_badge = " &nbsp;|&nbsp; <span style='color:#ea580c; font-weight:bold;'>⚠️ 超出假期 " + str(over) + " 天（需请假）</span>"

        item = (
            "<div class='card'>"
            "<div class='card-header'>"
            "<span class='dest'>📍 " + d + "</span>"
            "<span class='price'>" + p + "</span>"
            "</div>"
            "<div class='card-body'>"
            "<div><strong>团号：</strong> " + c + " &nbsp;|&nbsp; <strong>出发地：</strong> <span class='badge'>" + l + "</span>" + hol_badge + "</div>"
            "<div><strong>📅 出发日期：</strong> " + dt + "</div>"
            "<div><strong>路线：</strong> " + t + "</div>"
            "</div>"
            "</div>"
        )
        cards.append(item)
    
    cards_str = "".join(cards)
    count_str = str(len(df))

    html = (
        "<!DOCTYPE html>\n"
        "<html lang='zh-CN'>\n"
        "<head>\n"
        "<meta charset='UTF-8'>\n"
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>\n"
        "<title>旅游团筛选清单</title>\n"
        "<script src='[https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js](https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js)"></script>\n"
        "<style>\n"
        "body { font-family: -apple-system, sans-serif; background: #f1f5f9; margin: 0; padding: 15px; color: #0f172a; }\n"
        ".toolbar { max-width: 650px; margin: 0 auto 15px auto; display: flex; gap: 10px; }\n"
        ".btn { flex: 1; padding: 12px; border: none; border-radius: 8px; font-size: 15px; font-weight: 600; cursor: pointer; color: #fff; }\n"
        ".btn-img { background: #e11d48; }\n"
        ".btn-pdf { background: #0284c7; }\n"
        "#capture-area { max-width: 650px; margin: 0 auto; background: #fff; padding: 20px; border-radius: 12px; }\n"
        ".title { text-align: center; font-size: 20px; font-weight: bold; margin-bottom: 4px; }\n"
        ".subtitle { text-align: center; color: #64748b; font-size: 13px; margin-bottom: 16px; }\n"
        ".card { border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; margin-bottom: 10px; background: #f8fafc; }\n"
        ".card-header { display: flex; justify-content: space-between; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; margin-bottom: 6px; }\n"
        ".dest { font-size: 16px; font-weight: bold; }\n"
        ".price { font-size: 17px; font-weight: bold; color: #e11d48; }\n"
        ".card-body { font-size: 13px; line-height: 1.6; color: #334155; }\n"
        ".badge { color: #0284c7; font-weight: 600; }\n"
        "@media print { .toolbar { display: none; } body { background: #fff; padding: 0; } }\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        "<div class='toolbar'>\n"
        "<button class='btn btn-img' onclick='saveImg()'>🖼️ 保存为手机长图</button>\n"
        "<button class='btn btn-pdf' onclick='window.print()'>📄 另存为 PDF 文件</button>\n"
        "</div>\n"
        "<div id='capture-area'>\n"
        "<div class='title'>✈️ 旅游团筛选清单</div>\n"
        "<div class='subtitle'>共筛选出 " + count_str + " 个精选行程</div>\n"
        + cards_str +
        "</div>\n"
        "<script>\n"
        "function saveImg() {\n"
        "  html2canvas(document.getElementById('capture-area'), { scale: 2 }).then(function(canvas) {\n"
        "    var a = document.createElement('a');\n"
        "    a.download = '旅游团清单.png';\n"
        "    a.href = canvas.toDataURL('image/png');\n"
        "    a.click();\n"
        "  });\n"
        "}\n"
        "</script>\n"
        "</body>\n"
        "</html>"
    )
    return html

uploaded_files = st.file_uploader(
    "批量上传宣传图 (支持 JPG/PNG，可多选)", 
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True
)

task = st.session_state.task_state

if uploaded_files:
    st.success("已选择 " + str(len(uploaded_files)) + " 张图片")
    
    if not task["running"]:
        if st.button("🚀 开始后台批量分析", type="primary"):
            task["running"] = True
            task["finished"] = False
            task["notified"] = False
            task["progress"] = 0.0
            task["results"] = []
            task["errors"] = []
            task["status_msg"] = "正在启动独立工作线程..."
            
            files_data = [(f.name, f.getvalue()) for f in uploaded_files]
            t = threading.Thread(target=background_worker, args=(files_data, task), daemon=True)
            t.start()
            st.rerun()

if task["running"]:
    st.info(task["status_msg"])
    st.progress(task["progress"])
    st.caption("💡 任务已在服务器后台运行，可锁屏或切换应用，完成后会自动发送系统通知与提示音。")
    time.sleep(2)
    st.rerun()

elif task["finished"]:
    if not task["notified"]:
        trigger_notification()
        task["notified"] = True

    if task["results"]:
        st.success("🎉 提取完成！共准确获取到 " + str(len(task['results'])) + " 条旅游团信息！")
    if task["errors"]:
        for e in task["errors"]:
            st.warning("⚠️ " + str(e))

if task["results"]:
    st.markdown("---")
    df = pd.DataFrame(task["results"])
    
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
    
    raw_locs = sorted([l for l in df['departure_location'].unique() if l and l != "nan"])
    loc_list = ["全部", "🇲🇾 全马来西亚出发 (包含吉隆坡/新山/槟城)"] + raw_locs
    selected_loc = st.sidebar.selectbox("选择起飞地点", loc_list)
    
    # 严格匹配你的假期要求
    holiday_options = [
        "全部日期",
        "🎒 包含学校假期 (含最多超出2天)",
        "✨ 严格在学校假期内 (0超出)",
        "💼 仅平时非假期出发"
    ]
    selected_hol = st.sidebar.selectbox("🗓️ 2026 学校假期筛选", holiday_options)
    
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
            lambda loc: any(kw in loc for kw in malaysia_keywords)
        )]
    elif selected_loc != "全部":
        filtered_df = filtered_df[filtered_df['departure_location'] == selected_loc]
        
    # 执行假期筛选
    if selected_hol == "🎒 包含学校假期 (含最多超出2天)":
        filtered_df = filtered_df[filtered_df['holiday_status'].isin(['exact', 'slight_over'])]
    elif selected_hol == "✨ 严格在学校假期内 (0超出)":
        filtered_df = filtered_df[filtered_df['holiday_status'] == 'exact']
    elif selected_hol == "💼 仅平时非假期出发":
        filtered_df = filtered_df[filtered_df['holiday_status'] == 'none']
        
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
        
    st.markdown("### 符合条件的旅游团共 **" + str(len(filtered_df)) + "** 个：")
    
    display_cols = [c for c in ['destination', 'tour_code', 'departure_location', 'departure_dates', 'price_text', 'title'] if c in filtered_df.columns]
    st.dataframe(filtered_df[display_cols], use_container_width=True)
    
    for _, row in filtered_df.iterrows():
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 2, 2])
            with c1:
                st.markdown("### 📍 **" + str(row.get('destination', '未知')) + "**")
                st.write("**路线：** " + str(row.get('title', '无')))
                st.write("**团号：** `" + str(row.get('tour_code', '无')) + "`")
            with c2:
                st.markdown("🛫 **出发地：** `" + str(row.get('departure_location', '详见海报')) + "`")
                st.write("📅 **出发日期：** " + str(row.get('departure_dates', '见海报')))
                
                # 假期状态精准提示
                h_status = row.get('holiday_status')
                if h_status == 'exact':
                    st.success("🎒 完美在校假内 (" + str(row.get('holiday_name')) + ")")
                elif h_status == 'slight_over':
                    st.warning("⚠️ 包含校假，但超出 " + str(row.get('over_days')) + " 天（需请假）")
            with c3:
                st.markdown("### 💰 **" + str(row.get('price_text', '无')) + "**")
