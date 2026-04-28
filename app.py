import streamlit as st
import fitz  # PyMuPDF
from streamlit_drawable_canvas import st_canvas
from PIL import Image
import cloudconvert
import requests
import io
import tempfile
import os

# --- 1. 系統介面與名稱設定 ---
st.set_page_config(page_title="英俊的小羊 - 工程圖審查系統", layout="wide")
st.title("🐑 英俊的小羊系列：工程圖面審查與標註系統 V1.3")
st.markdown("---")

# --- 2. API 權限與邏輯判定 ---
# 因果：保護主人的 API 額度，同時允許訪客自帶鑰匙
owner_api_key = st.secrets.get("CLOUCCONVERT_API_KEY", None)

with st.sidebar.expander("🔑 進階：API 設定 (訪客轉換 DWG 專用)"):
    user_api_key = st.text_input("輸入 CloudConvert API Key", type="password")

final_api_key = user_api_key if user_api_key else owner_api_key

# --- 3. 檔案上傳與處理核心 ---
uploaded_file = st.file_uploader("請上傳工程圖 (支援 PDF, DWG, PNG, JPG)", type=["pdf", "dwg", "png", "jpg", "jpeg"])

img = None # 初始化背景底圖
pdf_stream = None # 初始化 PDF 數據流

if uploaded_file is not None:
    file_ext = uploaded_file.name.split('.')[-1].lower()
    
    # 邏輯分支 A：處理 DWG (呼叫第三方 API 轉換為 PDF)
    if file_ext == "dwg":
        if not final_api_key:
            st.error("❌ 系統攔截：未偵測到系統內碼，訪客請在左側填入自有的 API Key 才能處理 DWG 檔案。")
        else:
            with st.spinner("🔄 正在呼叫雲端引擎轉換 DWG 為 PDF，請稍候..."):
                try:
                    cloudconvert.configure(api_key=final_api_key)
                    # 建立轉檔任務
                    job = cloudconvert.Job.create(payload={
                        "tasks": {
                            "import-file": {"operation": "import/upload"},
                            "convert-file": {
                                "operation": "convert",
                                "input": "import-file",
                                "output_format": "pdf"
                            },
                            "export-file": {
                                "operation": "export/url",
                                "input": "convert-file"
                            }
                        }
                    })
                    
                    # 暫存 DWG 並上傳
                    upload_task_id = job['tasks'][0]['id']
                    upload_task = cloudconvert.Task.find(id=upload_task_id)
                    
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".dwg") as tmp:
                        tmp.write(uploaded_file.getvalue())
                        tmp_path = tmp.name
                        
                    cloudconvert.Task.upload(file_name="temp.dwg", path=tmp_path, task=upload_task)
                    os.remove(tmp_path) # 上傳完畢後刪除暫存檔
                    
                    # 等待伺服器運算完成
                    job = cloudconvert.Job.wait(id=job['id'])
                    export_task = job['tasks'][2]
                    
                    # 下載轉換好的 PDF 到記憶體中
                    file_url = export_task['result']['files'][0]['url']
                    response = requests.get(file_url)
                    pdf_stream = io.BytesIO(response.content)
                    st.success("✅ DWG 轉換成功！")
                    
                except Exception as e:
                    st.error(f"❌ 轉換失敗，請檢查 API Key 或網路狀態。錯誤代碼：{str(e)}")

    # 邏輯分支 B：直接處理原生 PDF
    elif file_ext == "pdf":
        pdf_stream = uploaded_file

    # --- 4. 影像光柵化與分頁控制器 ---
    if pdf_stream is not None:
        doc = fitz.open(stream=pdf_stream.read(), filetype="pdf")
        total_pages = doc.page_count
        
        st.sidebar.markdown("---")
        st.sidebar.subheader("📄 PDF 分頁控制器")
        selected_page = st.sidebar.number_input(
            f"目前選擇頁面 (總頁數: {total_pages})", 
            min_value=1, max_value=total_pages, value=1
        )
        
        # 物理限制：將 PDF 向量轉換為像素圖片供畫布使用
        page = doc.load_page(selected_page - 1)
        pix = page.get_pixmap(dpi=150)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        
    # 邏輯分支 C：處理一般圖片
    elif file_ext in ["png", "jpg", "jpeg"]:
        img = Image.open(uploaded_file)
        
    # --- 5. 繪圖標註與畫布渲染 ---
    if img is not None:
        st.sidebar.markdown("---")
        st.sidebar.header("🖌️ 標註工具設定")
        drawing_mode = st.sidebar.selectbox("繪圖模式", ("freedraw (自由畫筆)", "line (直線)", "rect (矩形框)", "circle (圓形)", "transform (選取移動)"))
        mode_command = drawing_mode.split(" ")[0]
        
        stroke_color = st.sidebar.color_picker("畫筆顏色", "#FF0000")
        stroke_width = st.sidebar.slider("畫筆粗細", 1, 25, 3)

        st.write("### 圖紙標註區")
        # 建立畫布層
        canvas_result = st_canvas(
            fill_color="rgba(255, 255, 0, 0.3)", 
            stroke_width=stroke_width,
            stroke_color=stroke_color,
            background_image=img,
            update_streamlit=True,
            height=img.height,
            width=img.width,
            drawing_mode=mode_command,
            key="canvas",
        )

        # --- 6. 專業防呆匯出 (底圖與標註合併) ---
        st.markdown("---")
        st.write("### 📥 匯出結果")
        if canvas_result.image_data is not None:
            # 矩陣運算：將標註圖層 (RGBA) 疊加至原始底圖上
            drawing_layer = Image.fromarray(canvas_result.image_data.astype('uint8'), 'RGBA')
            merged_img = img.convert("RGBA")
            merged_img.alpha_composite(drawing_layer)
            merged_img = merged_img.convert("RGB") # 轉回標準格式
            
            # 將合併後的圖片轉為二進制數據提供下載
            img_byte_arr = io.BytesIO()
            merged_img.save(img_byte_arr, format='PNG')
            img_byte_arr = img_byte_arr.getvalue()

            st.download_button(
                label="✅ 下載標註完成的工程圖 (PNG格式)",
                data=img_byte_arr,
                file_name=f"Reviewed_{uploaded_file.name}.png",
                mime="image/png"
            )
            st.info("因果提醒：若是多頁 PDF，請務必『標註完一頁、立刻下載該頁』，再切換至下一頁，以防網頁重整清除數據。")
