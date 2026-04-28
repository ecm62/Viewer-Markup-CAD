import streamlit as st
import fitz  # PyMuPDF 套件，用於處理 PDF
from streamlit_drawable_canvas import st_canvas
from PIL import Image

# 1. 系統介面與名稱設定
st.set_page_config(page_title="英俊的小羊 - 工程圖審查系統", layout="wide")
st.title("🐑 英俊的小羊系列：工程圖面審查與標註系統 V1.0")
st.markdown("---")

# 2. 檔案上傳區塊
uploaded_file = st.file_uploader("請上傳需要審查的工程圖 (僅限 PDF 格式)", type=["pdf"])

if uploaded_file is not None:
    # 3. PDF 轉換為圖片運算 
    # (物理限制因果：前端網頁畫布只能在像素圖片上作畫，無法直接疊加於 PDF 向量檔上，因此必須先進行轉換)
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    page = doc.load_page(0) # 預設讀取第一頁
    pix = page.get_pixmap(dpi=150) # 設定解析度以確保圖紙清晰
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

    st.success("圖檔讀取成功！請在左側工具列調整參數，並直接在圖面上進行標註。")

    # 4. 側邊欄：畫筆工具與參數設定
    st.sidebar.header("標註工具設定")
    drawing_mode = st.sidebar.selectbox("繪圖模式", ("freedraw (自由畫筆)", "line (直線)", "rect (矩形方框)", "circle (圓形)", "transform (選取與移動)"))
    
    # 擷取括號前的英文指令給系統讀取
    mode_command = drawing_mode.split(" ")[0] 
    
    stroke_color = st.sidebar.color_picker("畫筆顏色 (亮色系)", "#FF0000") # 預設為高亮紅色
    stroke_width = st.sidebar.slider("畫筆粗細", 1, 25, 3)

    # 5. 建立繪圖畫布層 (Canvas Overlay)
    st_canvas(
        fill_color="rgba(255, 255, 0, 0.3)",  # 幾何圖形內部填充顏色 (半透明黃色)
        stroke_width=stroke_width,
        stroke_color=stroke_color,
        background_image=img,
        update_streamlit=True,
        height=pix.height,
        width=pix.width,
        drawing_mode=mode_command,
        key="canvas",
    )
    
    st.info("提示：標註完成後，請將游標移至畫布上，使用右下角出現的圖片按鈕將結果下載，即可回傳發包。")
