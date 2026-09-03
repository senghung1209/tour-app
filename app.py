import streamlit as st
import requests

st.set_page_config(page_title="Gemini 模型自检工具", layout="wide")
st.title("🔍 Google 官方可用模型一键查询")

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

if not GEMINI_API_KEY:
    st.error("❌ 未在 Streamlit Secrets 中读取到 GEMINI_API_KEY")
else:
    st.write(f"当前使用的 Key 前缀: `{GEMINI_API_KEY[:8]}...`")

if st.button("🚀 点击查询当前账号所有可用模型", type="primary"):
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    headers = {"x-goog-api-key": GEMINI_API_KEY}
    
    with st.spinner("正在向 Google 官方查询..."):
        try:
            res = requests.get(url, headers=headers, timeout=20)
            if res.status_code == 200:
                data = res.json()
                models = data.get("models", [])
                
                # 过滤出支持生成内容（看图/对话）的模型
                usable_models = []
                for m in models:
                    methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" in methods:
                        usable_models.append(m.get("name", "").replace("models/", ""))
                
                st.success(f"✅ 查询成功！你的 Key 共有 {len(usable_models)} 个可用生成模型：")
                
                # 重点标出带 flash 的模型
                flash_list = [m for m in usable_models if "flash" in m]
                if flash_list:
                    st.markdown("### ⭐ 推荐的极速 Flash 模型：")
                    for m in flash_list:
                        st.code(m, language="text")
                
                st.markdown("### 📋 全部可用模型列表：")
                st.write(usable_models)
                
            else:
                st.error(f"❌ 查询失败，HTTP 状态码: {res.status_code}")
                st.json(res.json())
        except Exception as e:
            st.error(f"❌ 请求发生异常: {e}")
