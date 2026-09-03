import streamlit as st
import pandas as pd
import time
import datetime
import re
import json
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import streamlit.components.v1 as components

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

st.set_page_config(page_title="跨社旅游团聚合与智能筛选中心", page_icon="✈️", layout="wide")

st.title("✈️ 跨旅行社海报聚合与动态解析中心")
st.markdown("支持任意旅行社海报自动化识别：按印出的每一个出发日期精准展开与比价。")

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

# 侧边栏：API 密钥配置
api_key = st.sidebar.text_input("🔑 输入 Gemini API Key", type="password", help="用于自动识别任意上传的新海报")

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

    d, mth, y = matches[0]
    d, mth = int(d), int(mth)
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
                if total_over <= 2:
                    return 'slight_over', total_over, h_name
    except Exception:
        pass

    return 'none', 0, ""

def split_and_explode_dates(raw_agency, raw_dest, raw_code, raw_title, raw_loc, raw_dates_str, raw_price):
    """
    核心拆分引擎：将 '26/10, 28/10, 30/10' 等合并日期逐一拆解为独立的团记录
    """
    days = extract_tour_days(raw_title)
    try:
        clean_price = int(re.sub(r'[^\d]', '', str(raw_price)))
    except Exception:
        clean_price = 0

    # 匹配所有的独立日期段 (支持如 26/10/26, 26/10, 10/3/27 等格式)
    date_tokens = re.findall(r'\b\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?\b', str(raw_dates_str))
    
    # 若无法通过正则拆分，保留原样
    if not date_tokens:
        date_tokens = [str(raw_dates_str).strip()]

    exploded = []
    for d_token in date_tokens:
        status, over_days, hol_name = evaluate_holiday_fit(d_token, days)
        exploded.append({
            "agency": raw_agency,
            "destination": raw_dest,
            "tour_code": raw_code,
            "title": raw_title,
            "departure_location": raw_loc,
            "departure_dates": d_token,
            "price_numeric": clean_price,
            "price_text": f"RM {clean_price}",
            "holiday_status": status,
            "over_days": over_days,
            "holiday_name": hol_name
        })
    return exploded

def parse_poster_with_ai(image_bytes, mime_type, key):
    """使用多模态视觉模型进行零样本全量提取"""
    if not GENAI_AVAILABLE:
        raise ImportError("请在 requirements.txt 中安装 google-genai 库")
        
    client = genai.Client(api_key=key)
    prompt = """
    你是一个专业旅游数据解析引擎。请分析此海报并提取所有旅游行程选项。
    如果同一个行程下列出了多个出发日期（例如 '14/10, 18/10'），请在 departure_dates 字段中将它们全部保留，用逗号隔开。
    严格返回 JSON 格式列表：
    [
      {
        "agency": "旅行社名称",
        "destination": "目的地",
        "tour_code": "团号代码",
        "title": "路线标题",
        "departure_location": "出发地(如 SIN/KUL/JB)",
        "departure_dates": "全部出发日期(如 26/10, 28/10)",
        "price": 2999
      }
    ]
    """
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            prompt
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json"
        )
    )
    return json.loads(response.text)

def generate_comparison_image(df):
    img_width = 850
    row_height = 42
    header_height = 70
    total_height = header_height + len(df) * row_height + 30
    
    img = Image.new("RGB", (img_width, max(total_height, 200)), color=(248, 250, 252))
    draw = ImageDraw.Draw(img)
    
    font_default = ImageFont.load_default()
        
    draw.rectangle([0, 0, img_width, header_height], fill=(15, 23, 42))
    draw.text((25, 25), f"旅游团比价汇总清单 (共 {len(df)} 项出发日期)", fill=(255, 255, 255), font=font_default)
    
    y = header_height + 10
    draw.rectangle([15, y, img_width - 15, y + 30], fill=(226, 232, 240))
    cols = [("旅行社", 25), ("目的地", 160), ("团号", 240), ("出发日期", 330), ("价格", 440), ("行程名称", 540)]
    for name, x in cols:
        draw.text((x, y + 8), name, fill=(30, 41, 59), font=font_default)
        
    y += 38
    for _, r in df.iterrows():
        draw.text((25, y), str(r['agency'])[:10], fill=(71, 85, 105), font=font_default)
        draw.text((160, y), str(r['destination'])[:6], fill=(15, 23, 42), font=font_default)
        draw.text((240, y), str(r['tour_code'])[:10], fill=(71, 85, 105), font=font_default)
        draw.text((330, y), str(r['departure_dates'])[:12], fill=(30, 41, 59), font=font_default)
        draw.text((440, y), str(r['price_text']), fill=(220, 38, 38), font=font_default)
        draw.text((540, y), str(r['title'])[:22], fill=(71, 85, 105), font=font_default)
        y += row_height
        
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def background_worker(files_data, user_api_key, task_dict):
    total = len(files_data)
    for idx, (f_name, f_bytes, f_type) in enumerate(files_data):
        task_dict["status_msg"] = f"⚡ 正在动态解析海报 {idx + 1}/{total}: {f_name} ..."
        try:
            raw_items = parse_poster_with_ai(f_bytes, f_type, user_api_key)
            for item in raw_items:
                exploded_rows = split_and_explode_dates(
                    item.get("agency", "未知旅行社"),
                    item.get("destination", "未知"),
                    item.get("tour_code", "-"),
                    item.get("title", ""),
                    item.get("departure_location", "-"),
                    item.get("departure_dates", ""),
                    item.get("price", 0)
                )
                task_dict["results"].extend(exploded_rows)
        except Exception as err:
            task_dict["errors"].append(f"{f_name} 解析异常: {err}")
            
        task_dict["progress"] = (idx + 1) / total
        
    task_dict["running"] = False
    task_dict["finished"] = True
    task_dict["status_msg"] = "✅ 全部海报动态提取与原子日期拆解完成！"

c_up, c_rst = st.columns([4, 1])
with c_up:
    uploaded_files = st.file_uploader("上传宣传海报 (支持 JPG/PNG，可多选)", type=["jpg", "jpeg", "png"], accept_multiple_files=True)
with c_rst:
    st.write("")
    st.write("")
    if st.button("🗑️ 清空重置", use_container_width=True):
        task["running"] = False
        task["finished"] = False
        task["progress"] = 0.0
        task["status_msg"] = ""
        task["results"] = []
        task["errors"] = []
        st.rerun()

if uploaded_files:
    st.success(f"已选 {len(uploaded_files)} 张海报图片")
    if not task["running"]:
        if st.button("🚀 启动自动化全量日期解析", type="primary"):
            if not api_key:
                st.error("请先在左侧边栏输入 Gemini API Key 启用动态解析")
            else:
                task["running"] = True
                task["finished"] = False
                task["results"] = []
                task["errors"] = []
                task["progress"] = 0.0
                
                f_data = [(f.name, f.getvalue(), f.type or "image/jpeg") for f in uploaded_files]
                t = threading.Thread(target=background_worker, args=(f_data, api_key, task), daemon=True)
                t.start()
                st.rerun()

if task["running"]:
    st.info(task["status_msg"])
    st.progress(task["progress"])
    time.sleep(2)
    st.rerun()

if task["finished"]:
    if task["results"]:
        st.success(f"🎉 解析完成！共精准展开并收录 **{len(task['results'])}** 个独立出发日期！")
    if task["errors"]:
        for e in task["errors"]:
            st.warning(f"⚠️ {e}")

if task["results"]:
    st.markdown("---")
    df = pd.DataFrame(task["results"])
    df['price_numeric'] = pd.to_numeric(df['price_numeric'], errors='coerce').fillna(0).astype(int)
    
    st.sidebar.header("🎛️ 筛选条件")
    selected_agency = st.sidebar.selectbox("选择旅行社", ["全部"] + sorted(list(df['agency'].unique())))
    selected_dest = st.sidebar.selectbox("选择目的地", ["全部"] + sorted(list(df['destination'].unique())))
    
    holiday_options = ["全部日期", "🎒 包含学校假期 (含超出2天内)", "✨ 严格在学校假期内 (0超出)", "💼 仅平时非假期"]
    selected_hol = st.sidebar.selectbox("🗓️ 学校假期筛选", holiday_options)

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
        st.download_button(
            "📊 下载 CSV 比价清单",
            data=filtered_df.to_csv(index=False).encode('utf-8-sig'),
            file_name="旅游团全量日期比价.csv",
            mime="text/csv",
            use_container_width=True
        )
    with col2:
        st.download_button(
            "🖼️ 下载精美长图 (.png)",
            data=generate_comparison_image(filtered_df),
            file_name="旅游团比价长图.png",
            mime="image/png",
            use_container_width=True
        )
        
    st.markdown(f"### 符合条件的出发日期共 **{len(filtered_df)}** 个：")
    st.dataframe(filtered_df[['agency', 'destination', 'tour_code', 'departure_dates', 'price_text', 'title']], use_container_width=True)
