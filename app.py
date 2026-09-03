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
st.markdown("高精细度全板块识别，支持精准区分出发机场、2026学校假期超期校验与后台完成提醒。")

GROQ_API_KEY = "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"

OFFICIAL_HOLIDAYS = [
    (datetime.date(2026, 3, 20), datetime.date(2026, 3, 29), "2026 第一学期假期 (3月)"),
    (datetime.date(2026, 5, 22), datetime.date(2026, 6, 7), "2026 年中假期 (5/6月)"),
    (datetime.date(2026, 8, 28), datetime.date(2026, 9, 6), "2026 第二学期假期 (8/9月)"),
    (datetime.date(2026, 12, 4), datetime.date(2027, 1, 3), "2026 学年末大假期 (12月)"),
    (datetime.date(2027, 1, 23), datetime.date(2027, 2, 16), "2027 农历新年与跨年假期")
]

# 服务器级常驻任务管理器（关机断网重启依然能接续读取）
@st.cache_resource
def get_global_task_store():
    return {
        "running": False,
        "finished": False,
        "notified": False,
        "progress": 0.0,
        "status_msg": "",
        "results": [],
        "errors": []
    }

task = get_global_task_store()

def extract_tour_days(title_str):
    m = re.search(r'(\d+)\s*(?:天|D|d)', str(title_str))
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    return 1

def evaluate_holiday_fit(departure_date_str, duration_days):
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
            
            for h_start, h_end, h_name in OFFICIAL_HOLIDAYS:
                if dep_date >= h_start and ret_date <= h_end:
                    return 'exact', 0, h_name
                
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

def trigger_notification():
    js = """
    <script>
    (function() {
        try {
            if (navigator.vibrate) {
                navigator.vibrate([300, 150, 300, 150, 500]);
            }
        } catch(e) {}

        try {
            var ctx = new (window.AudioContext || window.webkitAudioContext)();
            var freqs = [523.25, 659.25, 783.99, 1046.50];
            freqs.forEach(function(f, i) {
                var osc = ctx.createOscillator();
                var gain = ctx.createGain();
                osc.type = 'triangle';
                osc.frequency.setValueAtTime(f, ctx.currentTime + i * 0.15);
                gain.gain.setValueAtTime(0.35, ctx.currentTime + i * 0.15);
                gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + i * 0.15 + 0.4);
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start(ctx.currentTime + i * 0.15);
                osc.stop(ctx.currentTime + i * 0.15 + 0.4);
            });
        } catch(e) {}

        try {
            parent.document.title = "【🔔 已完成分析！请查看结果】";
        } catch(e) {}

        try {
            if ("Notification" in window && Notification.permission === "granted") {
                new Notification("✈️ 旅游团分析已全部完成！", {
                    body: "海报数据已完整提取，请切回网页查看结果。",
                    icon: "https://fav.farm/✈️"
                });
            }
        } catch(e) {}
    })();
    </script>
    """
    components.html(js, height=0)

def compress_image(uploaded_file, max_size=850, quality=68):
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
    
    prompt = (
        "仔细扫描整张海报，提取所有板块的旅游团项目，返回纯 JSON 数组：\n"
        "1. 包含海报中所有板块（如 重庆、西藏、青岛、桂林、台湾、贵州、韩国、北疆、哈尔滨、九寨沟等）。\n"
        "2. 【起飞机场 departure_location】：根据卡片标题或右下角小字，准确标注『新加坡出发 (SIN)』、『新山出发 (JB)』或『吉隆坡出发 (KL)』。\n"
        "3. destination 填具体城市/国家。\n"
        "4. 同一行程如有多个出发日期，合并在 departure_dates 字段（如 '26/10, 28/10'）。\n"
        "输出 JSON 字段：destination, departure_location, tour_code, title, departure_dates, price_numeric, price_text。"
    )

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
        "temperature": 0.05,
        "max_tokens": 4096,
        "reasoning_effort": "none"
    }
    
    last_error = ""
    # 最多尝试 6 次，确保遇到免费额度限流能充分排队等候
    for attempt in range(6):
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
            
            items_raw = []
            json_match = re.search(r'\[\s*\{.*\}\s*\]', content, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group(0))
                    if isinstance(parsed, list) and len(parsed) > 0:
                        items_raw = parsed
                except Exception:
                    pass
            
            if not items_raw:
                items_raw = extract_partial_items(content)
                
            if items_raw:
                std_list = []
                seen_keys = set()
                for it in items_raw:
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

                    unique_key = (code_str, dest_str, loc_str, p_val, date_str)
                    if code_str and unique_key in seen_keys:
                        continue
                    seen_keys.add(unique_key)

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
                
            last_error = "未能识别出旅游团格式"
        elif response.status_code == 429:
            # 遇到 429 限流保护，读取等待时间并多缓冲 5 秒，彻底释放 TPM 额度
            wait_seconds = 30
            match = re.search(r'try again in ([\d\.]+)s', response.text)
            if match:
                wait_seconds = int(float(match.group(1))) + 5
            for remaining in range(wait_seconds, 0, -1):
                task_dict["status_msg"] = f"⏳ 正在冷却每分钟配额，后台等待 {remaining} 秒继续处理 {file_name} ..."
                time.sleep(1)
            continue
        else:
            last_error = "API 返回错误码 " + str(response.status_code)
            time.sleep(4)
            
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
        # 多图之间强制缓冲 12 秒，确保下一张图执行时每分钟 Token 计数器已经回满
        if idx + 1 < total:
            for c in range(12, 0, -1):
                task_dict["status_msg"] = f"☕ 配额平稳回血中，{c} 秒后开始分析下一张..."
                time.sleep(1)
            
    task_dict["running"] = False
    task_dict["finished"] = True
    task_dict["status_msg"] = "✅ 全部图片已在后台高精度解析完成！"

components.html("""
<div style="display:flex; align-items:center; justify-content:space-between; background:#f0fdf4; border:1px solid #bbf7d0; padding:10px 14px; border-radius:8px; font-family:sans-serif; margin-bottom:12px;">
    <span style="font-size:14px; color:#166534; font-weight:600;">🔔 开启后台完成声音与振动强提醒：</span>
    <button onclick="requestAudioAndNotify()" style="background:#16a34a; color:#fff; border:none; padding:7px 16px; border-radius:6px; font-weight:bold; cursor:pointer; font-size:13px;">点击授权启用</button>
</div>
<script>
function requestAudioAndNotify() {
    try {
        var ctx = new (window.AudioContext || window.webkitAudioContext)();
        ctx.resume();
    } catch(e) {}
    if ("Notification" in window) {
        Notification.requestPermission().then(function(perm) {
            if (perm === "granted") {
                alert("✅ 提醒功能已成功激活！后台运行完毕会自动播放和弦音并振动。");
            } else {
                alert("⚠️ 请在浏览器地址栏左侧网站权限中勾选允许通知与音频。");
            }
        });
    } else {
        alert("已激活网页提示音与物理振动通道！");
    }
}
</script>
""", height=58)

uploaded_files = st.file_uploader(
    "批量上传宣传图 (支持 JPG/PNG，可多选)", 
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True
)

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
    st.caption("💡 任务已在服务器持久后台运行，切出应用或息屏不会中断。")
    time.sleep(2)
    st.rerun()

elif task["finished"]:
    if not task["notified"]:
        trigger_notification()
        task["notified"] = True

    if task["results"]:
        st.success("🎉 深度提取完成！共准确获取到 " + str(len(task['results'])) + " 条全板块旅游团信息！")
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
    
    holiday_options = [
        "全部日期",
        "🎒 包含学校假期 (含最多超出2天)",
        "✨ 严格在学校假期内 (0超出)",
        "💼 仅平时非假期出发"
    ]
    selected_hol = st.sidebar.selectbox("🗓️ 学校假期筛选", holiday_options)
    
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
    csv_bytes = filtered_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📊 下载 Excel / CSV 表格",
        data=csv_bytes,
        file_name="旅游团清单.csv",
        mime="text/csv",
        type="primary"
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
                
                h_status = row.get('holiday_status')
                if h_status == 'exact':
                    st.success("🎒 完美在校假内 (" + str(row.get('holiday_name')) + ")")
                elif h_status == 'slight_over':
                    st.warning("⚠️ 包含校假，但超出 " + str(row.get('over_days')) + " 天（需请假）")
            with c3:
                st.markdown("### 💰 **" + str(row.get('price_text', '无')) + "**")
