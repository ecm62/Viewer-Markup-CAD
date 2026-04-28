import streamlit as st
import fitz  # PyMuPDF
from streamlit_drawable_canvas import st_canvas
from PIL import Image
import cloudconvert
import requests
import io
import tempfile
import os
import ezdxf

# --- 1. 系統介面與名稱設定 ---
st.set_page_config(page_title="英俊的小羊 - 工程圖審查系統", layout="wide")
st.title("🐑 英俊的小羊系列：工程圖面審查與標註系統 V1.4 專業版")
st.markdown("---")

# --- 2. API 權限與邏輯判定 ---
owner_api_key = st.secrets.get("CLOUCCONVERT_API_KEY", None)

with st.sidebar.expander("🔑 進階：API 設定 (訪客轉換 DWG 專用)"):
    user_api_key = st.text_input("輸入 CloudConvert API Key", type="password")

final_api_key = user_api_key if user_api_key else owner_api_key

# --- 3. 檔案上傳與處理核心 ---
uploaded_file = st.file_uploader("請上傳工程圖 (支援 PDF, DWG, PNG, JPG)", type=["pdf", "dwg", "png", "jpg", "jpeg"])

img = None 
pdf_stream = None 

if uploaded_file is not None:
    file_ext = uploaded_file.name.split('.')[-1].lower()
    
    # 邏輯分支 A：處理 DWG (呼叫 API 轉換)
    if file_ext == "dwg":
        if not final_api_key:
            st.error("❌ 系統攔截：未偵測到內碼，請在左側填入 API Key。")
        else:
            with st.spinner("🔄 正在進行雲端 DWG 轉 PDF 運算..."):
                try:
                    cloudconvert.configure(api_key=final_api_key)
                    job = cloudconvert.Job.create(payload={
                        "tasks": {
                            "import-file": {"operation": "import/upload"},
                            "convert-file": {"operation": "convert", "input": "import-file", "output_format": "pdf"},
                            "export-file": {"operation": "export/url", "input": "convert-file"}
                        }
                    })
                    
                    upload_task = next(task for task in job['tasks'] if task['name'] == 'import-file')
                    
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".dwg") as tmp:
                        tmp.write(uploaded_file.getvalue())
                        tmp_path = tmp.name
                        
                    cloudconvert.Task.upload(file_name=tmp_path, task=upload_task)
                    os.remove(tmp_path)
                    
                    job = cloudconvert.Job.wait(id=job['id'])
                    export_task = next((task for task in job['tasks'] if task['name'] == 'export-file'), None)
                    
                    if export_task and 'result' in export_task:
                        file_url = export_task['result']['files'][0]['url']
                        response = requests.get(file_url)
                        pdf_stream = io.BytesIO(response.content)
                        st.success("✅ DWG 轉換成功！")
                except Exception as e:
                    st.error(f"❌ 轉換失敗：{str(e)}")

    elif file_ext == "pdf":
        pdf_stream = uploaded_file

    # --- 4. 影像解析與分頁控制 ---
    if pdf_stream is not None:
        try:
            doc = fitz.open(stream=pdf_stream.read(), filetype="pdf")
            total_pages = doc.page_count
            st.sidebar.markdown("---")
            selected_page = st.sidebar.number_input(f"頁面 (總計: {total_pages})", min_value=1, max_value=total_pages, value=1)
            page = doc.load_page(selected_page - 1)
            pix = page.get_pixmap(dpi=150)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        except Exception as e:
            st.error(f"❌ 解析失敗：{str(e)}")
        
    elif file_ext in ["png", "jpg", "jpeg"]:
        img = Image.open(uploaded_file)
        
    # --- 5. 標註畫布渲染 ---
    if img is not None:
        st.sidebar.markdown("---")
        st.sidebar.header("🖌️ 標註工具")
        drawing_mode = st.sidebar.selectbox("模式", ("freedraw", "line", "rect", "circle", "transform"))
        stroke_color = st.sidebar.color_picker("顏色", "#FF0000")
        stroke_width = st.sidebar.slider("粗細", 1, 20, 3)

        st.write("### 圖紙標註區")
        canvas_result = st_canvas(
            fill_color="rgba(255, 255, 0, 0.3)", 
            stroke_width=stroke_width,
            stroke_color=stroke_color,
            background_image=img,
            height=img.height,
            width=img.width,
            drawing_mode=drawing_mode,
            key="canvas",
        )

        # --- 6. PNG 與 DXF 雙格式匯出運算 ---
        st.markdown("---")
        st.write("### 📥 成果輸出")
        
        if canvas_result.image_data is not None:
            # A. PNG 合併圖層
            draw_img = Image.fromarray(canvas_result.image_data.astype('uint8'), 'RGBA')
            bg_img = img.convert("RGBA")
            bg_img.alpha_composite(draw_img)
            png_output = io.BytesIO()
            bg_img.convert("RGB").save(png_output, format='PNG')

            # B. DXF 向量座標轉換 (實作 Y 軸反轉矩陣)
            dxf_doc = ezdxf.new('R2010')
            msp = dxf_doc.modelspace()
            canvas_h = img.height
            
            if canvas_result.json_data and "objects" in canvas_result.json_data:
                for obj in canvas_result.json_data["objects"]:
                    def to_cad_y(y): return canvas_h - y
                    try:
                        if obj["type"] == "line":
                            msp.add_line((obj["x1"], to_cad_y(obj["y1"])), (obj["x2"], to_cad_y(obj["y2"])))
                        elif obj["type"] == "rect":
                            x, y, w, h = obj["left"], obj["top"], obj["width"], obj["height"]
                            pts = [(x, to_cad_y(y)), (x+w, to_cad_y(y)), (x+w, to_cad_y(y+h)), (x, to_cad_y(y+h))]
                            msp.add_lwpolyline(pts, close=True)
                        elif obj["type"] == "circle":
                            msp.add_circle((obj["left"] + obj["radius"], to_cad_y(obj["top"] + obj["radius"])), radius=obj["radius"])
                    except: pass
            
            dxf_output = io.BytesIO()
            dxf_doc.write(dxf_output)

            col1, col2 = st.columns(2)
            col1.download_button("✅ 下載 PNG 審閱圖", png_output.getvalue(), f"Review_{uploaded_file.name}.png", "image/png")
            col2.download_button("📐 下載 DXF 標註層", dxf_output.getvalue(), f"Markup_{uploaded_file.name}.dxf", "application/dxf")
