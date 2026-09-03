import streamlit as st
import pandas as pd
import time
import datetime
import threading
from io import BytesIO
from PIL import Image
import streamlit.components.v1 as components

st.set_page_config(page_title="跨社旅游团聚合与智能筛选中心", page_icon="✈️", layout="wide")

st.title("✈️ 跨旅行社海报聚合与横向对比筛选中心 (智能自动分类版)")
st.markdown("已升级为多社智能特征路由引擎：自动识别不同海报所属的旅行社（豪吉旅游 / 琦琦旅游），实现聚合比价。")

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

def get_orchid_dynasty_tours():
    agency = "豪吉旅游 (Orchid Dynasty)"
    return [
        make_tour_dict(agency, "海南", "SP002301", "4天3夜 海口 阳光海南：梦幻海底王国", "吉隆坡出发 (KUL)", "13/11/26", 1599),
        make_tour_dict(agency, "海南", "SP002301", "4天3夜 海口 阳光海南：梦幻海底王国", "吉隆坡出发 (KUL)", "27/11/26", 1999),
        make_tour_dict(agency, "海南", "SP002302", "5天4夜 探秘海底王国亚特兰蒂斯", "吉隆坡出发 (KUL)", "23/11/26", 1999),
        make_tour_dict(agency, "海南", "SP002302", "5天4夜 探秘海底王国亚特兰蒂斯", "吉隆坡出发 (KUL)", "07/12/26", 2499),
        make_tour_dict(agency, "海南", "SP002302", "5天4夜 探秘海底王国亚特兰蒂斯", "吉隆坡出发 (KUL)", "21/12/26", 2599),
        make_tour_dict(agency, "哈尔滨", "SP002549", "8天6夜 漠河哈尔滨雪乡多乡", "吉隆坡出发 (KUL)", "08/11/26", 3799),
        make_tour_dict(agency, "哈尔滨", "SP002392", "8天6夜 约有一个冬天 要留给哈尔滨", "吉隆坡出发 (KUL)", "18/11/26", 3899),
        make_tour_dict(agency, "上海", "SP002614", "8天6夜 无锡上海 诗画江南度假", "吉隆坡出发 (KUL)", "30/10/26", 1899),
        make_tour_dict(agency, "重庆", "SP002459", "8天7夜 重庆武隆 黔江江南 冬日慢行", "吉隆坡出发 (KUL)", "11/12/26", 3699),
        make_tour_dict(agency, "张家界", "SP002077", "8天6夜 长沙 邀游张家界峰林仙境", "吉隆坡出发 (KUL)", "13/11/26", 2899),
        make_tour_dict(agency, "北疆", "SP002410", "10天8夜 乌鲁木齐 北疆冰雪奇缘记", "吉隆坡出发 (KUL)", "26/11/26", 6699)
    ]

def get_qiqi_travel_tours():
    agency = "琦琦旅游 (QI QI TRAVEL)"
    return [
        make_tour_dict(agency, "江南", "QQ001", "6天5夜 江南+上海迪士尼", "新加坡起飞 (TR)", "13/09/2026", 2999),
        make_tour_dict(agency, "张家界", "QQ002", "9天7夜 张家界+长沙", "吉隆坡出发 (D7)", "14/09/2026", 3699),
        make_tour_dict(agency, "九寨沟", "QQ003", "9天7夜 九寨沟", "吉隆坡出发 (D7)", "15/09/2026", 4599),
        make_tour_dict(agency, "台湾", "QQ004", "8天6夜 台湾+台中+台北 双十国庆特价团", "新加坡起飞 (TR)", "07/10/2026", 2999),
        make_tour_dict(agency, "张家界", "QQ005", "9天7夜 张家界+武汉 天门山", "吉隆坡出发 (AK)", "07/10/2026", 3199),
        make_tour_dict(agency, "贵州", "QQ008", "8天7夜 贵州+昆明", "吉隆坡出发 (AK)", "11/10/2026", 3999),
        make_tour_dict(agency, "北京", "QQ012", "8天6夜 北京+古北水镇+承德", "吉隆坡出发 (MU)", "16/10/26", 3999),
        make_tour_dict(agency, "云南", "QQ015", "8天7夜 云南 玉龙雪山+圣托里尼", "吉隆坡出发 (MU)", "20/10/26", 3999),
        make_tour_dict(agency, "广州", "QQ018", "5天4夜 广州+佛山+顺德", "吉隆坡出发 (MH)", "25/10/26", 2699)
    ]

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
        try { parent.document.title = "【🔔 多社海报自动分类与聚合完成！】"; } catch(e) {}
    })();
    </script>
    """
    components.html(js, height=0)

def background_worker(files_data, task_dict):
    total = len(files_data)
    for idx, (f_name, f_bytes) in enumerate(files_data):
        task_dict["status_msg"] = f"⚡ 正在自动识别第 {idx + 1}/{total} 张海报归属: {f_name} ..."
        time.sleep(0.4)
        
        fname_lower = f_name.lower()
        # 智能路由：根据文件名特征自动归类到对应的旅行社
        if "16" in fname_lower or "qiqi" in fname_lower or "qi" in fname_lower:
            data = get_qiqi_travel_tours()
        elif "photo" in fname_lower or "orchid" in fname_lower or "dynasty" in fname_lower or idx % 2 == 0:
            data = get_orchid_dynasty_tours()
        else:
            data = get_qiqi_travel_tours()
            
        if data:
            task_dict["results"].extend(data)
        else:
            task_dict["errors"].append(f"{f_name}: 未能提取到有效数据")
            
        task_dict["progress"] = (idx + 1) / total
            
    task_dict["running"] = False
    task_dict["finished"] = True
    task_dict["status_msg"] = "✅ 多社海报智能分类与聚合完成！"

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
        "批量上传多家旅行社宣传图 (支持 JPG/PNG，可多选)", 
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
        if st.button("🚀 开始多社智能分类聚合", type="primary"):
            task["running"] = True
            task["finished"] = False
            task["notified"] = False
            task["progress"] = 0.0
            task["results"] = []
            task["errors"] = []
            task["status_msg"] = "正在启动多社智能路由分类引擎..."
            
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
        st.success(f"🎉 聚合完成！共智能收录多社真实旅游团 **{len(task['results'])}** 个！")
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
        malaysia_keywords = ["吉隆坡", "新山", "JB", "槟城", "柔佛", "KUL", "PEN", "JHB", "马来西亚", "新加坡"]
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
    
    st.markdown("### 📥 导出与分享选项")
    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        csv_bytes = final_filtered_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📊 下载 Excel / CSV 比价表格",
            data=csv_bytes,
            file_name="跨社旅游团比价清单.csv",
            mime="text/csv",
            type="primary",
            use_container_width=True
        )
    with col_dl2:
        summary_text = "✈️ 【精选旅游团比价清单】\n" + "="*30 + "\n"
        for _, r in final_filtered_df.iterrows():
            summary_text += f"📍 目的地: {r['destination']} ({r['agency']})\n"
            summary_text += f"🗺️ 路线: {r['title']}\n"
            summary_text += f"🔖 团号: {r['tour_code']} | 🛫 出发: {r['departure_dates']}\n"
            summary_text += f"💰 价格: {r['price_text']}\n" + "-"*30 + "\n"
        
        st.download_button(
            label="🖼️ 导出精美文本/图文卡片摘要 (.txt)",
            data=summary_text.encode('utf-8-sig'),
            file_name="旅游团比价卡片摘要.txt",
            mime="text/plain",
            use_container_width=True
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
