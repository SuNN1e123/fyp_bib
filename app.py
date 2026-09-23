from datetime import datetime
import hashlib
import io
import json
import fitz  # PyMuPDF
from openai import OpenAI
import psycopg2
import streamlit as st

# --- 安全讀取 Secrets ---
try:
  OPENROUTER_API_KEY = st.secrets["OPENROUTER_API_KEY"]
except Exception:
  OPENROUTER_API_KEY = ""

try:
  SUPABASE_DB_URL = st.secrets["SUPABASE_DB_URL"]
except Exception:
  SUPABASE_DB_URL = ""

# 初始化 OpenRouter Client
client = None
if OPENROUTER_API_KEY:
  try:
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY
    )
  except Exception as e:
    st.error(f"OpenRouter 初始化失敗: {e}")


# --- 初始化 Supabase 雲端 PostgreSQL 資料庫連線 ---
def init_db():
  if not SUPABASE_DB_URL:
    st.error("❌ 找不到 SUPABASE_DB_URL，請檢查 Streamlit Secrets 設定！")
    st.stop()

  try:
    # 建立連線 (autocommit=True 確保即時寫入)
    conn = psycopg2.connect(SUPABASE_DB_URL, sslmode="require")
    conn.autocommit = True
    c = conn.cursor()

    # 1. 用戶表格
    c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE,
                password TEXT
            )
        """)

    # 2. 分類表格（加上 user_id 隔離）
    c.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id SERIAL PRIMARY KEY,
                user_id INTEGER,
                name TEXT
            )
        """)

    # 3. 文獻表格（加上 user_id 隔離，PDF 使用 BYTEA 儲存）
    c.execute("""
            CREATE TABLE IF NOT EXISTS papers (
                id SERIAL PRIMARY KEY,
                user_id INTEGER,
                title TEXT,
                authors TEXT,
                year TEXT,
                category TEXT,
                citation TEXT,
                pdf_data BYTEA,
                filename TEXT,
                sort_order INTEGER DEFAULT 0
            )
        """)
    return conn, c
  except Exception as e:
    st.error(f"資料庫連線失敗: {e}")
    st.stop()


conn, c = init_db()

# 設定網頁排版
st.set_page_config(
    page_title="My FYP Research Hub - 永久雲端多用戶版",
    page_icon="✨",
    layout="wide",
)

st.markdown("""
    <style>
    .main { background-color: #F8F9FA; }
    .stButton>button { border-radius: 8px; font-weight: 600; }
    </style>
""", unsafe_allow_html=True)


# --- 密碼雜湊輔助函數 ---
def hash_password(password):
  return hashlib.sha256(password.encode()).hexdigest()


# --- 用戶登入與註冊狀態管理 ---
if "logged_in" not in st.session_state:
  st.session_state.logged_in = False
if "username" not in st.session_state:
  st.session_state.username = ""
if "user_id" not in st.session_state:
  st.session_state.user_id = None

# ----------------- 未登入：顯示登入／註冊介面 -----------------
if not st.session_state.logged_in:
  st.title("✨ My FYP Research Hub - 登入專屬你的雲端文獻庫")
  st.caption(
      "資料已全面遷移至雲端資料庫（Supabase），所有帳號與 PDF 將永久保存不丟失！"
  )

  auth_tab1, auth_tab2 = st.tabs(["🔑 登入帳號", "📝 註冊新帳號"])

  with auth_tab1:
    with st.form("login_form"):
      login_user = st.text_input("用戶名稱 (Username)")
      login_pass = st.text_input("密碼 (Password)", type="password")
      login_submitted = st.form_submit_button("登入", type="primary")

      if login_submitted:
        hashed_pw = hash_password(login_pass)
        c.execute(
            "SELECT id FROM users WHERE username = %s AND password = %s",
            (login_user, hashed_pw),
        )
        user_row = c.fetchone()
        if user_row:
          st.session_state.logged_in = True
          st.session_state.username = login_user
          st.session_state.user_id = user_row[0]
          st.success(f"歡迎回來，{login_user}！正在進入你的雲端 Hub...")
          st.rerun()
        else:
          st.error("登入失敗：用戶名稱或密碼錯誤。")

  with auth_tab2:
    with st.form("register_form"):
      reg_user = st.text_input("設定用戶名稱 (Username)")
      reg_pass = st.text_input("設定密碼 (Password)", type="password")
      reg_submitted = st.form_submit_button("註冊並自動建立預設分類", type="primary")

      if reg_submitted:
        if not reg_user or not reg_pass:
          st.warning("用戶名稱與密碼不能為空！")
        else:
          try:
            hashed_pw = hash_password(reg_pass)
            c.execute(
                "INSERT INTO users (username, password) VALUES (%s, %s)",
                (reg_user, hashed_pw),
            )

            # 取得新註冊用戶的 id
            c.execute("SELECT id FROM users WHERE username = %s", (reg_user,))
            new_uid = c.fetchone()[0]

            # 為新用戶初始化預設分類
            default_cats = [
                "引言 (Introduction)",
                "方法 (Methodology)",
                "實驗 (Experiments)",
                "回收箱 (Trash)",
            ]
            for cat in default_cats:
              c.execute(
                  "INSERT INTO categories (user_id, name) VALUES (%s, %s)",
                  (new_uid, cat),
              )

            st.success(
                "🎉 雲端帳號註冊成功！請切換到「🔑 登入帳號」分頁進行登入。"
            )
          except Exception:
            st.error("該用戶名稱已經被註冊，請嘗試其他名稱。")

  st.stop()

# ----------------- 已登入：顯示用戶專屬的 FYP Hub -----------------
current_uid = st.session_state.user_id

st.sidebar.markdown(f"👤 當前用戶：**{st.session_state.username}**")
if st.sidebar.button("🚪 登出帳號"):
  st.session_state.logged_in = False
  st.session_state.username = ""
  st.session_state.user_id = None
  st.rerun()

st.title(f"✨ {st.session_state.username}'s FYP Research Hub (雲端永久版)")
st.caption(
    "專屬你的文獻管理平台：資料安全儲存於 Supabase 雲端，支援分區卡片檢視、A-Z"
    " 排序與 AI 智能解析。"
)

# 讀取當前用戶專屬的分類
c.execute(
    "SELECT name FROM categories WHERE user_id = %s ORDER BY id ASC",
    (current_uid,),
)
categories = [row[0] for row in c.fetchall()]

tab1, tab2 = st.tabs(["📚 文獻分區資料庫 (Dashboard)", "📤 上載與 AI 智能解析"])

# --- 分頁一：文獻資料庫 ---
with tab1:
  col_search, col_action = st.columns([3, 1])
  with col_search:
    search_query = st.text_input(
        "🔍 全局搜尋文獻標題或作者", "", key="search_box"
    )

  st.divider()

  # 分類管理區塊
  with st.expander("📁 管理研究分類夾 (新增 / 刪除)"):
    col_add, col_del = st.columns(2)

    with col_add:
      st.markdown("#### ➕ 建立新分類夾")
      new_cat = st.text_input(
          "輸入新分類名稱 (例如：Related Work)", key="new_cat_input"
      )
      if st.button("建立分類"):
        if new_cat:
          c.execute(
              "SELECT COUNT(*) FROM categories WHERE user_id = %s AND name ="
              " %s",
              (current_uid, new_cat),
          )
          if c.fetchone()[0] > 0:
            st.info("呢個分類已經存在喇！")
          else:
            c.execute(
                "INSERT INTO categories (user_id, name) VALUES (%s, %s)",
                (current_uid, new_cat),
            )
            st.success(f"成功新增分類夾：{new_cat}")
            st.rerun()
        else:
          st.warning("請輸入分類名稱！")

    with col_del:
      st.markdown("#### 🗑️ 刪除分類夾")
      if categories:
        cat_to_delete = st.selectbox(
            "選擇要刪除的分類夾", categories, key="del_cat_select"
        )
        st.caption(
            "⚠️ 注意：若該分類下還有文獻，刪除後文獻將會自動移至「回收箱"
            " (Trash)」！"
        )
        if st.button("確認刪除此分類", type="primary"):
          if cat_to_delete == "回收箱 (Trash)":
            st.warning("「回收箱 (Trash)」是系統保留分類，不能刪除！")
          elif len(categories) <= 1:
            st.warning("最少需要保留一個分類夾，不能全部刪除！")
          else:
            fallback_cat = "回收箱 (Trash)"
            c.execute(
                "UPDATE papers SET category = %s WHERE user_id = %s AND category"
                " = %s",
                (fallback_cat, current_uid, cat_to_delete),
            )
            c.execute(
                "INSERT INTO categories (user_id, name) SELECT %s, %s WHERE NOT"
                " EXISTS (SELECT 1 FROM categories WHERE user_id = %s AND name"
                " = %s)",
                (current_uid, fallback_cat, current_uid, fallback_cat),
            )
            c.execute(
                "DELETE FROM categories WHERE user_id = %s AND name = %s",
                (current_uid, cat_to_delete),
            )
            st.success(
                f"成功刪除分類「{cat_to_delete}」，入面嘅文獻已安全移至「回收箱"
                " (Trash)」！"
            )
            st.rerun()
      else:
        st.info("目前沒有可刪除的分類。")

  st.markdown("### 📂 研究分類分區檢視")

  for cat in categories:
    with st.container():
      col_header_title, col_header_btn = st.columns([4, 1])
      with col_header_title:
        st.markdown(
            f"<div style='background-color: #f1f3f5; padding: 10px 15px;"
            f" border-radius: 8px; font-weight: bold; font-size: 16px;"
            f" margin-top: 15px; margin-bottom: 10px;'>📌 {cat}</div>",
            unsafe_allow_html=True,
        )
      with col_header_btn:
        st.markdown(
            "<div style='margin-top: 12px;'>", unsafe_allow_html=True
        )
        if st.button("🔤 按 A-Z 排序", key=f"sort_az_{cat}"):
          c.execute(
              "SELECT id FROM papers WHERE user_id = %s AND category = %s ORDER"
              " BY title ASC",
              (current_uid, cat),
          )
          sorted_rows = c.fetchall()
          for idx, (p_id,) in enumerate(sorted_rows):
            c.execute(
                "UPDATE papers SET sort_order = %s WHERE id = %s",
                (idx, p_id),
            )
          st.success(f"已將「{cat}」內的文獻順利按字母 A-Z 排列！")
          st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

      query_sql = (
          "SELECT id, title, authors, year, citation, filename, pdf_data FROM"
          " papers WHERE user_id = %s AND category = %s"
      )
      params = [current_uid, cat]

      if search_query:
        query_sql += " AND (title ILIKE %s OR authors ILIKE %s)"
        params.extend([f"%{search_query}%", f"%{search_query}%"])

      query_sql += " ORDER BY sort_order ASC, id ASC"

      c.execute(query_sql, params)
      cat_papers = c.fetchall()

      if not cat_papers:
        st.caption("暫時未有文獻歸納在此分類中。")
      else:
        for idx, (
            paper_id,
            title,
            authors,
            year,
            citation,
            filename,
            pdf_blob,
        ) in enumerate(cat_papers, 1):
          with st.expander(f"{idx}. 📄 {title} ({year}) — {authors}"):
            st.write(f"**作者：** {authors}")
            st.write(f"**APA 7th Citation：** `{citation}`")

            col_dl, col_move, col_copy, col_del = st.columns([2, 2, 2, 1])

            with col_dl:
              if pdf_blob:
                # PostgreSQL BYTEA 轉換成 bytes
                pdf_bytes = (
                    bytes(pdf_blob)
                    if isinstance(pdf_blob, memoryview)
                    else pdf_blob
                )
                st.download_button(
                    label="📥 下載 PDF",
                    data=pdf_bytes,
                    file_name=filename if filename else f"paper_{paper_id}.pdf",
                    mime="application/pdf",
                    key=f"dl_{paper_id}",
                )
              else:
                st.caption("無 PDF")

            with col_move:
              target_move_cat = st.selectbox(
                  "移動至",
                  categories,
                  index=categories.index(cat) if cat in categories else 0,
                  key=f"move_cat_sel_{paper_id}",
                  label_visibility="collapsed",
              )
              if st.button("🚚 移動", key=f"btn_move_{paper_id}"):
                c.execute(
                    "UPDATE papers SET category = %s WHERE id = %s AND user_id"
                    " = %s",
                    (target_move_cat, paper_id, current_uid),
                )
                st.success(f"已成功移動至：{target_move_cat}")
                st.rerun()

            with col_copy:
              target_copy_cat = st.selectbox(
                  "複製至",
                  categories,
                  index=categories.index(cat) if cat in categories else 0,
                  key=f"copy_cat_sel_{paper_id}",
                  label_visibility="collapsed",
              )
              if st.button("📋 複製", key=f"btn_copy_{paper_id}"):
                c.execute(
                    """INSERT INTO papers (user_id, title, authors, year, category, citation, pdf_data, filename, sort_order)
                                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0)""",
                    (
                        current_uid,
                        title,
                        authors,
                        year,
                        target_copy_cat,
                        citation,
                        pdf_blob,
                        filename,
                    ),
                )
                st.success(f"已成功複製一份至：{target_copy_cat}")
                st.rerun()

            with col_del:
              if st.button("🗑️ 刪除", key=f"del_{paper_id}"):
                c.execute(
                    "DELETE FROM papers WHERE id = %s AND user_id = %s",
                    (paper_id, current_uid),
                )
                st.success("已刪除文獻！")
                st.rerun()

      st.markdown("---")

# --- 分頁二：上載與 AI 解析 ---
with tab2:
  st.subheader("📤 上載 PDF 文獻與 OpenRouter AI 智能提取 (雲端永久儲存)")
  uploaded_file = st.file_uploader(
      "拖放或選擇你的 PDF 檔案 (建議包含第一頁)", type="pdf"
  )

  if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    with fitz.open(stream=file_bytes, filetype="pdf") as doc:
      first_page_text = doc[0].get_text()

    filename = uploaded_file.name
    default_title = filename.replace(".pdf", "").replace("_", " ")

    if "ai_title" not in st.session_state:
      st.session_state.ai_title = default_title
    if "ai_authors" not in st.session_state:
      st.session_state.ai_authors = "Author et al."
    if "ai_year" not in st.session_state:
      st.session_state.ai_year = "2025"
    if "ai_citation" not in st.session_state:
      st.session_state.ai_citation = (
          f"{st.session_state.ai_authors} ({st.session_state.ai_year})."
          f" *{st.session_state.ai_title}*."
      )

    if client is not None:
      if st.button(
          "🤖 讓 OpenRouter AI 自動提取內文與 APA 7 格式", type="primary"
      ):
        with st.spinner("OpenRouter AI 正在深度閱讀文獻並整理格式中..."):
          try:
            prompt = (
                "請分析以下學術論文第一頁的文字，提取以下資訊，並嚴格以純 JSON"
                " 格式回傳（不要包含任何 markdown 的 ```json 或 ```"
                " 標籤，只輸出欄位）：\n"
                "- title: 論文標題\n"
                "- authors: 作者名字（請符合 APA 7 格式，例如 Lastname, F. M.,"
                " & Lastname, S. K.）\n"
                "- year: 發布年份（四位數字）\n"
                "- citation: 嚴格按照 APA 7th Edition"
                " 標準格式的完整引用字串\n\n論文第一頁文字：\n"
                + first_page_text
            )

            response = client.chat.completions.create(
                model="deepseek/deepseek-chat",
                messages=[{
                    "role": "user",
                    "content": prompt,
                }],
                temperature=0.1,
            )

            raw_content = response.choices[0].message.content.strip()
            clean_text = (
                raw_content.replace("```json", "")
                .replace("```", "")
                .strip()
            )
            paper_info = json.loads(clean_text)

            st.session_state.ai_title = paper_info.get(
                "title", default_title
            )
            st.session_state.ai_authors = paper_info.get(
                "authors", "Author et al."
            )
            st.session_state.ai_year = paper_info.get("year", "2025")
            st.session_state.ai_citation = paper_info.get(
                "citation",
                f"{st.session_state.ai_authors}"
                f" ({st.session_state.ai_year})."
                f" *{st.session_state.ai_title}*.",
            )
            st.success("✨ OpenRouter AI 成功提取並完成 APA 7 格式排版！")
            st.rerun()
          except Exception as e:
            st.error(f"AI 解析失敗，請手動確認。錯誤: {e}")

    with st.form("openrouter_upload_form"):
      paper_title = st.text_input(
          "文獻標題 (Title)", st.session_state.get("ai_title", default_title)
      )
      paper_authors = st.text_input(
          "作者 (Authors - APA 7)",
          st.session_state.get("ai_authors", "Author et al."),
      )
      paper_year = st.text_input(
          "年份 (Year)", st.session_state.get("ai_year", "2025")
      )
      paper_category = st.selectbox("選擇研究分類夾", categories)
      paper_citation = st.text_input(
          "APA 7th 引用格式 (可手動微調)",
          st.session_state.get("ai_citation", f"Author et al. (2025)."),
      )

      submitted = st.form_submit_button(
          "💾 確認無誤並加入雲端資料庫（含 PDF 原件）", type="primary"
      )
      if submitted:
        c.execute(
            "SELECT MAX(sort_order) FROM papers WHERE user_id = %s AND category"
            " = %s",
            (current_uid, paper_category),
        )
        res = c.fetchone()
        max_order = res[0] if res and res[0] is not None else -1
        new_order = max_order + 1

        # 將檔案 binary 透過 psycopg2 轉為 Binary 物件存入 BYTEA
        binary_pdf = psycopg2.Binary(file_bytes)

        c.execute(
            """INSERT INTO papers (user_id, title, authors, year, category, citation, pdf_data, filename, sort_order)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                current_uid,
                paper_title,
                paper_authors,
                paper_year,
                paper_category,
                paper_citation,
                binary_pdf,
                filename,
                new_order,
            ),
        )

        for key in ["ai_title", "ai_authors", "ai_year", "ai_citation"]:
          if key in st.session_state:
            del st.session_state[key]

        st.success("🎉 成功新增文獻及將 PDF 儲存至雲端資料庫！資料將永久保存！")
        st.rerun()
