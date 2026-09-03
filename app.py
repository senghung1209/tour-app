import streamlit as st
import pandas as pd
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

st.title("✈️ 旅游团宣传单智能分析与筛选 (OpenRouter 极速高精版)")
st.markdown("搭载前沿视觉多模态引擎：零企业认证墙、秒级多图解析、精准区分出发机场与 2026 学校假期。")

OPENROUTER_API_KEY = "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"

OFFICIAL_HOLIDAYS = [
    (datetime.date(2026, 3, 20), datetime.date(2026, 3, 29), "2026 第一学期假期 (3月)"),
    (datetime.date(2026, 5, 22), datetime.date(2026, 6, 7), "2026 年中假期 (5/6月)"),
    (datetime.date(2026, 8, 28), datetime.date(2026, 9, 6), "2026 第二学期假期 (8/9月)"),
    (datetime.date(2026, 12, 4), datetime.date(2027, 1, 3), "2026 学年末大假期 (12月)"),
    (datetime.date(2027, 1, 23), datetime.date(2027, 2, 16), "2027 农历新年与跨年假期")
]

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

def compress_image(uploaded_file, max_size=1000, quality=75):
    img = Image.open(uploaded_file)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=quality)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")

def parse_pipe_lines(content):
    items = []
    for line in content.strip().split("\n"):
        line = line.strip().strip("-*# `")
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 6:
            dest = parts[0]
            loc = parts[1]
            code = parts[2]
            title = parts[3]
            dates = parts[4]
            p_str = parts[5]
            
            try:
                p_val = int(re.sub(r'[^\d]', '', p_str))
            except Exception:
                p_val = 0
            
            if dest and (code or title):
                p_text = ("RM " + str(p_val)) if p_val > 0 else p_str
                items.append(make_tour_dict(dest, code, title, loc, dates, p_val, p_text))
    return items

def analyze_single_image(file_bytes, file_name, api_key):
    encoded_string = compress_image(BytesIO(file_bytes))
    
    prompt = (
        "仔细扫描整张海报中所有的旅游团板块（例如 重庆、西藏、青岛、桂林、台湾、贵州、韩国、北疆、哈尔滨、九寨沟等）。\n"
        "每行提取一个旅游团，严格使用竖线 | 隔开字段，格式如下：\n"
        "目的地|出发地|团号|天数路线|出发日期|价格\n\n"
        "【示范】：\n"
        "重庆|新加坡出发 (SIN)|SP002376|7天6夜 重庆8D风情线|31/12/26|RM2999\n"
        "贵州|新山出发 (JB)|SP002809|7天6夜 一路黔行 多彩贵州|18/11/26|RM2999\n"
        "贵州|新加坡出发 (SIN)|SP002729|7天6夜 一路黔行 多彩贵州|28/10, 06/11|RM2699\n\n"
        "【关键要求】：\n"
        "1. 仔细观察卡片右下角小字与航空标示，严格精确区分『新加坡出发 (SIN)』还是『新山出发 (JB)』还是『吉隆坡出发 (KL)』！\n"
        "2. 同一个团号如有多个出发日期，合并在同一行用逗号分隔，不要输出任何重复行。\n"
        "3. 只输出有效数据行，绝不输出任何多余废话或表头！"
    )

    candidate_models = [
        "qwen/qwen-2.5-vl-72b-instruct",
        "meta-llama/llama-3.2-11b-vision-instruct:free",
        "google/gemini-2.0-flash-exp:free"
    ]
    
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://senghung-tour.streamlit.app",
        "X-Title": "Tour Poster Analyzer"
    }

    last_error = ""
    for model_name in candidate_models:
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded_string}"}}
                    ]
                }
            ],
            "temperature": 0.1
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=90)
            if response.status_code == 200:
                res_json = response.json()
                content = res_json['choices'][0]['message']['content'].strip()
                items = parse_pipe_lines(content)
                if items:
                    unique_list = []
                    seen = set()
                    for it in items:
                        k = (it["tour_code"], it["destination"], it["departure_location"], it["price_numeric"])
                        if it["tour_code"] and k in seen:
                            continue
                        seen.add(k)
                        unique_list.append(it)
                    return unique_list
            elif response.status_code == 404:
                continue
            else:
                err_msg = response.text
                try:
                    err_msg = response.json().get("error", {}).get("message", response.text)
                except Exception:
                    pass
                last_error = f"{model_name} 报错 ({response.status_code}): {err_msg}"
        except Exception as e:
            last_error = str(e)
            continue

    raise Exception(last_error if last_error else "未能匹配可用模型端点")

def background_worker(files_data, task_dict, api_key):
    total = len(files_data)
    for idx, (f_name, f_bytes) in enumerate(files_data):
        task_dict["status_msg"] = f"⚡ 正在极速全板块解析第 {idx + 1}/{total} 张: {f_name} ..."
        try:
            data = analyze_single_image(f_bytes, f_name, api_key)
            if data:
                task_dict["results"].extend(data)
            else:
                task_dict["errors"].append(f"{f_name}: 未能提取到有效数据")
        except Exception as err:
            task_dict["errors"].append(f"{f_name}: {str(err)}")
            
        task_dict["progress"] = (idx + 1) / total
        time.sleep(1.0)
            
    task_dict["running"] = False
    task_dict["finished"] = True
    task_dict["status_msg"] = "✅ 全部海报已解析完成！"

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
    st.success(f"已选择 {len(uploaded_files)} 张图片")
    
    if not task["running"]:
        if st.button("🚀 开始极速后台批量分析", type="primary"):
            task["running"] = True
            task["finished"] = False
            task["notified"] = False
            task["progress"] = 0.0
            task["results"] = []
            task["errors"] = []
            task["status_msg"] = "正在启动极速视觉多模态引擎..."
            
            files_data = [(f.name, f.getvalue()) for f in uploaded_files]
            t = threading.Thread(target=background_worker, args=(files_data, task, OPENROUTER_API_KEY), daemon=True)
            t.start()
            st.rerun()

if task["running"]:
    st.info(task["status_msg"])
    st.progress(task["progress"])
    st.caption("💡 任务已在服务器后台运行，切出应用或锁屏不会中断。")
    time.sleep(2)
    st.rerun()

elif task["finished"]:
    if not task["notified"]:
        trigger_notification()
        task["notified"] = True

    if task["results"]:
        st.success(f"🎉 提取完成！共准确获取到 {len(task['results'])} 条全板块旅游团信息！")
    if task["errors"]:
        for e in task["errors"]:
            st.warning(f"⚠️ {e}")

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
    
    # --- 修复滑块边界：过滤掉 0 元异常值，防止 StreamlitJSNumberBoundsError ---
    valid_prices = df[df['price_numeric'] > 0]['price_numeric']
    if not valid_prices.empty:
        min_val = int(valid_prices.min())
        max_val = int(valid_prices.max())
    else:
        min_val = 500
        max_val = 15000

    if min_val >= max_val:
        max_val = min_val + 1000

    # 规范化整型并设置安全步长
    min_val = int(min_val)
    max_val = int(max_val)
    price_range = st.sidebar.slider(
        "价格预算范围 (RM)", 
        min_value=min_val, 
        max_value=max_val, 
        value=(min_val, max_val),
        step=50
    )
    
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
                
                h_status = row.get('holiday_status')
                if h_status == 'exact':
                    st.success(f"🎒 完美在校假内 ({row.get('holiday_name')})")
                elif h_status == 'slight_over':
                    st.warning(f"⚠️ 包含校假，但超出 {row.get('over_days')} 天（需请假）")
            with c3:
                st.markdown(f"### 💰 **{row.get('price_text', '无')}**")
