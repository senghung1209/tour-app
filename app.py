import streamlit as st
import pandas as pd
import time
import datetime
import re
import json
import base64
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

st.set_page_config(page_title="跨社旅游团比价筛选中心", page_icon="✈️", layout="wide")

st.title("✈️ 跨旅行社海报聚合与横向对比中心")
st.markdown("已接入 Google 官方 `gemini-flash-latest` 多模态引擎，支持海报全量精准提取与分批累加。")

OFFICIAL_HOLIDAYS = [
    (datetime.date(2026, 3, 20), datetime.date(2026, 3, 29), "2026 第一学期假期 (3月)"),
    (datetime.date(2026, 5, 22), datetime.date(2026, 6, 7), "2026 年中假期 (5/6月)"),
    (datetime.date(2026, 8, 28), datetime.date(2026, 9, 6), "2026 第二学期假期 (8/9月)"),
    (datetime.date(2026, 12, 4), datetime.date(2027, 1, 3), "2026 学年末大假期 (12月)"),
    (datetime.date(2027, 1, 23), datetime.date(2027, 2, 16), "2027 农历新年与跨年假期")
]

# 严格剔除密钥中可能携带的隐藏空格或换行符
RAW_KEY = st.secrets.get("GEMINI_API_KEY", "")
GEMINI_API_KEY = str(RAW_KEY).strip() if RAW_KEY else ""
TARGET_MODEL = "gemini-flash-latest"

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
    if any(k in s for k in ["新加坡", "SIN", "CHANGI", "TR"]):
        return "🇸🇬 新加坡起飞 (SIN)"
    return "🇲🇾 马来西亚起飞 (KUL)"

def split_and_explode_dates(raw_agency, raw_dest, raw_code, raw_title, raw_loc, raw_dates_str, raw_price):
    days = extract_tour_days(raw_title)
    try:
        clean_price = int(re.sub(r'[^\d]', '', str(raw_price)))
    except Exception:
        clean_price = 0

    norm_loc = normalize_departure_location(raw_loc, raw_title)

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

def call_gemini_vision(image_bytes):
    if not GEMINI_API_KEY:
        raise ValueError("未检测到 GEMINI_API_KEY，请在 Streamlit 后台 Secrets 中配置")

    # 规范化压缩海报，控制传输体积
    img = Image.open(BytesIO(image_bytes))
    if img.mode != 'RGB':
        img = img.convert('RGB')
    w, h = img.size
    if max(w, h) > 1600:
        scale = 1600.0 / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    base64_data = base64.b64encode(buf.getvalue()).decode('utf-8')

    prompt = """
    你是一个专业的高精度旅游海报表格提取引擎。海报中包含一份多行的旅游团汇总表，请仔细阅读并提取每一行，绝不能遗漏任何一行！
    重要规则：
    1. 表格里有几个行程行（例如序号 1 到 23），就必须提取出完整数量的数据项，切勿中途截断；
    2. 如果某行写有“新加坡起飞”或航空公司代码为 TR，departure_location 填写“新加坡起飞 (SIN)”；否则统一填写“马来西亚起飞 (KUL)”；
    3. 行程若有多个出发日，全部列在 departure_dates 字段中，用逗号隔开；
    4. 务必输出纯 JSON 数组，严禁任何 Markdown 外皮（如 ```json）或额外文字：
    [
      {
        "agency": "旅行社名称(如 琦琦旅游/豪吉旅游)",
        "destination": "目的地(如 江南/张家界/九寨沟)",
        "tour_code": "团号或序号",
        "title": "行程路线全称",
        "departure_location": "新加坡起飞 (SIN) 或 马来西亚起飞 (KUL)",
        "departure_dates": "出发日期(如 13/09/2026)",
        "price": 2999
      }
    ]
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
            "maxOutputTokens": 8192,
            "response_mime_type": "application/json"
        }
    }

    # 规范标准干净的 URL，不拼接易出乱码的参数，彻底规避 adapter 错误
    clean_url = f"[https://generativelanguage.googleapis.com/v1beta/models/](https://generativelanguage.googleapis.com/v1beta/models/){TARGET_MODEL}:generateContent".strip()
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }

    res = requests.post(clean_url, headers=headers, json=payload, timeout=30)
    
    if res.status_code == 200:
        res_json = res.json()
        raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
        clean_json = re.search(r'\[.*\]', raw_text, re.DOTALL)
        if clean_json:
            return json.loads(clean_json.group(0))
        return json.loads(raw_text)
    else:
        raise RuntimeError(f"Google 官方 API 响应错误 (HTTP {res.status_code}): {res.text[:150]}")

def generate_comparison_image(df):
    w, rh, hh = 850, 40, 70
    h = hh + len(df) * rh + 30
    img = Image.new("RGB", (w, max(h, 200)), color=(248, 250, 252))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    draw.rectangle([0, 0, w, hh], fill=(15, 23, 42))
    draw.text((25, 25), f"旅游团比价汇总清单 (共 {len(df)} 项出发日期)", fill=(255, 255, 255), font=font)

    y = hh + 10
    draw.rectangle([15, y, w - 15, y + 28], fill=(226, 232, 240))
    cols = [("旅行社", 25), ("目的地", 160), ("团号", 240), ("出发日期", 330), ("价格", 440), ("起飞地", 530), ("行程名称", 670)]
    for name, x in cols:
        draw.text((x, y + 7), name, fill=(30, 41, 59), font=font)

    y += 35
    for _, r in df.iterrows():
        draw.text((25, y), str(r['agency'])[:10], fill=(71, 85, 105), font=font)
        draw.text((160, y), str(r['destination'])[:6], fill=(15, 23, 42), font=font)
        draw.text((240, y), str(r['tour_code'])[:10], fill=(71, 85, 105), font=font)
        draw.text((330, y), str(r['departure_dates'])[:12], fill=(30, 41, 59), font=font)
        draw.text((440, y), str(r['price_text']), fill=(220, 38, 38), font=font)
        draw.text((530, y), str(r['departure_location'])[:12], fill=(2, 132, 199), font=font)
        draw.text((670, y), str(r['title'])[:16], fill=(71, 85, 105), font=font)
        y += rh

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

if "tour_data" not in st.session_state:
    st.session_state.tour_data = []

