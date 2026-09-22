from datetime import datetime
import io
import sqlite3
import fitz  # PyMuPDF
import json
from openai import OpenAI
import streamlit as st

# --- 安全讀取 OpenRouter API Key ---
try:
  OPENROUTER_API_KEY = st.secrets["OPENROUTER_API_KEY"]
except Exception:
  OPENROUTER_API_KEY = ""

# 初始化 OpenRouter Client
client = None
if OPENROUTER_API_KEY:
  try:
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY
    )
  except Exception as e:
    st.error(f"OpenRouter 初始化失敗: {e}")
else:
  st.warning(
      "⚠️ 偵測不到 OPENROUTER_API_KEY，請在 Streamlit Secrets 或設定中配置。"
  )


# --- 初始化與自動升級 SQLite 資料庫 ---
def init_db():
  conn = sqlite3.connect("fyp_papers.db", check_same_thread=False)
  c = conn.cursor()

  c.execute("""
        CREATE TABLE IF NOT EXISTS papers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            authors TEXT,
            year TEXT,
            category TEXT,
            citation TEXT
        )
    """)
  c.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        )
    """)

  c.execute("PRAGMA table_info(papers)")
  columns = [col[1] for col in c.fetchall()]

  if "pdf_data" not in columns:
    c.execute("ALTER TABLE papers ADD COLUMN pdf_data BLOB")
  if "filename" not in columns:
    c.execute("ALTER TABLE papers ADD COLUMN filename TEXT")

  default_cats = [
      "引言 (Introduction)",
      "方法 (Methodology)",
      "實驗 (Experiments)",
  ]
  for cat in default_cats:
    c.execute(
        "INSERT OR IGNORE INTO categories (name) VALUES (?)",
        (cat,),
    )
  conn.commit()
  return conn, c


conn, c = init_db()

# 設定網頁排版
st.set_page_config(
    page_title="My FYP Research Hub", page_icon="✨", layout="wide"
)

st.markdown("""
    <style>
    .main { background-color: #F8F9FA; }
    .stButton>button { border-radius: 8px; font-weight: 600; }
    </style>
""", unsafe_allow_html=True)

st.title("✨ My FYP Research Hub (分區卡片 + PDF 原件儲存版)")
st.caption(
    "結合獨立分類卡片框與資料庫永久儲存，PDF 原件隨時下載，高效管理您的 FYP"
    " 文獻！"
)

# 讀取分類
c.execute("SELECT name FROM categories")
categories = [row[0] for row in c.fetchall()]

tab1, tab2 = st.tabs(["📚 文獻分區資料庫 (Dashboard)", "📤 上載與 AI 智能解析"])

# --- 分頁一：文獻資料庫（分區卡片檢視） ---
with tab1:
  col_search, col_action = st.columns([3, 1])
  with col_search:
    search_query = st.text_input(
        "🔍 全局搜尋文獻標題或作者", "", key="search_box"
    )

  st.divider()

  with st.expander("➕ 建立新分類夾 / 資料夾"):
    new_cat = st.text_input(
        "輸入新分類名稱 (例如：Related Work)", key="new_cat_input"
    )
    if st.button("建立分類"):
      if new_cat:
        try:
          c.execute(
              "INSERT INTO categories (name) VALUES (?)",
              (new_cat,),
          )
          conn.commit()
          st.success(f"成功新增分類夾：{new_cat}")
          st.rerun()
        except sqlite3.IntegrityError:
          st.info("呢個分類已經存在喇！")
      else:
        st.warning("請輸入分類名稱！")

  st.markdown("### 📂 研究分類分區檢視")

  for cat in categories:
    with st.container():
      st.markdown(
          f"<div style='background-color: #f1f3f5; padding: 10px 15px;"
          f" border-radius: 8px; font-weight: bold; font-size: 16px; margin-top:"
          f" 15px; margin-bottom: 10px;'>📌 {cat}</div>",
          unsafe_allow_html=True,
      )

      query_sql = (
          "SELECT id, title, authors, year, citation, filename, pdf_data FROM"
          " papers WHERE category = ?"
      )
      params = [cat]

      if search_query:
        query_sql += " AND (title LIKE ? OR authors LIKE ?)"
        params.extend([f"%{search_query}%", f"%{search_query}%"])

      c.execute(query_sql, params)
      cat_papers = c.fetchall()

      if not cat_papers:
        st.caption(
            "暫時未有文獻歸納在此分類中。可透過「上載與 AI"
            " 智能解析」加入，或在下方修改文獻分類。"
        )
      else:
        for paper_id, title, authors, year, citation, filename, pdf_blob in (
            cat_papers
        ):
          with st.expander(f"📄 {title} ({year}) — {authors}"):
            st.write(f"**作者：** {authors}")
            st.write(f"**APA 7th Citation：** `{citation}`")

            col_btn1, col_btn2, col_btn3 = st.columns([2, 2, 1])

            with col_btn1:
              if pdf_blob:
                st.download_button(
                    label="📥 下載 PDF 原件",
                    data=pdf_blob,
                    file_name=filename if filename else f"paper_{paper_id}.pdf",
                    mime="application/pdf",
                    key=f"dl_{paper_id}",
                )
              else:
                st.caption("無附帶 PDF 原件")

            with col_btn2:
              new_assigned_cat = st.selectbox(
                  "流動到其他分類",
                  categories,
                  index=categories.index(cat) if cat in categories else 0,
                  key=f"move_cat_{paper_id}",
              )
              if st.button("確認轉移", key=f"btn_move_{paper_id}"):
                c.execute(
                    "UPDATE papers SET category = ? WHERE id = ?",
                    (new_assigned_cat, paper_id),
                )
                conn.commit()
                st.success(f"已成功將文獻轉移至：{new_assigned_cat}")
                st.rerun()

            with col_btn3:
              if st.button("🗑️ 刪除", key=f"del_{paper_id}"):
                c.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
                conn.commit()
                st.success("已刪除文獻！")
                st.rerun()

      st.markdown("---")

# --- 分頁二：上載與 AI 解析 ---
with tab2:
  st.subheader("📤 上載 PDF 文獻與 OpenRouter AI 智能提取")
  uploaded_file = st.file_uploader(
      "拖放或選擇你的 PDF 檔案 (建議包含第一頁)", type="pdf"
  )

  if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    with fitz.open(stream=file_bytes, filetype="pdf") as doc:
      first_page_text = doc[0].get_text()

    filename = uploaded_file.name
    default_title = filename.replace(".pdf", "").replace("_", " ")

    ai_title = default_title
    ai_authors = "Author et al."
    ai_year = "2025"
    ai_citation = f"{ai_authors} ({ai_year}). *{ai_title}*."

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

            ai_title = paper_info.get("title", default_title)
            ai_authors = paper_info.get("authors", "Author et al.")
            ai_year = paper_info.get("year", "2025")
            ai_citation = paper_info.get(
                "citation", f"{ai_authors} ({ai_year}). *{ai_title}*."
            )
            st.success("✨ OpenRouter AI 成功提取並完成 APA 7 格式排版！")
          except Exception as e:
            st.error(f"AI 解析失敗，請手動確認。錯誤: {e}")

    with st.form("openrouter_upload_form"):
      paper_title = st.text_input("文獻標題 (Title)", ai_title)
      paper_authors = st.text_input("作者 (Authors - APA 7)", ai_authors)
      paper_year = st.text_input("年份 (Year)", ai_year)
      paper_category = st.selectbox("選擇研究分類夾", categories)
      paper_citation = st.text_input(
          "APA 7th 引用格式 (可手動微調)", ai_citation
      )

      submitted = st.form_submit_button(
          "💾 確認無誤並加入資料庫（含 PDF 原件）", type="primary"
      )
      if submitted:
        c.execute(
            """INSERT INTO papers (title, authors, year, category, citation, pdf_data, filename)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                paper_title,
                paper_authors,
                paper_year,
                paper_category,
                paper_citation,
                sqlite3.Binary(file_bytes),
                filename,
            ),
        )
        conn.commit()
        st.success("🎉 成功新增文獻及儲存 PDF 原件！紀錄已永久保存！")
        st.rerun()
