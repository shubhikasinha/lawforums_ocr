from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from paddleocr import PaddleOCR
from pdf2image import convert_from_bytes
import fitz  # PyMuPDF
import tempfile, os, re

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

def extract_with_paddleocr(pdf_bytes):
    pages = convert_from_bytes(pdf_bytes)
    temp_dir = tempfile.mkdtemp()
    ocr_text = ""

    for i, page in enumerate(pages):
        img_path = os.path.join(temp_dir, f"page_{i}.jpg")
        page.save(img_path, "JPEG")

        result = ocr.ocr(img_path, cls=True)
        for line in result[0]:
            ocr_text += line[1][0] + "\n"

        os.remove(img_path)
    return ocr_text.strip()

@app.post("/extract")
async def extract_text(file: UploadFile = File(...)):
    pdf_bytes = await file.read()

    text = extract_with_pymupdf(pdf_bytes)
    if len(text.strip()) < 100:
        text = extract_with_paddleocr(pdf_bytes)

    formatted = clean_text(text)
    return {"text": formatted}

@app.get("/")
def root():
    return {"message": "OCR Backend is running!"}