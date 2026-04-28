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
st.set_page_config(page_title="工程圖審查系統 V2.0", layout="wide", initial_sidebar_state="expanded")
st.title("🐑 英俊的小羊：工程圖面審查與標註系統 V2.0 (專業流程版)")
st.markdown("---")

# 初始化 Session State (狀態管理，用於控制「確認按鈕」流程)
if 'ready_to_draw' not in st.session_state:
    st.session_state.ready_to_draw = False

# --- 2. 側邊欄：API 與系統狀態 ---
with st.sidebar:
    st.header("⚙️ 系統核心設定")
    owner_api_key = st.secrets.get("CLOUCCONVERT_API_KEY", None)
    user_api_key = st.text_input("輸入 CloudConvert API Key (訪客專用)", type="password")
    final_api_key = user_api_key if user_api_key else owner_api_key
    
    st.divider()
    st.markdown("### 支援的工程格式")
    st.info("原生支援: PDF, PNG, JPG, TIFF, BMP\n\n雲端運算 (需API): DWG, DXF, DWF")

# --- 3. 主畫面分頁結構 (上/下流程設計) ---
tab_input, tab_preview, tab_canvas = st.tabs(["📥 1. 輸入與解析", "🔍 2. 預覽與調控", "🖌️ 3. 標註與輸出"])

img = None 
pdf_stream = None 

# ==========================================
# 📥 第一區塊：輸入與解析 (Top)
# ==========================================
with tab_input:
    st.subheader("請上傳工程圖紙")
    uploaded_file = st.file_uploader("", type=["pdf", "dwg", "dxf", "dwf", "png", "jpg", "jpeg", "tiff", "bmp"])
    
    if uploaded_file is not None:
        file_ext = uploaded_file.name.split('.')[-1].lower()
        
        # 雲端運算格式群組 (DWG, DXF, DWF)
        if file_ext in ["dwg", "dxf", "dwf"]:
            if not final_api_key:
                st.error("❌ 缺少 API Key，無法解析 CAD 格式。")
            else:
                with st.spinner(f"🔄 雲端引擎正在將 {file_ext.upper()} 轉換為標準圖層，請耐心等候..."):
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
                            st.success(f"✅ {file_ext.upper()} 解析成功！請前往「預覽與調控」頁籤。")
                        else:
                            st.error("❌ 轉換失敗：檔案可能包含不支持的 3D 數據或結構損壞。")
                    except Exception as e:
                        st.error(f"❌ 雲端引擎錯誤：{str(e)}。請確認 API 額度。")
        
        # 原生 PDF 處理
        elif file_ext == "pdf":
            pdf_stream = uploaded_file
            st.success("✅ PDF 載入成功！")
            
        # 圖片格式群組處理
        elif file_ext in ["png", "jpg", "jpeg", "tiff", "bmp"]:
            img = Image.open(uploaded_file).convert("RGBA")
            st.success(f"✅ {file_ext.upper()} 圖片載入成功！")

        # PDF 光柵化運算
        if pdf_stream is not None:
            try:
                doc = fitz.open(stream=pdf_stream.read(), filetype="pdf")
                total_pages = doc.page_count
                selected_page = st.number_input(f"選擇頁面 (總頁數: {total_pages})", min_value=1, max_value=total_pages, value=1)
                page = doc.load_page(selected_page - 1)
                pix = page.get_pixmap(dpi=150, alpha=True)
                img = Image.frombytes("RGBA", [pix.width, pix.height], pix.samples)
            except Exception as e:
                st.error(f"❌ PDF 解析失敗，檔案可能已加密或損壞：{str(e)}")

# ==========================================
# 🔍 第二區塊：預覽與調控 (Middle)
# ==========================================
with tab_preview:
    if img is not None:
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.subheader("參數調控面板")
            # 1. 視覺修復選項
            vision_fix = st.radio(
                "光學對比修正 (若圖紙一片白請調整):",
                ("預設模式", "強制黑底 (針對透明底)", "負片反轉 (針對白底白線)")
            )
            
            if vision_fix == "強制黑底 (針對透明底)":
                black_bg = Image.new("RGBA", img.size, (0, 0, 0, 255))
                black_bg.alpha_composite(img)
                img = black_bg
            elif vision_fix == "負片反轉 (針對白底白線)":
                r, g, b, a = img.split()
                rgb_img = Image.merge('RGB', (r, g, b))
                img = Image.merge('RGBA', ImageOps.invert(rgb_img).split() + (a,))

            # 2. 比例縮放 (%) 控制器
            st.divider()
            scale_pct = st.slider("畫布縮放比例 (%) - 決定標註時的大小", min_value=10, max_value=200, value=100, step=10)
            
            # 矩陣縮放運算
            calc_w = int(img.width * (scale_pct / 100.0))
            calc_h = int(img.height * (scale_pct / 100.0))
            final_img = img.resize((calc_w, calc_h), Image.Resampling.LANCZOS)
            
            st.info(f"當前畫布物理尺寸: {calc_w} x {calc_h} 像素")
            
            # 3. 狀態鎖定確認鈕
            if st.button("✅ 確認預覽無誤，鎖定並生成標註畫布", use_container_width=True):
                st.session_state.ready_to_draw = True
                st.success("畫布已生成！請點擊上方『🖌️ 3. 標註與輸出』頁籤進入作業。")
                
        with col2:
            st.subheader("即時視覺預覽區")
            # 純預覽，非畫布，僅供確認位置與清晰度
            st.image(final_img, caption="調控結果預覽", use_column_width=True)
    else:
        st.info("請先於「📥 1. 輸入與解析」完成檔案上傳。")

# ==========================================
# 🖌️ 第三區塊：標註與輸出 (Bottom)
# ==========================================
with tab_canvas:
    if img is not None and st.session_state.ready_to_draw:
        col_tool, col_canvas = st.columns([1, 4])
        
        with col_tool:
            st.subheader("標註工具")
            drawing_mode = st.selectbox("筆刷模式", ("freedraw", "line", "rect", "circle", "transform"))
            stroke_color = st.color_picker("顏色", "#FF0000")
            stroke_width = st.slider("粗細", 1, 20, 3)
            
        with col_canvas:
            st.subheader("作業畫布")
            canvas_result = st_canvas(
                fill_color="rgba(255, 255, 0, 0.3)", 
                stroke_width=stroke_width,
                stroke_color=stroke_color,
                background_image=final_img,  # 使用縮放後的 final_img
                height=final_img.height,
                width=final_img.width,
                drawing_mode=drawing_mode,
                key="engineering_canvas",
            )

        # --- 清晰成列的輸出選單 ---
        st.divider()
        st.subheader("📤 成果匯出區")
        if canvas_result.image_data is not None:
            out_col1, out_col2 = st.columns(2)
            
            # 運算PNG
            draw_img = Image.fromarray(canvas_result.image_data.astype('uint8'), 'RGBA')
            bg_img = final_img.convert("RGBA")
            bg_img.alpha_composite(draw_img)
            png_output = io.BytesIO()
            bg_img.convert("RGB").save(png_output, format='PNG')
            
            with out_col1:
                st.markdown("#### 1. 一般溝通格式")
                st.download_button("📥 下載 PNG 審閱圖 (適合 Email/Line 溝通)", png_output.getvalue(), f"Review_{uploaded_file.name}.png", "image/png")
            
            # 運算DXF
            with out_col2:
                st.markdown("#### 2. 工程專業格式")
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
                st.download_button("📐 下載 DXF 標註圖層 (適合疊加進 AutoCAD)", dxf_output.getvalue(), f"Markup_{uploaded_file.name}.dxf", "application/dxf")
    else:
        st.info("請先在「🔍 2. 預覽與調控」頁籤中調整完畢，並按下『確認鎖定』按鈕。")
