@st.cache_resource
def init_google_sheets_connection():
    try:
        scope = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        gcp_secrets = dict(st.secrets["gcp_service_account"])
        if "private_key" in gcp_secrets:
            # 确保去掉前后多余的空白并规范化换行
            pk = str(gcp_secrets["private_key"]).strip()
            pk = pk.replace("\\n", "\n")
            gcp_secrets["private_key"] = pk
            
        creds = Credentials.from_service_account_info(gcp_secrets, scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open("TourPriceDB").sheet1
        return sheet
    except Exception as e:
        st.error(f"连接 Google Sheets 失败，请检查配置: {e}")
        return None
