import streamlit as st
import fitz  # PyMuPDF
from streamlit_drawable_canvas import st_canvas
from PIL import Image, ImageOps
import cloudconvert
import requests
import io
import tempfile
import os
import ezdxf

# --- 1. 系統介面大改版設定 ---
st.set_page_config(page_title="工程圖審查系統 V2.1", layout="wide", initial_sidebar_state="collapsed")
st.title("🐑 英俊的小羊：工程圖面審查與標註系統 V2.1 (高解析細節版)")
st.markdown("---")

if 'ready_to_draw' not in st.session_state:
    st.session_state.ready_to_draw = False

# --- 2. 側邊欄：API 設定 ---
with st.sidebar:
    st.header("⚙️ 系統核心設定")
    owner_api_key = st.secrets.get("CLOUCCONVERT_API_KEY", None)
    user_api_key = st.text_input("輸入 CloudConvert API Key", type="password")
    final_api_key = user_api_key if user_api_key else owner_api_key

# --- 3. 主畫面分頁結構 ---
tab_input, tab_preview, tab_canvas = st.tabs(["📥 1. 輸入與解析", "🔍 2. 預覽與調控", "🖌️ 3. 巨型畫布標註與輸出"])

img = None 
pdf_stream = None 

# ==========================================
# 📥 第一區塊：輸入與解析
# ==========================================
with tab_input:
    st.subheader("請上傳工程圖紙 (將以高解析度光柵化)")
    uploaded_file = st.file_uploader("", type=["pdf", "dwg", "dxf", "dwf", "png", "jpg", "jpeg", "tiff", "bmp"])
    
    if uploaded_file is not None:
        file_ext = uploaded_file.name.split('.')[-1].lower()
        
        if file_ext in ["dwg", "dxf", "dwf"]:
            if not final_api_key:
                st.error("❌ 缺少 API Key，無法解析 CAD 格式。")
            else:
                with st.spinner(f"🔄 雲端引擎處理中，請耐心等候..."):
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
                        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_ext}") as tmp:
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
                            st.success(f"✅ 解析成功！請前往第二頁籤。")
                        else:
                            st.error("❌ 轉換失敗：檔案可能包含不支援的結構。")
                    except Exception as e:
                        st.error(f"❌ 雲端引擎錯誤：{str(e)}")
        
        elif file_ext == "pdf":
            pdf_stream = uploaded_file
            st.success("✅ PDF 載入成功！")
            
        elif file_ext in ["png", "jpg", "jpeg", "tiff", "bmp"]:
            img = Image.open(uploaded_file).convert("RGBA")
            st.success(f"✅ 圖片載入成功！")

        if pdf_stream is not None:
            try:
                doc = fitz.open(stream=pdf_stream.read(), filetype="pdf")
                total_pages = doc.page_count
                selected_page = st.number_input(f"選擇頁面 (總頁數: {total_pages})", min_value=1, max_value=total_pages, value=1)
                page = doc.load_page(selected_page - 1)
                # 物理決策：提高 DPI 基礎值至 200，確保工程線條清晰
                pix = page.get_pixmap(dpi=200, alpha=True)
                img = Image.frombytes("RGBA", [pix.width, pix.height], pix.samples)
            except Exception as e:
                st.error(f"❌ PDF 解析失敗：{str(e)}")

# ==========================================
# 🔍 第二區塊：預覽與調控
# ==========================================
with tab_preview:
    if img is not None:
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.subheader("參數調控面板")
            vision_fix = st.radio("光學對比修正:", ("預設模式", "強制黑底", "負片反轉"))
            
            if vision_fix == "強制黑底":
                black_bg = Image.new("RGBA", img.size, (0, 0, 0, 255))
                black_bg.alpha_composite(img)
                img = black_bg
            elif vision_fix == "負片反轉":
                r, g, b, a = img.split()
                rgb_img = Image.merge('RGB', (r, g, b))
                img = Image.merge('RGBA', ImageOps.invert(rgb_img).split() + (a,))

            st.divider()
            # 解除縮放限制，最高可放大至 300%
            scale_pct = st.slider("🔧 畫布尺寸放大倍率 (%) - 越大越能看清細節", min_value=50, max_value=300, value=100, step=10)
            
            calc_w = int(img.width * (scale_pct / 100.0))
            calc_h = int(img.height * (scale_pct / 100.0))
            final_img = img.resize((calc_w, calc_h), Image.Resampling.LANCZOS)
            
            st.info(f"警告：當前畫布將高達 {calc_w} x {calc_h} 像素。生成後請使用網頁右側與下方的滾動軸尋找細節。")
            
            if st.button("✅ 確認解析度，生成巨型畫布", use_container_width=True):
                st.session_state.ready_to_draw = True
                st.success("巨型畫布已生成！請前往『🖌️ 3. 巨型畫布標註與輸出』。")
                
        with col2:
            st.subheader("全局預覽圖 (非實際畫布大小)")
            st.image(final_img, use_column_width=True)

# ==========================================
# 🖌️ 第三區塊：巨型畫布標註與輸出
# ==========================================
with tab_canvas:
    if img is not None and st.session_state.ready_to_draw:
        # 將工具列移至上方，讓畫布佔滿整個螢幕寬度
        st.subheader("🖌️ 工具列")
        t_col1, t_col2, t_col3 = st.columns(3)
        with t_col1:
            drawing_mode = st.selectbox("筆刷模式", ("freedraw (自由手寫代替打字)", "line", "rect", "circle", "transform"))
        with t_col2:
            stroke_color = st.color_picker("顏色", "#FF0000")
        with t_col3:
            stroke_width = st.slider("粗細", 1, 25, 5)
            
        st.info("💡 提示：若畫布超出螢幕，請使用網頁邊緣的滾動軸來尋找工程細節。無法直接打字，請使用 freedraw 手寫或畫框。")
        
        # 建立無寬度限制的畫布
        canvas_result = st_canvas(
            fill_color="rgba(255, 255, 0, 0.3)", 
            stroke_width=stroke_width,
            stroke_color=stroke_color,
            background_image=final_img,
            height=final_img.height,
            width=final_img.width,
            drawing_mode=drawing_mode.split(" ")[0],
            key="engineering_canvas",
        )

        st.divider()
        st.subheader("📤 成果匯出區")
        if canvas_result.image_data is not None:
            out_col1, out_col2 = st.columns(2)
            
            draw_img = Image.fromarray(canvas_result.image_data.astype('uint8'), 'RGBA')
            bg_img = final_img.convert("RGBA")
            bg_img.alpha_composite(draw_img)
            png_output = io.BytesIO()
            bg_img.convert("RGB").save(png_output, format='PNG')
            
            with out_col1:
                st.download_button("📥 1. 下載 PNG 審閱圖 (Email 夾檔)", png_output.getvalue(), f"Review_{uploaded_file.name}.png", "image/png")
            
            with out_col2:
                dxf_doc = ezdxf.new('R2010')
                msp = dxf_doc.modelspace()
                c_h = final_img.height
                if canvas_result.json_data and "objects" in canvas_result.json_data:
                    for obj in canvas_result.json_data["objects"]:
                        def t_y(y): return c_h - y
                        try:
                            if obj["type"] == "line":
                                msp.add_line((obj["x1"], t_y(obj["y1"])), (obj["x2"], t_y(obj["y2"])))
                            elif obj["type"] == "rect":
                                x, y, w, h = obj["left"], obj["top"], obj["width"], obj["height"]
                                msp.add_lwpolyline([(x, t_y(y)), (x+w, t_y(y)), (x+w, t_y(y+h)), (x, t_y(y+h))], close=True)
                            elif obj["type"] == "circle":
                                msp.add_circle((obj["left"] + obj["radius"], t_y(obj["top"] + obj["radius"])), radius=obj["radius"])
                        except: pass
                dxf_output = io.StringIO()
                dxf_doc.write(dxf_output)
                st.download_button("📐 2. 下載 DXF 標註圖層 (CAD 疊圖)", dxf_output.getvalue(), f"Markup_{uploaded_file.name}.dxf", "application/dxf")
