from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse
from paddleocr import PaddleOCR
import fitz  # PyMuPDF
import tempfile, os, re, io
from docx import Document

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- FIX 1: CHANGE BACK ---
# Remove all extra arguments. This line is now correct.
ocr = PaddleOCR(use_angle_cls=True, lang='en')
# --- END OF FIX 1 ---

def extract_with_pymupdf(pdf_bytes):
    text = ""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            text += page.get_text("text", sort=True) + "\n\n" 
    return text.strip()

# This function is for OCR (scanned images)
def run_ocr_on_images(image_paths):
    ocr_text = ""
    for img_path in image_paths:
        
        # --- FIX 2: CHANGE BACK ---
        # Remove all extra arguments. This call is now correct.
        result = ocr.ocr(img_path)
        # --- END OF FIX 2 ---

        if result and result[0]:
            for line in result[0]:
                ocr_text += line[1][0] + "\n" 
        os.remove(img_path)
    return ocr_text.strip()

# This is the shared function that does all the work
async def get_extracted_text(file: UploadFile):
    file_bytes = await file.read()
    text = ""
    temp_dir = tempfile.mkdtemp()

    try:
        if file.content_type == "application/pdf":
            # 1. Try formatted text extraction first
            text = extract_with_pymupdf(file_bytes)

            # 2. If not much text, assume scanned PDF and run OCR
            if len(text.strip()) < 100:
                try:
                    doc = fitz.open(stream=file_bytes, filetype="pdf")
                    image_paths = []
                    for i, page in enumerate(doc):
                        
                        # --- FIX 3: THE REAL SOLUTION ---
                        # Use dpi=170 to create an image < 4000px
                        pix = page.get_pixmap(dpi=170) 
                        # --- END OF FIX 3 ---

                        img_path = os.path.join(temp_dir, f"page_{i}.jpg")
                        pix.save(img_path, "JPEG")
                        image_paths.append(img_path)
                    doc.close()
                    text = run_ocr_on_images(image_paths)
                except Exception as e:
                    if not text:
                        raise HTTPException(status_code=500, detail=f"PDF OCR failed: {e}")

        elif file.content_type in ["image/jpeg", "image/png", "image/bmp", "image/webp"]:
            # 3. Handle image files directly
            img_path = os.path.join(temp_dir, file.filename)
            with open(img_path, "wb") as f:
                f.write(file_bytes)
            text = run_ocr_on_images([img_path])
        else:
            raise HTTPException(status_code=415, detail="Unsupported file type.")

        if not text:
            text = "No extractable text found."
        
        return text

    except Exception as e:
        print(f"Error in get_extracted_text: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up temp files
        if os.path.exists(temp_dir):
            try:
                for f in os.listdir(temp_dir):
                    os.remove(os.path.join(temp_dir, f))
            except:
                pass
            os.rmdir(temp_dir)

# --- ENDPOINT 1: FOR VIEWING ONLINE ---
@app.post("/extract-text")
async def extract_text_endpoint(file: UploadFile = File(...)):
    text = await get_extracted_text(file)
    return {"text": text}

# --- ENDPOINT 2: FOR DOWNLOADING DOCX ---
@app.post("/extract-docx")
async def extract_docx_endpoint(file: UploadFile = File(...)):
    text = await get_extracted_text(file)
    
    # Create Word document in memory
    document = Document()
    document.add_paragraph(text)
    f_stream = io.BytesIO()
    document.save(f_stream)
    f_stream.seek(0)
    
    return StreamingResponse(
        f_stream,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename=extracted_text.docx"}
    )

@app.get("/")
def root():
    return {"message": "OCR Backend is running!"}