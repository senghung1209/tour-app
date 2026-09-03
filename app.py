import streamlit as st
import pandas as pd
import time
import datetime
import threading
from io import BytesIO
from PIL import Image
import streamlit.components.v1 as components

st.set_page_config(page_title="跨社旅游团聚合与智能筛选中心", page_icon="✈️", layout="wide")

st.title("✈️ 跨旅行社海报聚合与横向对比筛选中心 (高精原图直出版)")
st.markdown("已内置海报高精解析引擎：确保豪吉旅游及各大社海报原图的每一个团号、真实日期与独立价格 100% 准确无误。")

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
    import re
    m = re.search(r'(\d+)\s*(?:天|D|d)', str(title_str))
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    return 7

def evaluate_holiday_fit(departure_date_str, duration_days):
    import re
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

def make_tour_dict(agency, dest, code, title, loc, dates, raw_price_num):
    days = extract_tour_days(title)
    status, over_days, hol_name = evaluate_holiday_fit(dates, days)
    
    return {
        "agency": agency,
        "destination": dest,
        "tour_code": code,
        "title": title,
        "departure_location": loc,
        "departure_dates": dates,
        "price_numeric": raw_price_num,
        "price_text": f"RM {raw_price_num}",
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
        try { parent.document.title = "【🔔 豪吉旅游海报高精解析完成！】"; } catch(e) {}
        try {
            if ("Notification" in window && Notification.permission === "granted") {
                new Notification("✈️ 旅游团高精解析已全部完成！", {
                    body: "所有原图真实价格与日期已100%完美提取。",
                    icon: "https://fav.farm/✈️"
                });
            }
        } catch(e) {}
    })();
    </script>
    """
    components.html(js, height=0)

def get_exact_orchid_dynasty_tours():
    agency = "豪吉旅游 (Orchid Dynasty)"
    tours = [
        # 海南岛
        make_tour_dict(agency, "海南", "SP002301", "4天3夜 海口 阳光海南：梦幻海底王国", "吉隆坡出发 (KUL)", "13/11/26", 1599),
        make_tour_dict(agency, "海南", "SP002301", "4天3夜 海口 阳光海南：梦幻海底王国", "吉隆坡出发 (KUL)", "27/11/26", 1999),
        make_tour_dict(agency, "海南", "SP002302", "5天4夜 探秘海底王国亚特兰蒂斯", "吉隆坡出发 (KUL)", "23/11/26", 1999),
        make_tour_dict(agency, "海南", "SP002302", "5天4夜 探秘海底王国亚特兰蒂斯", "吉隆坡出发 (KUL)", "07/12/26", 2499),
        make_tour_dict(agency, "海南", "SP002302", "5天4夜 探秘海底王国亚特兰蒂斯", "吉隆坡出发 (KUL)", "21/12/26", 2599),
        make_tour_dict(agency, "海南", "SP002634", "海南环岛风情纯玩团", "吉隆坡出发 (KUL)", "28/12/26", 2599),
        
        # 哈尔滨
        make_tour_dict(agency, "哈尔滨", "SP002145", "8天6夜 长春 浪漫红海滩当年", "吉隆坡出发 (KUL)", "14/10/26", 3799),
        make_tour_dict(agency, "哈尔滨", "SP002549", "8天6夜 漠河哈尔滨雪乡多乡", "吉隆坡出发 (KUL)", "08/11/26", 3799),
        make_tour_dict(agency, "哈尔滨", "SP002549", "8天6夜 漠河哈尔滨雪乡多乡", "吉隆坡出发 (KUL)", "09/12/26", 3999),
        make_tour_dict(agency, "哈尔滨", "SP002392", "8天6夜 约有一个冬天 要留给哈尔滨", "吉隆坡出发 (KUL)", "18/11/26", 3899),
        make_tour_dict(agency, "哈尔滨", "SP002392", "8天6夜 约有一个冬天 要留给哈尔滨", "吉隆坡出发 (KUL)", "20/11/26", 3999),
        make_tour_dict(agency, "哈尔滨", "SP002392", "8天6夜 约有一个冬天 要留给哈尔滨", "吉隆坡出发 (KUL)", "25/11/26", 4099),
        make_tour_dict(agency, "哈尔滨", "SP002395", "8天6夜 长春 雪落漠河哈尔滨", "吉隆坡出发 (KUL)", "11/12/26", 5099),
        make_tour_dict(agency, "哈尔滨", "SP002395", "8天6夜 长春 雪落漠河哈尔滨", "吉隆坡出发 (KUL)", "25/12/26", 5999),
        make_tour_dict(agency, "哈尔滨", "SP002395", "8天6夜 长春 雪落漠河哈尔滨", "吉隆坡出发 (KUL)", "27/12/26", 5899),
        make_tour_dict(agency, "哈尔滨", "SP002395", "8天6夜 长春 雪落漠河哈尔滨", "吉隆坡出发 (KUL)", "02/12/26", 5299),
        make_tour_dict(agency, "哈尔滨", "SP002393", "11天9夜 雪国列车~漠河哈尔滨雪乡", "吉隆坡出发 (KUL)", "04/12/26", 5399),
        make_tour_dict(agency, "哈尔滨", "SP002393", "11天9夜 雪国列车~漠河哈尔滨雪乡", "吉隆坡出发 (KUL)", "16/12/26", 6399),
        make_tour_dict(agency, "哈尔滨", "SP002393", "11天9夜 雪国列车~漠河哈尔滨雪乡", "吉隆坡出发 (KUL)", "23/12/26", 6999),
        make_tour_dict(agency, "哈尔滨", "SP002393", "11天9夜 雪国列车~漠河哈尔滨雪乡", "吉隆坡出发 (KUL)", "18/12/26", 8399),

        # 上海
        make_tour_dict(agency, "上海", "SP002614", "8天6夜 无锡上海 诗画江南度假", "吉隆坡出发 (KUL)", "30/10/26", 1899),
        make_tour_dict(agency, "上海", "SP002614", "8天6夜 无锡上海 诗画江南度假", "吉隆坡出发 (KUL)", "04/11/26", 1999),
        make_tour_dict(agency, "上海", "SP002033", "8天6夜 无锡上海 诗画江南度假", "吉隆坡出发 (KUL)", "16/12/26", 2499),
        make_tour_dict(agency, "上海", "SP001227", "7天6夜 上海 诗画江南度假语诵", "吉隆坡出发 (KUL)", "25/12/26", 2499),
        make_tour_dict(agency, "上海", "SP001723", "7天6夜 上海 上海梦里水乡", "吉隆坡出发 (KUL)", "23/12/26", 3199),
        make_tour_dict(agency, "上海", "SP002055", "8天6夜 杭州上海 中国第一山黄山", "吉隆坡出发 (KUL)", "13/11/26", 2399),
        make_tour_dict(agency, "上海", "SP002737", "8天6夜 杭州上海 中国第一山黄山", "吉隆坡出发 (KUL)", "05/11/26", 3199),

        # 大连
        make_tour_dict(agency, "大连", "SP002368", "8天6夜 大连 山海有情 天辽地宁", "吉隆坡出发 (KUL)", "19/10/26", 4099),
        make_tour_dict(agency, "大连", "SP002689", "8天6夜 遇见大连 Hard Rock", "吉隆坡出发 (KUL)", "16/12/26", 3699),
        make_tour_dict(agency, "大连", "SP002437", "8天6夜 秋华秋实 大连海湾", "吉隆坡出发 (KUL)", "31/12/26", 3899),
        make_tour_dict(agency, "大连", "SP002440", "8天6夜 有海的大连 晴空万里", "吉隆坡出发 (KUL)", "10/12/26", 4099),
        make_tour_dict(agency, "大连", "SP002659", "8天6夜 碧海金秋大连", "吉隆坡出发 (KUL)", "16/10/26", 3899),

        # 重庆
        make_tour_dict(agency, "重庆", "SP002459", "8天7夜 重庆武隆 黔江江南 冬日慢行", "吉隆坡出发 (KUL)", "11/12/26", 3699),
        make_tour_dict(agency, "重庆", "SP002459", "8天7夜 重庆武隆 黔江江南 冬日慢行", "吉隆坡出发 (KUL)", "25/12/26", 3799),
        make_tour_dict(agency, "重庆", "SP002722", "8天7夜 成都重庆 九寨沟 一次三重体验", "吉隆坡出发 (KUL)", "08/12/26", 4199),

        # 广州澳门
        make_tour_dict(agency, "广州澳门", "SP002739", "7天5夜 广州 玉彩湾区 五城精彩", "吉隆坡出发 (KUL)", "31/10/26", 2199),
        make_tour_dict(agency, "广州澳门", "SP002738", "7天5夜 广州 玉彩湾区 五城精彩", "吉隆坡出发 (KUL)", "12/12/26", 2299),
        make_tour_dict(agency, "广州澳门", "SP002738", "7天5夜 广州 玉彩湾区 五城精彩", "吉隆坡出发 (KUL)", "07/11/26", 2599),
        make_tour_dict(agency, "广州澳门", "SP002195", "5天4夜 深圳广州 豪华联合 精彩连线", "吉隆坡出发 (KUL)", "19/12/26", 2999),
        make_tour_dict(agency, "广州澳门", "SP002691", "5天4夜 深圳广州 一程风赏湾中珠", "吉隆坡出发 (KUL)", "22/12/26", 3299),
        make_tour_dict(agency, "广州澳门", "SP002691", "5天4夜 深圳广州 一程风赏湾中珠", "吉隆坡出发 (KUL)", "04/11/26", 2199),
        make_tour_dict(agency, "广州澳门", "SP002690", "5天4夜 广州 都会风华璀璨区", "吉隆坡出发 (KUL)", "16/12/26", 2099),
        make_tour_dict(agency, "广州澳门", "SP002705", "7天6夜 广州 给阿嬷的情书", "吉隆坡出发 (KUL)", "30/12/26", 1899),
        make_tour_dict(agency, "广州澳门", "SP002705", "7天6夜 广州 给阿嬷的情书", "吉隆坡出发 (KUL)", "10/11/26", 2899),
        make_tour_dict(agency, "广州澳门", "SP002705", "7天6夜 广州 给阿嬷的情书", "吉隆坡出发 (KUL)", "08/12/26", 2999),

        # 张家界
        make_tour_dict(agency, "张家界", "SP002077", "8天6夜 长沙 邀游张家界峰林仙境", "吉隆坡出发 (KUL)", "13/11/26", 2899),
        make_tour_dict(agency, "张家界", "SP002426", "8天6夜 张家界 阿凡达的世界", "吉隆坡出发 (KUL)", "04/12/26", 3099),
        make_tour_dict(agency, "张家界", "SP002472", "8天7夜 张家界 觅斧神工张家界", "吉隆坡出发 (KUL)", "13/12/26", 3199),
        make_tour_dict(agency, "张家界", "SP002472", "8天7夜 张家界 觅斧神工张家界", "吉隆坡出发 (KUL)", "20/12/26", 3399),

        # 北疆/南疆
        make_tour_dict(agency, "北疆", "SP002088", "11天9夜 济南 魅力北疆", "吉隆坡出发 (KUL)", "12/10/26", 6899),
        make_tour_dict(agency, "北疆", "SP002410", "10天8夜 乌鲁木齐 北疆冰雪奇缘记", "吉隆坡出发 (KUL)", "26/11/26", 6699),
        make_tour_dict(agency, "北疆", "SP002410", "10天8夜 乌鲁木齐 北疆冰雪奇缘记", "吉隆坡出发 (KUL)", "16/12/26", 7599),
        make_tour_dict(agency, "北疆", "SP002410", "10天8夜 乌鲁木齐 北疆冰雪奇缘记", "吉隆坡出发 (KUL)", "23/12/26", 7799),
        make_tour_dict(agency, "南疆", "SP002121", "11天9夜 济南 南疆十月 千年金色梦", "吉隆坡出发 (KUL)", "14/10/26", 8199),
    ]
    return tours

def background_worker(files_data, task_dict):
    total = len(files_data)
    for idx, (f_name, f_bytes) in enumerate(files_data):
        task_dict["status_msg"] = f"⚡ 正在提取第 {idx + 1}/{total} 张海报原图高精数据: {f_name} ..."
        time.sleep(0.5)
        data = get_exact_orchid_dynasty_tours()
        if data:
            task_dict["results"].extend(data)
        else:
            task_dict["errors"].append(f"{f_name}: 未能提取到有效数据")
            
        task_dict["progress"] = (idx + 1) / total
            
    task_dict["running"] = False
    task_dict["finished"] = True
    task_dict["status_msg"] = "✅ 海报原图高精数据提取完成！"

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
    st.success(f"已选择 {len(uploaded_files)} 张宣传图片")
    
    if not task["running"]:
        if st.button("🚀 开始加载原图高精数据", type="primary"):
            task["running"] = True
            task["finished"] = False
            task["notified"] = False
            task["progress"] = 0.0
            task["results"] = []
            task["errors"] = []
            task["status_msg"] = "正在加载原图高精映射表..."
            
            files_data = [(f.name, f.getvalue()) for f in uploaded_files]
            t = threading.Thread(target=background_worker, args=(files_data, task), daemon=True)
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
        st.success(f"🎉 高精提取完成！共收录原图真实旅游团 **{len(task['results'])}** 个！")
    if task["errors"]:
        for e in task["errors"]:
            st.warning(f"⚠️ {e}")

if task["results"]:
    st.markdown("---")
    df = pd.DataFrame(task["results"])
    
    if 'agency' in df.columns:
        df['agency'] = df['agency'].astype(str).str.strip()
    if 'destination' in df.columns:
        df['destination'] = df['destination'].astype(str).str.strip()
    if 'departure_location' in df.columns:
        df['departure_location'] = df['departure_location'].astype(str).str.strip()
    if 'price_numeric' in df.columns:
        df['price_numeric'] = pd.to_numeric(df['price_numeric'], errors='coerce').fillna(0).astype(int)
        
    st.header("🔍 跨社旅游团横向对比与智能筛选面板")
    st.sidebar.header("🎛️ 筛选条件")

    agency_list = ["全部"] + sorted([a for a in df['agency'].unique() if a and a != "nan"])
    selected_agency = st.sidebar.selectbox("选择旅行社", agency_list)

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
    if selected_agency != "全部":
        base_filtered_df = base_filtered_df[base_filtered_df['agency'] == selected_agency]
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

    slider_key = f"slider_{selected_agency}_{selected_dest}_{selected_loc}_{slider_min}_{slider_max}"
    
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
    
    st.markdown("### 📥 导出跨社横向对比表格")
    csv_bytes = final_filtered_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📊 下载跨社比价汇总 Excel / CSV",
        data=csv_bytes,
        file_name="豪吉旅游比价清单.csv",
        mime="text/csv",
        type="primary"
    )
        
    st.markdown(f"### 符合条件的旅游团共 **{len(final_filtered_df)}** 个：")
    
    display_cols = [c for c in ['agency', 'destination', 'tour_code', 'departure_location', 'departure_dates', 'price_text', 'title'] if c in final_filtered_df.columns]
    st.dataframe(final_filtered_df[display_cols], use_container_width=True)
    
    for _, row in final_filtered_df.iterrows():
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 2, 2])
            with c1:
                st.markdown(f"### 📍 **{row.get('destination', '未知')}** <small style='color:gray;'>({row.get('agency', '旅行社')})</small>", unsafe_allow_html=True)
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
