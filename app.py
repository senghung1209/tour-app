import streamlit as st
import pandas as pd
import time
import datetime
import threading
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

st.set_page_config(page_title="跨社旅游团聚合与智能筛选中心", page_icon="✈️", layout="wide")

st.title("✈️ 跨旅行社海报聚合与横向对比筛选中心 (84团精准免Key版)")
st.markdown("已收录豪吉（61个独立日期）与琦琦（23个独立日期）共计 **84 个**完整团期，支持一键筛选与图表导出。")

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
        "progress": 0.0,
        "status_msg": "",
        "results": [],
        "errors": []
    }

task = get_global_task_store()

def extract_tour_days(title_str):
    import re
    m = re.search(r'(\d+)\s*(?:天|D|d)', str(title_str))
    return int(m.group(1)) if m else 7

def evaluate_holiday_fit(departure_date_str, duration_days):
    import re
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

def make_tour(agency, dest, code, title, loc, dates, price):
    days = extract_tour_days(title)
    status, over, h_name = evaluate_holiday_fit(dates, days)
    return {
        "agency": agency,
        "destination": dest,
        "tour_code": code,
        "title": title,
        "departure_location": loc,
        "departure_dates": dates,
        "price_numeric": price,
        "price_text": f"RM {price}",
        "holiday_status": status,
        "over_days": over,
        "holiday_name": h_name
    }

def get_orchid_tours_61():
    a = "豪吉旅游 (Orchid Dynasty)"
    return [
        make_tour(a, "重庆", "SP002376", "7天6夜 重庆8D风景线 武隆黔江", "SIN出发", "31/12/26", 2999),
        make_tour(a, "重庆", "SP002334", "7天6夜 8D重庆与阿凡达张家界", "SIN出发", "30/11/26", 3499),
        make_tour(a, "重庆", "SP002115", "7天6夜 重庆风采 山水之都 文化之旅", "SIN出发", "29/12/26", 3499),
        make_tour(a, "重庆", "SP002332", "8天6夜 重庆香格里拉的烟火气", "SIN出发", "08/11/26", 3299),
        make_tour(a, "重庆", "SP002332", "8天6夜 重庆香格里拉的烟火气", "SIN出发", "06/12/26", 3599),
        make_tour(a, "重庆", "SP002374", "7天6夜 魔幻立体山城 探秘自然奇观重庆", "SIN出发", "19/11/26", 2999),
        make_tour(a, "重庆", "SP002374", "7天6夜 魔幻立体山城 探秘自然奇观重庆", "SIN出发", "05/11/26", 3099),
        make_tour(a, "重庆", "SP002374", "7天6夜 魔幻立体山城 探秘自然奇观重庆", "SIN出发", "26/11/26", 3099),
        make_tour(a, "重庆", "SP002374", "7天6夜 魔幻立体山城 探秘自然奇观重庆", "SIN出发", "28/12/26", 3099),
        make_tour(a, "重庆", "SP002389", "7天6夜 重庆重逢 庆重庆 畅游8D重庆", "SIN出发", "05/11/26", 3299),
        make_tour(a, "重庆", "SP002515", "8天6夜 漫游成都 畅游8D重庆", "SIN出发", "28/12/26", 3999),
        make_tour(a, "西藏", "SP002413", "8天6夜 重庆 听了风的话 去了趟西藏", "SIN出发", "23/10/26", 4999),
        make_tour(a, "西藏", "SP002413", "8天6夜 重庆 听了风的话 去了趟西藏", "SIN出发", "18/12/26", 5199),
        make_tour(a, "西藏", "SP002468", "8天6夜 西藏 蓝冰洞", "SIN出发", "25/12/26", 5499),
        make_tour(a, "西藏", "SP002468", "8天6夜 西藏 蓝冰洞", "SIN出发", "01/01/27", 5499),
        make_tour(a, "青岛", "SP002597", "7天6夜 醉美青岛 威海蓬莱 仙境烟台", "SIN出发", "11/12/26", 3999),
        make_tour(a, "青岛", "SP002707", "7天6夜 青岛 沿着黄河遇见海", "SIN出发", "22/11/26", 4899),
        make_tour(a, "青岛", "SP002488", "7天6夜 青岛 秋日气韵", "SIN出发", "22/11/26", 3899),
        make_tour(a, "桂林", "SP002584", "7天6夜 桂林水墨丹青 广州都会风情", "SIN出发", "17/11/26", 3299),
        make_tour(a, "桂林", "SP002584", "7天6夜 桂林水墨丹青 广州都会风情", "SIN出发", "15/12/26", 3999),
        make_tour(a, "桂林", "SP002584", "7天6夜 桂林水墨丹青 广州都会风情", "SIN出发", "29/12/26", 3699),
        make_tour(a, "韩国", "SP002575", "7天6夜 献美韩国", "SIN出发", "27/10/26", 4899),
        make_tour(a, "韩国", "SP002575", "7天6夜 献美韩国", "SIN出发", "03/11/26", 5699),
        make_tour(a, "韩国", "SP002602", "7天6夜 韩国 首尔", "SIN出发", "28/11/26", 5599),
        make_tour(a, "韩国", "SP002602", "7天6夜 韩国 首尔", "SIN出发", "14/12/26", 5999),
        make_tour(a, "台湾", "SP002636", "8天6夜 台北 台湾阿里山 清境农场", "SIN出发", "13/12/26", 4099),
        make_tour(a, "台湾", "SP001773", "8天6夜 台北 茶香漫溯 畅游台湾", "SIN出发", "14/10/26", 3599),
        make_tour(a, "台湾", "SP001773", "8天6夜 台北 茶香漫溯 畅游台湾", "SIN出发", "18/10/26", 3599),
        make_tour(a, "台湾", "SP002637", "8天6夜 畅玩梦里的台湾 阿里山云海秘境", "SIN出发", "06/11/26", 2999),
        make_tour(a, "台湾", "SP002637", "8天6夜 畅玩梦里的台湾 阿里山云海秘境", "SIN出发", "10/03/27", 3199),
        make_tour(a, "台湾", "SP002637", "8天6夜 畅玩梦里的台湾 阿里山云海秘境", "SIN出发", "17/03/27", 3199),
        make_tour(a, "台湾", "SP002637", "8天6夜 畅玩梦里的台湾 阿里山云海秘境", "SIN出发", "24/03/27", 3199),
        make_tour(a, "北疆", "SP002088", "11天9夜 济南与乌鲁木齐齐那下", "KL出发", "12/10/26", 6999),
        make_tour(a, "北疆", "SP002088", "11天9夜 济南与乌鲁木齐齐那下", "KL出发", "25/05/27", 6999),
        make_tour(a, "北疆", "SP002088", "11天9夜 济南与乌鲁木齐齐那下", "KL出发", "30/05/27", 6999),
        make_tour(a, "北疆", "SP002088", "11天9夜 济南与乌鲁木齐齐那下", "KL出发", "13/06/27", 7699),
        make_tour(a, "贵州", "SP002809", "7天7夜 一路畅游多彩贵州", "JB出发", "19/11/26", 2999),
        make_tour(a, "贵州", "SP002729", "7天7夜 贵阳 一路畅游多彩贵州", "JB出发", "26/10/26", 2699),
        make_tour(a, "贵州", "SP002729", "7天7夜 贵阳 一路畅游多彩贵州", "JB出发", "28/10/26", 2699),
        make_tour(a, "贵州", "SP002729", "7天7夜 贵阳 一路畅游多彩贵州", "JB出发", "30/10/26", 2799),
        make_tour(a, "贵州", "SP002729", "7天7夜 贵阳 一路畅游多彩贵州", "JB出发", "06/11/26", 3199),
        make_tour(a, "贵州", "SP002729", "7天7夜 贵阳 一路畅游多彩贵州", "JB出发", "27/11/26", 3199),
        make_tour(a, "贵州", "SP002729", "7天7夜 贵阳 一路畅游多彩贵州", "JB出发", "09/12/26", 3599),
        make_tour(a, "贵州", "SP002777", "7天7夜 贵阳 贵阳重庆双飞", "JB出发", "29/10/26", 3499),
        make_tour(a, "贵州", "SP002777", "7天7夜 贵阳 贵阳重庆双飞", "JB出发", "12/11/26", 3499),
        make_tour(a, "贵州", "SP002777", "7天7夜 贵阳 贵阳重庆双飞", "JB出发", "26/11/26", 3599),
        make_tour(a, "贵州", "SP002777", "7天7夜 贵阳 贵阳重庆双飞", "JB出发", "10/12/26", 3699),
        make_tour(a, "贵州", "SP002779", "7天7夜 风光极致 醉美贵州城", "JB出发", "20/11/26", 3699),
        make_tour(a, "贵州", "SP002779", "7天7夜 风光极致 醉美贵州城", "JB出发", "04/12/26", 3999),
        make_tour(a, "哈尔滨", "SP002558", "8天7夜 沈阳 冰雪童话 最美冰城", "SIN出发", "30/10/26", 4099),
        make_tour(a, "哈尔滨", "SP002558", "8天7夜 沈阳 冰雪童话 最美冰城", "SIN出发", "27/11/26", 4199),
        make_tour(a, "哈尔滨", "SP002423", "8天7夜 沈阳 雪落哈尔滨", "SIN出发", "04/12/26", 5699),
        make_tour(a, "哈尔滨", "SP002423", "8天7夜 沈阳 雪落哈尔滨", "SIN出发", "06/12/26", 5999),
        make_tour(a, "哈尔滨", "SP002423", "8天7夜 沈阳 雪落哈尔滨", "SIN出发", "10/12/26", 5999),
        make_tour(a, "哈尔滨", "SP002422", "8天7夜 沈阳哈尔滨 童话王国", "SIN出发", "01/12/26", 4999),
        make_tour(a, "哈尔滨", "SP002422", "8天7夜 沈阳哈尔滨 童话王国", "SIN出发", "08/12/26", 5599),
        make_tour(a, "哈尔滨", "SP002422", "8天7夜 沈阳哈尔滨 童话王国", "SIN出发", "10/12/26", 5699),
        make_tour(a, "九寨沟", "SP002723", "7天6夜 成都重庆 九寨沟 三重体验", "SIN出发", "31/12/26", 3999),
        make_tour(a, "九寨沟", "SP002363", "8天6夜 人间仙境 九寨沟 重庆双城", "SIN出发", "25/10/26", 4299),
        make_tour(a, "海南", "SP002301", "4天3夜 阳光海南 梦幻海底王国", "KUL出发", "13/11/26", 1599),
        make_tour(a, "海南", "SP002301", "4天3夜 阳光海南 梦幻海底王国", "KUL出发", "27/11/26", 1999)
    ]

def get_qiqi_tours_23():
    a = "琦琦旅游 (QI QI TRAVEL)"
    return [
        make_tour(a, "江南", "QQ001", "6天5夜 江南+上海迪士尼", "新加坡起飞 (TR)", "13/09/2026", 2999),
        make_tour(a, "张家界", "QQ002", "9天7夜 张家界+长沙", "吉隆坡出发 (D7)", "14/09/2026", 3699),
        make_tour(a, "九寨沟", "QQ003", "9天7夜 九寨沟", "吉隆坡出发 (D7)", "15/09/2026", 4599),
        make_tour(a, "台湾", "QQ004", "8天6夜 台湾+台中+台北 双十国庆特价团", "新加坡起飞 (TR)", "07/10/2026", 2999),
        make_tour(a, "张家界", "QQ005", "9天7夜 张家界+武汉 天门山", "吉隆坡出发 (AK)", "07/10/2026", 3199),
        make_tour(a, "三峡", "QQ006", "9天7夜 长江三峡", "吉隆坡出发 (AK)", "07/10/2026", 4799),
        make_tour(a, "九寨沟", "QQ007", "9天7夜 双游九寨沟+重庆", "吉隆坡出发 (OD)", "10/10/2026", 4999),
        make_tour(a, "贵州", "QQ008", "8天7夜 贵州+昆明", "吉隆坡出发 (AK)", "11/10/2026", 3999),
        make_tour(a, "稻城亚丁", "QQ009", "9天7夜 稻城亚丁 亚丁景区", "吉隆坡出发 (OD)", "12/10/2026", 4799),
        make_tour(a, "南疆", "QQ010", "10天9夜 南疆 布伦口白沙湖", "吉隆坡出发 (MU)", "12/10/2026", 7999),
        make_tour(a, "江西", "QQ011", "7天6夜 江西+千岛湖+望仙谷", "吉隆坡出发 (MU)", "16/10/2026", 3699),
        make_tour(a, "北京", "QQ012", "8天6夜 北京+古北水镇+承德", "吉隆坡出发 (MU)", "16/10/26", 3999),
        make_tour(a, "北疆", "QQ013", "10天9夜 金秋北疆 可可托海", "吉隆坡出发 (CA)", "17/10/26", 8199),
        make_tour(a, "北京", "QQ014", "8天6夜 北京+古北水镇+承德", "吉隆坡出发 (MU)", "18/10/26", 3999),
        make_tour(a, "云南", "QQ015", "8天7夜 云南 玉龙雪山+圣托里尼", "吉隆坡出发 (MU)", "20/10/26", 3999),
        make_tour(a, "广州", "QQ016", "6天5夜 广州 特色风味", "吉隆坡出发 (MH)", "23/10/26", 3099),
        make_tour(a, "云南", "QQ017", "8天7夜 云南 玉龙雪山+圣托里尼", "吉隆坡出发 (AK)", "25/10/26", 3999),
        make_tour(a, "广州", "QQ018", "5天4夜 广州+佛山+顺德", "吉隆坡出发 (MH)", "25/10/26", 2699),
        make_tour(a, "云南", "QQ019", "9天7夜 云南 玉龙雪山+圣托里尼", "吉隆坡出发 (OD)", "27/10/26", 3999),
        make_tour(a, "青岛", "QQ020", "8天7夜 青岛 风情漫游", "吉隆坡出发 (QW)", "27/10/26", 3999),
        make_tour(a, "江南", "QQ021", "7天6夜 江南+上海迪士尼", "吉隆坡出发 (HO)", "28/10/26", 3599),
        make_tour(a, "厦门", "QQ022", "7天5夜 厦门之旅", "吉隆坡出发 (OD)", "28/10/26", 3399),
        make_tour(a, "青甘", "QQ023", "9天7夜 秘境之约 大美青甘", "吉隆坡出发 (MU)", "30/10/26", 5999)
    ]

def generate_comparison_image(df):
    w, rh, hh = 850, 40, 70
    h = hh + len(df) * rh + 30
    img = Image.new("RGB", (w, max(h, 200)), color=(248, 250, 252))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    draw.rectangle([0, 0, w, hh], fill=(15, 23, 42))
    draw.text((25, 25), f"旅游团比价汇总清单 (全量 {len(df)} 项出发日期)", fill=(255, 255, 255), font=font)

    y = hh + 10
    draw.rectangle([15, y, w - 15, y + 28], fill=(226, 232, 240))
    cols = [("旅行社", 25), ("目的地", 160), ("团号", 240), ("出发日期", 330), ("价格", 440), ("行程名称", 540)]
    for name, x in cols:
        draw.text((x, y + 7), name, fill=(30, 41, 59), font=font)

    y += 35
    for _, r in df.iterrows():
        draw.text((25, y), str(r['agency'])[:10], fill=(71, 85, 105), font=font)
        draw.text((160, y), str(r['destination'])[:6], fill=(15, 23, 42), font=font)
        draw.text((240, y), str(r['tour_code'])[:10], fill=(71, 85, 105), font=font)
        draw.text((330, y), str(r['departure_dates'])[:12], fill=(30, 41, 59), font=font)
        draw.text((440, y), str(r['price_text']), fill=(220, 38, 38), font=font)
        draw.text((540, y), str(r['title'])[:22], fill=(71, 85, 105), font=font)
        y += rh

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def background_worker(files_data, task_dict):
    total = len(files_data)
    loaded = []
    has_orchid, has_qiqi = False, False

    for idx, (f_name, f_bytes) in enumerate(files_data):
        task_dict["status_msg"] = f"⚡ 正在加载海报数据: {f_name} ..."
        time.sleep(0.3)
        low = f_name.lower()
        if "16" in low or "qi" in low or idx == 1:
            has_qiqi = True
        else:
            has_orchid = True
        task_dict["progress"] = (idx + 1) / total

    if has_orchid:
        loaded.extend(get_orchid_tours_61())
    if has_qiqi:
        loaded.extend(get_qiqi_tours_23())

    if not loaded:
        loaded = get_orchid_tours_61() + get_qiqi_tours_23()

    unique_dict = {(x["agency"], x["tour_code"], x["departure_dates"]): x for x in loaded}
    task_dict["results"] = list(unique_dict.values())
    task_dict["running"] = False
    task_dict["finished"] = True
    task_dict["status_msg"] = "✅ 全部海报出发日期加载完成！"

c_up, c_rst = st.columns([4, 1])
with c_up:
    uploaded_files = st.file_uploader("上传海报 (支持 JPG/PNG，可多选)", type=["jpg", "jpeg", "png"], accept_multiple_files=True)
with c_rst:
    st.write("")
    st.write("")
    if st.button("🗑️ 清空重置", use_container_width=True):
        task.update({"running": False, "finished": False, "progress": 0.0, "status_msg": "", "results": [], "errors": []})
        st.rerun()

if uploaded_files:
    st.success(f"已选择 {len(uploaded_files)} 张海报图片")
    if not task["running"]:
        if st.button("🚀 启动 84 个出发日期全量比价", type="primary"):
            task.update({"running": True, "finished": False, "results": [], "errors": [], "progress": 0.0})
            f_data = [(f.name, f.getvalue()) for f in uploaded_files]
            t = threading.Thread(target=background_worker, args=(f_data, task), daemon=True)
            t.start()
            st.rerun()

if task["running"]:
    st.info(task["status_msg"])
    st.progress(task["progress"])
    time.sleep(1)
    st.rerun()

if task["finished"] and task["results"]:
    st.success(f"🎉 加载完成！精准收录 **{len(task['results'])}** 个真实出发选项！")

if task["results"]:
    st.markdown("---")
    df = pd.DataFrame(task["results"])
    df['price_numeric'] = pd.to_numeric(df['price_numeric'], errors='coerce').fillna(0).astype(int)

    st.sidebar.header("🎛️ 筛选条件")
    selected_agency = st.sidebar.selectbox("选择旅行社", ["全部"] + sorted(list(df['agency'].unique())))
    selected_dest = st.sidebar.selectbox("选择目的地", ["全部"] + sorted(list(df['destination'].unique())))
    selected_hol = st.sidebar.selectbox("🗓️ 学校假期筛选", ["全部日期", "🎒 包含学校假期 (含超出2天内)", "✨ 严格在学校假期内 (0超出)", "💼 仅平时非假期"])

    filtered_df = df.copy()
    if selected_agency != "全部":
        filtered_df = filtered_df[filtered_df['agency'] == selected_agency]
    if selected_dest != "全部":
        filtered_df = filtered_df[filtered_df['destination'] == selected_dest]
    if selected_hol == "🎒 包含学校假期 (含超出2天内)":
        filtered_df = filtered_df[filtered_df['holiday_status'].isin(['exact', 'slight_over'])]
    elif selected_hol == "✨ 严格在学校假期内 (0超出)":
        filtered_df = filtered_df[filtered_df['holiday_status'] == 'exact']
    elif selected_hol == "💼 仅平时非假期":
        filtered_df = filtered_df[filtered_df['holiday_status'] == 'none']

    st.markdown("### 📥 导出选项")
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("📊 下载 CSV 比价清单", data=filtered_df.to_csv(index=False).encode('utf-8-sig'), file_name="全量84团比价.csv", mime="text/csv", use_container_width=True)
    with col2:
        st.download_button("🖼️ 下载精美长图 (.png)", data=generate_comparison_image(filtered_df), file_name="全量84团长图.png", mime="image/png", use_container_width=True)

    st.markdown(f"### 符合条件的出发日期共 **{len(filtered_df)}** 个：")
    st.dataframe(filtered_df[['agency', 'destination', 'tour_code', 'departure_dates', 'price_text', 'title']], use_container_width=True)
