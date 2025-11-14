from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse
from paddleocr import PaddleOCR
from pdf2image import convert_from_bytes
import fitz  # PyMuPDF
import tempfile, os, re, io
from docx import Document

app = FastAPI()

# Allow React frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize OCR
ocr = PaddleOCR(use_angle_cls=True, lang='en')

def clean_text(text):
    text = text.replace('\n\n', '\n')
    text = re.sub(r'(?<![.?!])\n', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_with_pymupdf(pdf_bytes):
    text = ""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            text += page.get_text("text") + "\n"
    return text.strip()

# Refactored function to run OCR on a list of image paths
def run_ocr_on_images(image_paths):
    ocr_text = ""
    for img_path in image_paths:
        result = ocr.ocr(img_path, cls=True)
        if result and result[0]:  # Check if ocr result is not None
            for line in result[0]:
                ocr_text += line[1][0] + "\n"
        os.remove(img_path)  # Clean up temp image
    return ocr_text.strip()

@app.post("/extract")
async def extract_text(file: UploadFile = File(...)):
    file_bytes = await file.read()
    text = ""
    temp_dir = tempfile.mkdtemp()

    try:
        if file.content_type == "application/pdf":
            # 1. Try text extraction first
            text = extract_with_pymupdf(file_bytes)

            # 2. If not much text, assume scanned PDF and run OCR
            if len(text.strip()) < 100:
                try:
                    pages = convert_from_bytes(file_bytes)
                    image_paths = []
                    for i, page in enumerate(pages):
                        img_path = os.path.join(temp_dir, f"page_{i}.jpg")
                        page.save(img_path, "JPEG")
                        image_paths.append(img_path)

                    text = run_ocr_on_images(image_paths)
                except Exception as e:
                    print(f"pdf2image OCR failed: {e}")
                    if not text: # If text is still empty
                        raise HTTPException(status_code=500, detail=f"PDF OCR failed. Is Poppler installed? Error: {e}")
                    # If PyMuPDF found *some* text, just use that.

        elif file.content_type in ["image/jpeg", "image/png", "image/bmp", "image/webp"]:
            # 3. Handle image files directly
            img_path = os.path.join(temp_dir, file.filename)
            with open(img_path, "wb") as f:
                f.write(file_bytes)

            text = run_ocr_on_images([img_path])

        else:
            raise HTTPException(status_code=415, detail="Unsupported file type. Please upload a PDF or image.")

        if not text:
            text = "No extractable text found."

        # 4. Clean text and create Word document
        formatted = clean_text(text)
        document = Document()
        document.add_paragraph(formatted)

        # 5. Save to memory stream
        f_stream = io.BytesIO()
        document.save(f_stream)
        f_stream.seek(0)

        return StreamingResponse(
            f_stream,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f"attachment; filename=extracted_text.docx"
            }
        )

    except Exception as e:
        print(f"Error in /extract: {e}")
        # Clean up temp directory on error
        if os.path.exists(temp_dir):
            try:
                for f in os.listdir(temp_dir):
                    os.remove(os.path.join(temp_dir, f))
            except:
                pass
            os.rmdir(temp_dir)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up temp directory
        if os.path.exists(temp_dir) and not any(os.listdir(temp_dir)):
            os.rmdir(temp_dir)


@app.get("/")
def root():
    return {"message": "OCR Backend is running!"}