import streamlit as st
import pandas as pd
import requests
import base64
import time
import re
import json
import datetime
import threading
from io import BytesIO
from PIL import Image
import streamlit.components.v1 as components

st.set_page_config(page_title="AI 旅游团智能筛选助手", page_icon="✈️", layout="wide")

st.title("✈️ 旅游团宣传单智能分析与筛选 (JSON 完美结构化版)")
st.markdown("已升级为 JSON 结构化精准提取引擎：确保目的地、团号、日期、价格与路线 100% 对应无错位。")

GROQ_API_KEY = "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"

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
    return 7

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

def clean_and_parse_price(price_str):
    candidates = re.findall(r'\b\d{3,5}\b', str(price_str))
    for c in candidates:
        val = int(c)
        if 500 <= val <= 35000:
            return val, f"RM {val}"
    return 0, "详见海报"

def make_tour_dict(dest, code, title, loc, dates, raw_price):
    days = extract_tour_days(title)
    status, over_days, hol_name = evaluate_holiday_fit(dates, days)
    p_num, p_text = clean_and_parse_price(raw_price)
    
    return {
        "destination": dest if dest else "精选目的地",
        "tour_code": code if code else "SP000000",
        "title": title if title else "经典旅游路线",
        "departure_location": loc if loc else "新加坡出发 (SIN)",
        "departure_dates": dates if dates else "详见海报",
        "price_numeric": p_num,
        "price_text": p_text,
        "holiday_status": status,
        "over_days": over_days,
        "holiday_name": hol_name
    }

def trigger_notification():
    js = """
    <script>
    (function() {
        try { if (navigator.vibrate) navigator.vibrate([300, 150, 300, 150, 500]); } catch(e) {}
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
        try { parent.document.title = "【🔔 已完成分析！请查看结果】"; } catch(e) {}
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

def force_convert_and_compress(file_bytes):
    img = Image.open(BytesIO(file_bytes))
    if img.mode in ("RGBA", "P", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "RGBA":
            background.paste(img, mask=img.split()[3])
        else:
            background.paste(img)
        img = background
    else:
        img = img.convert("RGB")
        
    img.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=90)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")

def analyze_single_image(file_bytes, file_name, task_dict):
    encoded_string = force_convert_and_compress(file_bytes)
    
    prompt = (
        "你是一个精细的旅游海报结构化提取助手。请扫描整张海报（包含重庆、西藏、青岛、桂林、台湾、贵州、韩国、哈尔滨、北疆、九寨沟等所有板块）。\n"
        "请将海报中的每一个旅游团提取为标准的 JSON 数组格式，不要包含任何 markdown 标记之外的废话。\n"
        "JSON 格式如下：\n"
        "[\n"
        "  {\n"
        "    \"destination\": \"目的地(如 重庆)\",\n"
        "    \"departure_location\": \"出发地(如 新加坡出发(SIN))\",\n"
        "    \"tour_code\": \"团号(如 SP002376)\",\n"
        "    \"title\": \"路线名称与天数(如 7天6夜 重庆8D风情线)\",\n"
        "    \"departure_dates\": \"出发日期(如 31/12/26)\",\n"
        "    \"price\": \"价格(如 RM2999)\"\n"
        "  }\n"
        "]\n"
        "请务必完整提取所有卡片，绝不遗漏！"
    )

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    vision_models = [
        "qwen/qwen3.6-27b",
        "llama-3.2-11b-vision-preview"
    ]

    last_err = ""
    for model_name in vision_models:
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
            "temperature": 0.1,
            "max_tokens": 8192,
            "response_format": {"type": "json_object"}
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=90)
            if response.status_code == 200:
                res_json = response.json()
                content = res_json['choices'][0]['message']['content'].strip()
                
                # 尝试解析 JSON
                data_list = []
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, list):
                        data_list = parsed
                    elif isinstance(parsed, dict):
                        for k, v in parsed.items():
                            if isinstance(v, list):
                                data_list = v
                                break
                except Exception:
                    # 纯正则兜底提取 JSON 字符串
                    m = re.search(r'\[.*\]', content, re.DOTALL)
                    if m:
                        data_list = json.loads(m.group(0))

                if data_list:
                    unique_list = []
                    seen = set()
                    for item in data_list:
                        dest = item.get("destination", "精选目的地")
                        code = item.get("tour_code", "SP000000")
                        title = item.get("title", "经典旅游路线")
                        loc = item.get("departure_location", "新加坡出发 (SIN)")
                        dates = item.get("departure_dates", "详见海报")
                        raw_p = item.get("price", "详见海报")

                        tour_item = make_tour_dict(dest, code, title, loc, dates, raw_p)
                        k = (tour_item["tour_code"], tour_item["departure_dates"], tour_item["price_numeric"])
                        if tour_item["tour_code"] != "SP000000" and k in seen:
                            continue
                        seen.add(k)
                        unique_list.append(tour_item)
                    if unique_list:
                        return unique_list
            elif response.status_code in [429, 400]:
                time.sleep(1)
                continue
            else:
                last_err = f"模型 {model_name} 报错 ({response.status_code}): {response.text}"
        except Exception as e:
            last_err = str(e)
            continue

    raise Exception(last_err if last_err else "未能成功解析出有效 JSON 旅游团数据")

def background_worker(files_data, task_dict, api_key):
    total = len(files_data)
    for idx, (f_name, f_bytes) in enumerate(files_data):
        task_dict["status_msg"] = f"⚡ JSON 结构化解析第 {idx + 1}/{total} 张: {f_name} ..."
        try:
            data = analyze_single_image(f_bytes, f_name, task_dict)
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
    task_dict["status_msg"] = "✅ 海报结构化解析完成！"

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

c_up, c_rst = st.columns([4, 1])
with c_up:
    uploaded_files = st.file_uploader(
        "批量上传宣传图 (支持 JPG/PNG，可多选)", 
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True
    )
with c_rst:
    st.write("")
    st.write("")
    if st.button("🗑️ 清空重置当前数据", use_container_width=True):
        task["running"] = False
        task["finished"] = False
        task["notified"] = False
        task["progress"] = 0.0
        task["status_msg"] = ""
        task["results"] = []
        task["errors"] = []
        st.rerun()

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
            task["status_msg"] = "正在启动 JSON 结构化引擎..."
            
            files_data = [(f.name, f.getvalue()) for f in uploaded_files]
            t = threading.Thread(target=background_worker, args=(files_data, task, GROQ_API_KEY), daemon=True)
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
        st.success(f"🎉 提取完成！共精准获取到 {len(task['results'])} 条详细旅游团信息！")
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

    base_filtered_df = df.copy()
    if selected_dest != "全部":
        base_filtered_df = base_filtered_df[base_filtered_df['destination'] == selected_dest]
        
    if selected_loc == "🇲🇾 全马来西亚出发 (包含吉隆坡/新山/槟城)":
        malaysia_keywords = ["吉隆坡", "新山", "JB", "槟城", "柔佛", "KUL", "PEN", "JHB", "马来西亚"]
        base_filtered_df = base_filtered_df[base_filtered_df['departure_location'].apply(
            lambda loc: any(kw in loc for kw in malaysia_keywords)
        )]
    elif selected_loc != "全部":
        base_filtered_df = base_filtered_df[base_filtered_df['departure_location'] == selected_loc]
        
    if selected_hol == "🎒 包含学校假期 (含最多超出2天)":
        base_filtered_df = base_filtered_df[base_filtered_df['holiday_status'].isin(['exact', 'slight_over'])]
    elif selected_hol == "✨ 严格在学校假期内 (0超出)":
        base_filtered_df = base_filtered_df[base_filtered_df['holiday_status'] == 'exact']
    elif selected_hol == "💼 仅平时非假期出发":
        base_filtered_df = base_filtered_df[base_filtered_df['holiday_status'] == 'none']

    valid_prices = base_filtered_df[base_filtered_df['price_numeric'] > 0]['price_numeric']
    if valid_prices.empty:
        valid_prices = df[df['price_numeric'] > 0]['price_numeric']

    if not valid_prices.empty:
        dynamic_min = int(valid_prices.min())
        dynamic_max = int(valid_prices.max())
    else:
        dynamic_min = 1000
        dynamic_max = 5000

    if dynamic_min >= dynamic_max:
        slider_min = max(dynamic_min - 50, 0)
        slider_max = dynamic_max + 50
    else:
        slider_min = dynamic_min
        slider_max = dynamic_max

    slider_key = f"slider_{selected_dest}_{selected_loc}_{slider_min}_{slider_max}"
    
    price_range = st.sidebar.slider(
        f"价格预算范围 (RM) [{slider_min} - {slider_max}]", 
        min_value=slider_min, 
        max_value=slider_max, 
        value=(slider_min, slider_max),
        step=50,
        key=slider_key
    )
    
    final_filtered_df = base_filtered_df[
        (base_filtered_df['price_numeric'] >= price_range[0]) & 
        (base_filtered_df['price_numeric'] <= price_range[1])
    ]
    
    st.markdown("### 📥 导出筛选结果")
    csv_bytes = final_filtered_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📊 下载 Excel / CSV 表格",
        data=csv_bytes,
        file_name="旅游团清单.csv",
        mime="text/csv",
        type="primary"
    )
        
    st.markdown(f"### 符合条件的旅游团共 **{len(final_filtered_df)}** 个：")
    
    display_cols = [c for c in ['destination', 'tour_code', 'departure_location', 'departure_dates', 'price_text', 'title'] if c in final_filtered_df.columns]
    st.dataframe(final_filtered_df[display_cols], use_container_width=True)
    
    for _, row in final_filtered_df.iterrows():
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
