import io
import os
import tempfile
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse
from pydantic import BaseModel
from docx import Document
import fitz  # PyMuPDF
from paddleocr import PaddleOCR

# --- Configuration ---

# Initialize PaddleOCR
# This will download models on first run
print("Loading PaddleOCR models...")
ocr = PaddleOCR(use_angle_cls=True, lang='en')
print("PaddleOCR models loaded.")

app = FastAPI(title="Advanced OCR Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# --- Pydantic Models ---

class TextItem(BaseModel):
    """Pydantic model for receiving text data in request body."""
    text: str

# --- Helper Functions ---

def process_digital_pdf(file_bytes: bytes) -> str:
    """
    Extracts text from a digitally-native PDF, preserving layout.
    """
    text_blocks = []
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            for page in doc:
                # 'sort=True' is key for preserving reading order
                text_blocks.append(page.get_text("text", sort=True))
    except Exception as e:
        print(f"Error processing digital PDF: {e}")
        return ""
    return "\n\n".join(text_blocks)

def process_scanned_pdf(file_bytes: bytes) -> str:
    """
    Converts a scanned PDF to images and runs OCR on each page.
    """
    all_page_texts = []
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            for page_num, page in enumerate(doc):
                print(f"Processing scanned PDF page: {page_num + 1}/{len(doc)}")
                # Use DPI 200 for a good balance of quality and speed
                pix = page.get_pixmap(dpi=200)
                img_bytes = pix.tobytes("jpg")
                
                # Run OCR on the image bytes
                # --- FIX ---
                # Removed 'cls=True' as it's an invalid argument for this method
                result = ocr.ocr(img_bytes)
                # --- END FIX ---
                
                if result and result[0]:
                    lines = [line[1][0] for line in result[0]]
                    all_page_texts.append("\n".join(lines))
    except Exception as e:
        print(f"Error processing scanned PDF: {e}")
        raise HTTPException(status_code=500, detail=f"PDF OCR failed: {e}")
    
    return "\n\n".join(all_page_texts)

def process_image(file_bytes: bytes) -> str:
    """
    Runs OCR on a single image.
    """
    try:
        print("Processing image file...")
        # --- FIX ---
        # Removed 'cls=True' as it's an invalid argument for this method
        result = ocr.ocr(file_bytes)
        # --- END FIX ---
        if result and result[0]:
            lines = [line[1][0] for line in result[0]]
            return "\n".join(lines)
    except Exception as e:
        print(f"Error processing image: {e}")
        raise HTTPException(status_code=500, detail=f"Image OCR failed: {e}")
    return ""

# --- API Endpoints ---

@app.get("/")
def read_root():
    return {"message": "Advanced OCR Backend is running. POST to /extract-text to process files."}

@app.post("/extract-text")
async def extract_text(file: UploadFile = File(...)):
    """
    The main endpoint to upload and process a file.
    It intelligently decides whether to use digital extraction or OCR.
    
    WARNING: This is a synchronous, blocking endpoint.
    Large files WILL cause a timeout.
    """
    if not file.content_type:
        raise HTTPException(status_code=400, detail="Could not determine file type.")

    print(f"Received file: {file.filename}, Type: {file.content_type}")
    
    # Read file bytes into memory
    # WARNING: This is the bottleneck for large files.
    try:
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="File is empty.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {e}")

    final_text = ""

    if file.content_type == "application/pdf":
        # 1. First, try digital extraction
        final_text = process_digital_pdf(file_bytes)
        
        # 2. If it's a scanned PDF (little/no text), run OCR
        # --- FIX ---
        # We changed 100 to 20. We only run slow OCR if the page
        # is TRULY empty, not just "short".
        if len(final_text.strip()) < 20:
        # --- END FIX ---
            print("PDF has little text. Assuming scanned. Running OCR...")
            final_text = process_scanned_pdf(file_bytes)
    
    elif file.content_type in ["image/jpeg", "image/png", "image/bmp", "image/webp"]:
        # 3. Handle image files
        final_text = process_image(file_bytes)
        
    else:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {file.content_type}")

    if not final_text:
        final_text = "No extractable text found."
        
    return {"text": final_text}

@app.post("/download-docx")
async def download_docx(item: TextItem):
    """
    Converts a plain text string (sent in JSON) to a .docx file.
    This is much more efficient than re-processing the file.
    """
    try:
        text = item.text
        document = Document()
        document.add_heading('Extracted Text', 0)
        
        # Preserve paragraphs
        # We assume paragraphs are separated by double newlines
        paragraphs = text.split('\n\n')
        for para in paragraphs:
            # Add each line as a new paragraph
            # This handles single newlines as line breaks
            lines = para.split('\n')
            p = document.add_paragraph()
            for i, line in enumerate(lines):
                p.add_run(line)
                if i < len(lines) - 1:
                    p.add_run().add_break()

        # Save to a virtual file in memory
        f_stream = io.BytesIO()
        document.save(f_stream)
        f_stream.seek(0)
        
        return StreamingResponse(
            f_stream,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": "attachment; filename=extracted_text.docx"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating .docx file: {e}")

@app.post("/download-txt")
async def download_txt(item: TextItem):
    """
    Converts a plain text string (sent in JSON) to a .txt file.
    """
    try:
        text_bytes = item.text.encode('utf-8')
        f_stream = io.BytesIO(text_bytes)
        
        return StreamingResponse(
            f_stream,
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=extracted_text.txt"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating .txt file: {e}")

if __name__ == "__main__":
    import uvicorn
    # This is for development. For production, use a proper Gunicorn/Uvicorn command.
    # Make sure to use 127.0.0.1 for the host to avoid firewall popups
    uvicorn.run(app, host="127.0.0.1", port=8000)