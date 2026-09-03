import streamlit as st
import pandas as pd
import datetime
import re
import os
import json
import threading
import time
import urllib.request
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import streamlit.components.v1 as components

st.set_page_config(page_title="跨社旅游团比价筛选中心", page_icon="✈️", layout="wide")

DB_FILE = "tour_database.json"
TASK_STATUS_FILE = "task_status.json"

def load_persisted_data():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_persisted_data(data):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def get_task_status():
    if os.path.exists(TASK_STATUS_FILE):
        try:
            with open(TASK_STATUS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"running": False, "msg": "", "done_alert": False}
    return {"running": False, "msg": "", "done_alert": False}

def set_task_status(running, msg="", done_alert=False):
    try:
        with open(TASK_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump({"running": running, "msg": msg, "done_alert": done_alert}, f)
    except Exception:
        pass

if "tour_data" not in st.session_state:
    st.session_state.tour_data = load_persisted_data()

st.title("✈️ 跨旅行社海报聚合与横向对比中心")

# 醒目一键授权卡片
auth_card_html = """
<div style="background: #f0fdf4; border: 1.5px solid #22c55e; border-radius: 10px; padding: 12px; margin-bottom: 15px;">
    <div style="font-weight: bold; font-size: 15px; color: #15803d; margin-bottom: 5px;">
        🔔 后台挂机提醒设置
    </div>
    <div style="font-size: 13px; color: #166534; margin-bottom: 8px;">
        点击下方按钮激活手机提醒。上传海报点击提取后，可直接切出刷抖音或FB，全部解析完毕回来看即可！
    </div>
    <button id="auth_btn" style="background: #16a34a; color: white; border: none; padding: 9px 16px; border-radius: 6px; font-weight: bold; font-size: 14px; cursor: pointer; width: 100%;">
        👉 点击开启通知提醒与声音
    </button>
</div>

<script>
document.getElementById('auth_btn').addEventListener('click', function() {
    try {
        window.audioCtx = window.audioCtx || new (window.AudioContext || window.webkitAudioContext)();
        if (window.audioCtx.state === 'suspended') {
            window.audioCtx.resume();
        }
        const osc = window.audioCtx.createOscillator();
        const gain = window.audioCtx.createGain();
        osc.type = "sine";
        osc.frequency.setValueAtTime(587.33, window.audioCtx.currentTime);
        gain.gain.setValueAtTime(0.15, window.audioCtx.currentTime);
        osc.connect(gain);
        gain.connect(window.audioCtx.destination);
        osc.start();
        osc.stop(window.audioCtx.currentTime + 0.15);
    } catch(e) {}

    if ("Notification" in window) {
        Notification.requestPermission().then(function(perm) {
            alert("提示音已就绪！系统通知状态: " + perm);
        });
    } else {
        alert("提示音激活成功！");
    }
});
</script>
"""
components.html(auth_card_html, height=125)

def trigger_notification_js(title, message):
    js_code = f"""
    <script>
    (function() {{
        try {{
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const now = ctx.currentTime;
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = "triangle";
            osc.frequency.setValueAtTime(587.33, now);
            osc.frequency.setValueAtTime(880, now + 0.18);
            gain.gain.setValueAtTime(0.3, now);
            gain.gain.exponentialRampToValueAtTime(0.01, now + 0.7);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start(now);
            osc.stop(now + 0.7);
        }} catch(e) {{}}

        if ("Notification" in window && Notification.permission === "granted") {{
            new Notification("{title}", {{ body: "{message}", icon: "✈️" }});
        }}
    }})();
    </script>
    """
    components.html(js_code, height=0)

OFFICIAL_HOLIDAYS = [
    (datetime.date(2026, 3, 20), datetime.date(2026, 3, 29), "2026 第一学期假期 (3月)"),
    (datetime.date(2026, 5, 22), datetime.date(2026, 6, 7), "2026 年中假期 (5/6月)"),
    (datetime.date(2026, 8, 28), datetime.date(2026, 9, 6), "2026 第二学期假期 (8/9月)"),
    (datetime.date(2026, 12, 4), datetime.date(2027, 1, 3), "2026 学年末大假期 (12月)"),
    (datetime.date(2027, 1, 23), datetime.date(2027, 2, 16), "2027 农历新年与跨年假期")
]

RAW_KEY = st.secrets.get("GEMINI_API_KEY", "")
GEMINI_API_KEY = str(RAW_KEY).strip() if RAW_KEY else ""
PRIMARY_MODEL = "gemini-3.5-flash"
BACKUP_MODEL = "gemini-3.1-flash-lite"

def extract_tour_days(title_str):
    m = re.search(r'(\d+)\s*(?:天|D|d)', str(title_str))
    return int(m.group(1)) if m else 7

def evaluate_holiday_fit(departure_date_str, duration_days):
    matches = re.findall(r'(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?', str(departure_date_str))
    if not matches:
        return 'none', 0, ""

    d, mth, y = matches[0]
    d, mth = int(d), int(mth)
    y = int(y) + 2000 if y and int(y) < 100 else (int(y) if y else 2026)

    try:
        dep_date = datetime.date(y, mth, d)
        ret_date = dep_date + datetime.timedelta(days=max(duration_days - 1, 0))
        for h_start, h_end, h_name in OFFICIAL_HOLIDAYS:
            if dep_date >= h_start and ret_date <= h_end:
                return 'exact', 0, h_name
            if not (ret_date < h_start or dep_date > h_end):
                over = max((h_start - dep_date).days, 0) + max((ret_date - h_end).days, 0)
                if over <= 2:
                    return 'slight_over', over, h_name
    except Exception:
        pass
    return 'none', 0, ""

def normalize_departure_location(raw_loc, raw_title):
    s = f"{raw_loc} {raw_title}".upper()
    if any(k in s for k in ["SIN", "新加坡", "CHANGI", "SCOOT", "TR"]):
        return "🇸🇬 新加坡起飞 (SIN)"
    if any(k in s for k in ["JB", "新山"]):
        return "🇲🇾 新山出发 (JB)"
    return "🇲🇾 马来西亚起飞 (KUL)"

def split_and_explode_dates(raw_agency, raw_dest, raw_code, raw_title, raw_loc, raw_dates_str, raw_price):
    days = extract_tour_days(raw_title)
    try:
        clean_price = int(re.sub(r'[^\d]', '', str(raw_price)))
    except Exception:
        clean_price = 0

    norm_loc = normalize_departure_location(raw_loc, raw_title)
    
    # 支持形如 26/10, 28/10, 30/10 的批量日期提取
    date_tokens = re.findall(r'\b\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?\b', str(raw_dates_str))
    if not date_tokens:
        date_tokens = [str(raw_dates_str).strip()]

    exploded = []
    for d_token in date_tokens:
        status, over_days, hol_name = evaluate_holiday_fit(d_token, days)
        exploded.append({
            "agency": str(raw_agency or "精选旅行社"),
            "destination": str(raw_dest or "精选路线"),
            "tour_code": str(raw_code or "-"),
            "title": str(raw_title or ""),
            "departure_location": norm_loc,
            "departure_dates": str(d_token),
            "price_numeric": clean_price,
            "price_text": f"RM {clean_price}",
            "holiday_status": status,
            "over_days": over_days,
            "holiday_name": hol_name
        })
    return exploded

def parse_compact_lines(raw_text):
    clean_lines = raw_text.strip().splitlines()
    items = []
    for line in clean_lines:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("`") or "旅行社|目的地" in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 7:
            try:
                price_val = int(re.sub(r'[^\d]', '', parts[6]))
            except Exception:
                price_val = 0
            items.append({
                "agency": parts[0] or "精选旅行社",
                "destination": parts[1] or "精选目的地",
                "tour_code": parts[2] or "-",
                "title": parts[3] or "",
                "departure_location": parts[4] or "",
                "departure_dates": parts[5] or "",
                "price": price_val
            })
    return items

def call_gemini_vision_chunk(img_chunk, chunk_name, expected_blocks_hint):
    if not GEMINI_API_KEY:
        return []

    buf = BytesIO()
    img_chunk.save(buf, format="JPEG", quality=92)
    base64_data = base64.b64encode(buf.getvalue()).decode('utf-8')

    prompt = f"""
    你是一个高精度旅游海报视觉解析专家。正在扫描海报的【{chunk_name}】。
    请务必全量提取当前画面中的以下各个板块，一个团期都不允许漏掉！
    重点核对板块：{expected_blocks_hint}

    提取规则：
    1. 【每个日期拆单行】：一个小格子里若列有多个出发日（例如 26/10, 28/10 对应 2699，或者 12/10/26, 25/5/27 对应 6999），必须把每一个出发日单独拆成一行输出！
    2. 旅行社：若海报含 SP 编号或豪吉标志，统一写“豪吉旅游”；长表格按实际名称写。
    3. 起飞地点：含 SIN/新加坡/酷航 填“新加坡起飞 (SIN)”；含 JB/新山 填“新山出发 (JB)”；默认填“马来西亚起飞 (KUL)”。
    4. 输出格式：纯文本逐行输出，竖线 | 分隔，不要输出任何代码块标记与解释：
    旅行社|目的地|团号|行程路线全称|起飞地|出发日期|纯数字价格
    """

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": base64_data
                        }
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 8192
        }
    }

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }

    for model_name in [PRIMARY_MODEL, BACKUP_MODEL]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        for attempt in range(2):
            try:
                res = requests.post(url, headers=headers, json=payload, timeout=55)
                if res.status_code == 200:
                    res_json = res.json()
                    raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
                    return parse_compact_lines(raw_text)
                if res.status_code == 503:
                    time.sleep(2)
                    continue
                else:
                    break
            except requests.exceptions.Timeout:
                break
    return []

def background_worker(files_data):
    try:
        set_task_status(True, "🚀 服务器后台正在极速扫描...")
        newly_extracted = []

        for f_bytes in files_data:
            img = Image.open(BytesIO(f_bytes))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            w, h = img.size

            if h > w * 1.2:
                # 黄金切割比例：
                # 上半区切到 58%（完整包含 重庆、西藏、青岛、桂林、台湾、韩国）
                # 下半区从 46% 切到 100%（完整包含 韩国底部、贵州全部、哈尔滨全部、北疆全部、九寨沟全部）
                box_top = (0, 0, w, int(h * 0.58))
                box_bottom = (0, int(h * 0.46), w, h)

                set_task_status(True, "🔍 正在地毯式提取上半区 (重庆/西藏/青岛/桂林/台湾/韩国)...")
                hint_top = "必须提取：SIN-重庆(约12条)、SIN-西藏(约5条)、青岛(约3条)、SIN-桂林(约3条)、SIN-台湾(约6条)、SIN-韩国(约4条)"
                r1 = call_gemini_vision_chunk(img.crop(box_top), "上半区", hint_top)

                set_task_status(True, "🔍 正在地毯式提取下半区 (贵州/哈尔滨/北疆/九寨沟)...")
                hint_bottom = "必须提取：JB-贵州(约13条全部日期)、SIN-哈尔滨(约9条全部日期)、KL-北疆(约4条全部日期)、SIN-九寨沟(约2条全部日期)"
                r2 = call_gemini_vision_chunk(img.crop(box_bottom), "下半区", hint_bottom)

                raw_items = r1 + r2
            else:
                set_task_status(True, "🔍 正在全幅扫描长表海报...")
                raw_items = call_gemini_vision_chunk(img, "全图", "所有表格行")

            for item in raw_items:
                rows = split_and_explode_dates(
                    item.get("agency", "精选旅行社"),
                    item.get("destination", "精选路线"),
                    item.get("tour_code", "-"),
                    item.get("title", ""),
                    item.get("departure_location", ""),
                    item.get("departure_dates", ""),
                    item.get("price", 0)
                )
                newly_extracted.extend(rows)

        if newly_extracted:
            current_data = load_persisted_data()
            combined = current_data + newly_extracted
            seen = set()
            unique_combined = []
            for item in combined:
                marker = (item["agency"], item["title"], item["departure_dates"], item["price_numeric"])
                if marker not in seen:
                    seen.add(marker)
                    unique_combined.append(item)
            save_persisted_data(unique_combined)

        set_task_status(False, "FINISHED", done_alert=True)
    except Exception as e:
        set_task_status(False, f"ERROR: {e}")

task_info = get_task_status()
if task_info["running"]:
    st.warning(f"⚡ **后台任务运算中**：{task_info['msg']}")
    st.caption("你可以随意切去刷抖音/FB，服务器后台正在持续扫描！20~30秒后切回来即可。")
    time.sleep(3)
    st.rerun()

if task_info.get("done_alert", False):
    set_task_status(False, "", done_alert=False)
    trigger_notification_js("🎉 扫描成功完成！", "海报所有团期已提取入库。")
    st.balloons()
    st.success("🎉 恭喜！后台已完成全部扫描并写入总库！")

# 字体加载引擎
@st.cache_resource
def get_chinese_font(font_size=15):
    font_paths = [
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "wqy-microhei.ttc"
    ]
    for p in font_paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, font_size)
            except Exception:
                pass

    local_font = "wqy-microhei.ttc"
    if not os.path.exists(local_font):
        try:
            url = "https://github.com/anthonyfok/fonts-wqy-microhei/raw/master/wqy-microhei.ttc"
            urllib.request.urlretrieve(url, local_font)
            return ImageFont.truetype(local_font, font_size)
        except Exception:
            pass
    return ImageFont.load_default()

# 导出高清专业对比长图
def generate_comparison_image(df):
    w = 1000
    rh = 44
    hh = 80
    h = hh + (len(df) + 1) * rh + 40
    img = Image.new("RGB", (w, max(h, 250)), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    f_head = get_chinese_font(22)
    f_col = get_chinese_font(15)
    f_body = get_chinese_font(14)
    f_price = get_chinese_font(15)

    # 顶栏头部
    draw.rectangle([0, 0, w, hh], fill=(30, 41, 59))
    draw.text((30, 26), f"✈️ 跨旅行社旅游团比价汇总清单 (精选有效团期 {len(df)} 项)", fill=(255, 255, 255), font=f_head)

    # 表头
    y = hh + 12
    draw.rectangle([20, y, w - 20, y + 36], fill=(241, 245, 249))
    cols = [
        ("旅行社", 35),
        ("目的地", 160),
        ("团号", 250),
        ("起飞地", 360),
        ("出发日期", 500),
        ("团费价格", 610),
        ("行程路线全称", 730)
    ]
    for name, x in cols:
        draw.text((x, y + 8), name, fill=(71, 85, 105), font=f_col)

    y += 44
    for idx, r in df.iterrows():
        bg = (248, 250, 252) if idx % 2 == 0 else (255, 255, 255)
        draw.rectangle([20, y, w - 20, y + rh - 2], fill=bg)

        draw.text((35, y + 12), str(r['agency'])[:8], fill=(71, 85, 105), font=f_body)
        draw.text((160, y + 12), str(r['destination'])[:6], fill=(15, 23, 42), font=f_body)
        draw.text((250, y + 12), str(r['tour_code'])[:10], fill=(100, 116, 139), font=f_body)

        loc_txt = "🇸🇬 新加坡" if "SIN" in str(r['departure_location']) else ("🇲🇾 新山" if "JB" in str(r['departure_location']) else "🇲🇾 马来西亚")
        draw.text((360, y + 12), loc_txt, fill=(2, 132, 199), font=f_body)

        draw.text((500, y + 12), str(r['departure_dates'])[:12], fill=(15, 23, 42), font=f_body)
        draw.text((610, y + 11), str(r['price_text']), fill=(220, 38, 38), font=f_price)
        draw.text((730, y + 12), str(r['title'])[:16], fill=(71, 85, 105), font=f_body)

        y += rh

    buf = BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()

uploaded_files = st.file_uploader("📷 上传旅行社海报图片 (已支持后台脱机托管，可自由切出网页)", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

if uploaded_files:
    st.info(f"已选择 {len(uploaded_files)} 张海报图片")
    if st.button("🚀 启动后台全量提取 (点完直接切走刷抖音/FB)", type="primary", use_container_width=True):
        files_data = [f.getvalue() for f in uploaded_files]
        t = threading.Thread(target=background_worker, args=(files_data,), daemon=True)
        t.start()
        st.rerun()

st.session_state.tour_data = load_persisted_data()

if st.session_state.tour_data:
    if st.button("🗑️ 清空总库全部数据 (永久重置)", use_container_width=True):
        save_persisted_data([])
        st.session_state.tour_data = []
        st.rerun()

    st.markdown("---")
    df = pd.DataFrame(st.session_state.tour_data)
    df['price_numeric'] = pd.to_numeric(df['price_numeric'], errors='coerce').fillna(0).astype(int)

    with st.expander(f"🛠️ 快速数据校对面板 (当前总库共有 {len(df)} 项，支持修改/增删行)", expanded=False):
        edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)
        if not edited_df.equals(df):
            st.session_state.tour_data = edited_df.to_dict('records')
            save_persisted_data(st.session_state.tour_data)
            st.rerun()

    st.sidebar.header("🎛️ 筛选条件")
    clean_agencies = sorted(list({str(a) for a in df['agency'] if pd.notna(a) and str(a).strip()}))
    selected_agency = st.sidebar.selectbox("选择旅行社", ["全部"] + clean_agencies)

    clean_dests = sorted(list({str(d) for d in df['destination'] if pd.notna(d) and str(d).strip()}))
    selected_dest = st.sidebar.selectbox("选择目的地", ["全部"] + clean_dests)

    loc_options = ["全部", "🇸🇬 新加坡起飞 (SIN)", "🇲🇾 新山出发 (JB)", "🇲🇾 马来西亚起飞 (KUL)"]
    selected_loc = st.sidebar.selectbox("选择起飞地点", loc_options)

    selected_hol = st.sidebar.selectbox("🗓️ 学校假期筛选", ["全部日期", "🎒 包含学校假期 (含超出2天内)", "✨ 严格在学校假期内 (0超出)", "💼 仅平时非假期"])

    filtered_df = df.copy()
    if selected_agency != "全部":
        filtered_df = filtered_df[filtered_df['agency'] == selected_agency]
    if selected_dest != "全部":
        filtered_df = filtered_df[filtered_df['destination'] == selected_dest]
    if selected_loc != "全部":
        filtered_df = filtered_df[filtered_df['departure_location'] == selected_loc]

    if selected_hol == "🎒 包含学校假期 (含超出2天内)":
        filtered_df = filtered_df[filtered_df['holiday_status'].isin(['exact', 'slight_over'])]
    elif selected_hol == "✨ 严格在学校假期内 (0超出)":
        filtered_df = filtered_df[filtered_df['holiday_status'] == 'exact']
    elif selected_hol == "💼 仅平时非假期":
        filtered_df = filtered_df[filtered_df['holiday_status'] == 'none']

    p_min = int(df['price_numeric'].min()) if not df.empty else 1000
    p_max = int(df['price_numeric'].max()) if not df.empty else 9000
    if p_min >= p_max:
        p_max = p_min + 100
    price_range = st.sidebar.slider("💰 团费预算范围 (RM)", min_value=p_min, max_value=p_max, value=(p_min, p_max), step=100)
    filtered_df = filtered_df[(filtered_df['price_numeric'] >= price_range[0]) & (filtered_df['price_numeric'] <= price_range[1])]

    st.markdown(f"### 符合条件的出发选项共 **{len(filtered_df)}** 个：")
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("📊 下载 CSV 比价清单", data=filtered_df.to_csv(index=False).encode('utf-8-sig'), file_name="智能比价清单.csv", mime="text/csv", use_container_width=True)
    with col2:
        st.download_button("🖼️ 下载高清长图 (.png)", data=generate_comparison_image(filtered_df), file_name="智能比价长图.png", mime="image/png", use_container_width=True)

    st.dataframe(filtered_df[['agency', 'destination', 'tour_code', 'departure_location', 'departure_dates', 'price_text', 'title']], use_container_width=True)

    st.markdown("#### 📋 行程比对卡片")
    for _, row in filtered_df.iterrows():
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 2, 2])
            with c1:
                st.markdown(f"### 📍 **{row['destination']}** <small style='color:gray;'>({row['agency']})</small>", unsafe_allow_html=True)
                st.write(f"**路线：** {row['title']}")
                st.write(f"**团号：** `{row['tour_code']}`")
            with c2:
                st.markdown(f"🛫 **出发地：** `{row['departure_location']}`")
                st.write(f"📅 **出发日期：** {row['departure_dates']}")
                h_stat = row['holiday_status']
                if h_stat == 'exact':
                    st.success(f"🎒 完美在校假内 ({row['holiday_name']})")
                elif h_stat == 'slight_over':
                    st.warning(f"⚠️ 包含校假，超 {row['over_days']} 天 (需请假)")
            with c3:
                st.markdown(f"### 💰 **{row['price_text']}**")
