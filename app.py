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
st.title("🐑 英俊的小羊系列：工程圖面審查與標註系統 V1.3 穩定版")
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
                    
                    # 動態尋找「上傳」任務 (防呆：不依賴陣列順序)
                    upload_task = next(task for task in job['tasks'] if task['name'] == 'import-file')
                    
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".dwg") as tmp:
                        tmp.write(uploaded_file.getvalue())
                        tmp_path = tmp.name
                        
                    cloudconvert.Task.upload(file_name=tmp_path, task=upload_task)
                    os.remove(tmp_path) # 上傳完畢後刪除暫存檔
                    
                    # 等待伺服器運算完成
                    job = cloudconvert.Job.wait(id=job['id'])
                    
                    # 動態尋找「匯出」任務，並加入嚴格的防呆判定
                    export_task = next((task for task in job['tasks'] if task['name'] == 'export-file'), None)
                    
                    if export_task is None or export_task.get('status') == 'error':
                        raise Exception("雲端引擎回報錯誤，可能是此 DWG 檔案格式不支援或已損壞。")
                        
                    if 'result' not in export_task or 'files' not in export_task['result']:
                        raise Exception("伺服器未產生有效的下載連結。")
                    
                    # 下載轉換好的 PDF 到記憶體中
                    file_url = export_task['result']['files'][0]['url']
                    response = requests.get(file_url)
                    pdf_stream = io.BytesIO(response.content)
                    st.success("✅ DWG 轉換成功！")
                    
                except Exception as e:
                    st.error(f"❌ 轉換失敗。錯誤細節：{str(e)}")

    # 邏輯分支 B：直接處理原生 PDF
    elif file_ext == "pdf":
        pdf_stream = uploaded_file

    # --- 4. 影像光柵化與分頁控制器 ---
    if pdf_stream is not None:
        try:
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
        except Exception as e:
            st.error(f"❌ PDF 讀取失敗。錯誤細節：{str(e)}")
        
    # 邏輯分支 C：處理一般圖片
    elif file_ext in ["png", "jpg", "jpeg"]:
        try:
            img = Image.open(uploaded_file)
        except Exception as e:
            st.error(f"❌ 圖片讀取失敗。錯誤細節：{str(e)}")
        
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

       # --- 6. 專業防呆與雙格式匯出 (PNG + DXF) ---
        st.markdown("---")
        st.write("### 📥 匯出結果")
        
        if canvas_result.image_data is not None:
            # === 第一部分：生成 PNG 預覽圖 (平面的像素結果) ===
            drawing_layer = Image.fromarray(canvas_result.image_data.astype('uint8'), 'RGBA')
            merged_img = img.convert("RGBA")
            merged_img.alpha_composite(drawing_layer)
            merged_img = merged_img.convert("RGB")
            
            img_byte_arr = io.BytesIO()
            merged_img.save(img_byte_arr, format='PNG')
            png_data = img_byte_arr.getvalue()

            # === 第二部分：生成 DXF 可編輯標註圖層 (向量座標結果) ===
            import ezdxf
            dxf_doc = ezdxf.new('R2010') # 建立一個標準 CAD 檔案
            msp = dxf_doc.modelspace()
            
            # 讀取畫布背後的數學向量資料
            if canvas_result.json_data is not None and "objects" in canvas_result.json_data:
                canvas_h = img.height
                
                for obj in canvas_result.json_data["objects"]:
                    # Web 座標轉換為 CAD 座標 (Y軸反轉)
                    def to_cad_y(y): return canvas_h - y
                    
                    try:
                        if obj["type"] == "line":
                            msp.add_line(
                                (obj["x1"], to_cad_y(obj["y1"])), 
                                (obj["x2"], to_cad_y(obj["y2"]))
                            )
                        elif obj["type"] == "rect":
                            x, y = obj["left"], obj["top"]
                            w, h = obj["width"], obj["height"]
                            # 建立四個頂點並繪製矩形
                            pts = [(x, to_cad_y(y)), (x+w, to_cad_y(y)), (x+w, to_cad_y(y+h)), (x, to_cad_y(y+h))]
                            msp.add_lwpolyline(pts, close=True)
                        elif obj["type"] == "circle":
                            x, y = obj["left"] + obj["radius"], obj["top"] + obj["radius"]
                            msp.add_circle((x, to_cad_y(y)), radius=obj["radius"])
                    except Exception as e:
                        pass # 略過無法轉換的複雜自由曲線
            
            # 將 DXF 寫入記憶體準備下載
            dxf_byte_arr = io.BytesIO()
            dxf_doc.write(dxf_byte_arr)
            dxf_data = dxf_byte_arr.getvalue()

            # === 第三部分：前端下載按鈕介面 ===
            col1, col2 = st.columns(2)
            with col1:
                st.download_button(
                    label="✅ 1. 下載 PNG 預覽圖 (回傳確認用)",
                    data=png_data,
                    file_name=f"Reviewed_{uploaded_file.name}.png",
                    mime="image/png"
                )
            with col2:
                st.download_button(
                    label="📐 2. 下載 DXF 標註圖層 (供專業繪圖端編輯)",
                    data=dxf_data,
                    file_name=f"Markup_Layer_{uploaded_file.name}.dxf",
                    mime="application/dxf"
                )
                
            st.info("實務說明：DXF 格式能提取你畫的直線、矩形與圓形。自由畫筆(freedraw)因點位過於零碎，不寫入 CAD 中以避免圖紙產生雜訊。")
