import io
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from docx import Document
import fitz  # PyMuPDF
from paddleocr import PaddleOCR
import numpy as np
import cv2
import uuid
import asyncio
import json
from threading import Lock

# --- App Initialization ---


# Global OCR variable
ocr = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load model on startup
    global ocr
    print("Loading PaddleOCR models... This may take a moment.")
    # We run this in a thread to avoid blocking the event loop potentially, 
    # though it needs to happen before requests.
    # Actually, for Koyeb health checks, it's better if we start FAST and load later?
    # No, we'll load it here.
    ocr = PaddleOCR(use_angle_cls=True, lang='en')
    print("PaddleOCR models loaded successfully.")
    yield
    # Cleanup if needed
    print("Shutting down...")

app = FastAPI(title="Advanced OCR Backend", lifespan=lifespan)



# --- Pydantic Models ---

class TextItem(BaseModel):
    """Pydantic model for receiving text data in request body."""
    text: str

# --- Helper Functions ---

def sort_text_blocks(blocks):
    """
    Sorts PyMuPDF text blocks in reading order (top-to-bottom, left-to-right).
    Blocks are tuples: (x0, y0, x1, y1, text, block_no, block_type)
    """
    return sorted(blocks, key=lambda b: (b[1], b[0]))


def run_ocr_on_image(img: np.ndarray) -> str:
    """
    Run PaddleOCR on an image array and return extracted text.
    Handles PaddleOCR 3.x output format (dict with 'rec_texts' key).
    """
    try:
        if img is None:
            print("DEBUG: Image is None!")
            return ""
        
        print(f"DEBUG: Image shape = {img.shape}, dtype = {img.dtype}")
        
        # Call ocr method
        result = ocr.ocr(img)
        
        if result is None:
            print("DEBUG: OCR returned None")
            return ""
        
        lines = []
        
        # PaddleOCR 3.x returns: [{'rec_texts': [...], 'rec_scores': [...], ...}]
        # It's a list containing one dictionary per page
        
        if isinstance(result, list):
            for item in result:
                # PaddleOCR 3.x format: item is a dict with 'rec_texts' key
                if isinstance(item, dict):
                    rec_texts = item.get('rec_texts', [])
                    if rec_texts:
                        lines.extend(rec_texts)
                        print(f"DEBUG: Found {len(rec_texts)} text lines from rec_texts")
                
                # Old PaddleOCR 2.x format: item is a list of [box, (text, score)]
                elif isinstance(item, list):
                    for line_data in item:
                        if isinstance(line_data, (list, tuple)) and len(line_data) >= 2:
                            text_part = line_data[1]
                            if isinstance(text_part, (list, tuple)) and len(text_part) >= 1:
                                text = str(text_part[0])
                                if text.strip():
                                    lines.append(text)
                            elif isinstance(text_part, str) and text_part.strip():
                                lines.append(text_part)
        
        final_text = "\n".join(lines)
        print(f"DEBUG: Total lines extracted: {len(lines)}")
        return final_text
        
    except Exception as e:
        print(f"OCR error: {e}")
        traceback.print_exc()
        return ""


def preprocess_image_minimal(img: np.ndarray) -> np.ndarray:
    """
    Minimal preprocessing that doesn't damage handwritten text.
    Just ensures proper format and does light cleanup.
    """
    if img is None:
        return None
    
    # If already 3-channel BGR, return as is
    if len(img.shape) == 3 and img.shape[2] == 3:
        return img
    
    # If grayscale, convert to BGR
    if len(img.shape) == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    
    # If RGBA, convert to BGR
    if len(img.shape) == 3 and img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
    
    return img


def decode_image_bytes(image_bytes: bytes) -> np.ndarray:
    """Decode image bytes to numpy array."""
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        return img
    except Exception as e:
        print(f"Image decode error: {e}")
        return None


def process_digital_pdf(file_bytes: bytes) -> str:
    """
    Extracts text from a digitally-native PDF, preserving layout.
    """
    all_page_texts = []
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            for page in doc:
                blocks = page.get_text("blocks")
                sorted_blocks = sort_text_blocks(blocks)
                page_text = "\n".join([b[4].strip() for b in sorted_blocks if b[4].strip()])
                all_page_texts.append(page_text)
                
    except Exception as e:
        print("--- ERROR IN process_digital_pdf ---")
        traceback.print_exc()
        print("--------------------------------------")
        return ""
            
    return "\n\n".join(all_page_texts)


# --- Job queue / progress tracking ---

# In-memory job store: job_id -> {status, progress, result, error, file_bytes}
job_store = {}
job_store_lock = Lock()


def process_file_sync(job_id: str, file_bytes: bytes, content_type: str):
    """Synchronous worker that does OCR and updates job_store. Intended to run in a thread."""
    try:
        with job_store_lock:
            job_store[job_id]["status"] = "processing"
            job_store[job_id]["progress"] = 0

        text = ""
        
        if content_type == "application/pdf":
            # Try digital extraction first
            try:
                with fitz.open(stream=file_bytes, filetype="pdf") as doc:
                    pages = len(doc)
                    digital_text = ""
                    
                    for i, page in enumerate(doc):
                        # Extract digital text
                        blocks = page.get_text("blocks")
                        sorted_blocks = sort_text_blocks(blocks)
                        page_text = "\n".join([b[4].strip() for b in sorted_blocks if b[4].strip()])
                        if page_text.strip():
                            digital_text += page_text + "\n\n"
                        with job_store_lock:
                            job_store[job_id]["progress"] = int(((i + 1) / pages) * 50)

                    # If digital text is too short, it's likely a scanned PDF
                    if len(digital_text.strip()) < 50:
                        print(f"Scanned PDF detected, running OCR on {pages} pages...")
                        text = ""
                        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
                            for i, page in enumerate(doc):
                                # Render page as high-res image
                                pix = page.get_pixmap(dpi=300)  # Higher DPI for better OCR
                                
                                # Convert to numpy array directly
                                img_data = pix.samples
                                img = np.frombuffer(img_data, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                                
                                # Convert to BGR if needed
                                if pix.n == 4:  # RGBA
                                    img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
                                elif pix.n == 1:  # Grayscale
                                    img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
                                elif pix.n == 3:  # RGB
                                    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
                                
                                # Run OCR
                                page_text = run_ocr_on_image(img)
                                if page_text:
                                    text += f"--- Page {i+1} ---\n{page_text}\n\n"
                                
                                with job_store_lock:
                                    job_store[job_id]["progress"] = 50 + int(((i + 1) / pages) * 50)
                    else:
                        text = digital_text
                        
            except Exception as e:
                print(f"PDF processing error: {e}")
                traceback.print_exc()
                with job_store_lock:
                    job_store[job_id]["error"] = f"Failed processing PDF: {str(e)}"
                    job_store[job_id]["status"] = "error"
                return

        elif content_type and content_type.startswith("image/"):
            try:
                print(f"Processing image with content type: {content_type}")
                
                # Decode image
                img = decode_image_bytes(file_bytes)
                if img is None:
                    raise Exception("Failed to decode image")
                
                print(f"Image shape: {img.shape}")
                
                # Ensure proper format
                img = preprocess_image_minimal(img)
                
                # Run OCR
                text = run_ocr_on_image(img)
                
                print(f"Extracted text length: {len(text)}")
                
                with job_store_lock:
                    job_store[job_id]["progress"] = 100
                    
            except Exception as e:
                print(f"Image processing error: {e}")
                traceback.print_exc()
                with job_store_lock:
                    job_store[job_id]["error"] = f"Failed processing image: {str(e)}"
                    job_store[job_id]["status"] = "error"
                return

        else:
            with job_store_lock:
                job_store[job_id]["error"] = "Unsupported file type"
                job_store[job_id]["status"] = "error"
            return

        with job_store_lock:
            job_store[job_id]["result"] = text if text.strip() else "No text could be extracted from this image."
            job_store[job_id]["status"] = "finished"
            job_store[job_id]["progress"] = 100

    except Exception as e:
        print(f"Unexpected error in process_file_sync: {e}")
        traceback.print_exc()
        with job_store_lock:
            job_store[job_id]["error"] = f"Unexpected error: {str(e)}"
            job_store[job_id]["status"] = "error"


# --- API Endpoints ---

@app.get("/")
async def read_index():
    return FileResponse('static/index.html')

app.mount("/", StaticFiles(directory="static", html=True), name="static")

@app.post("/extract-text")
async def extract_text(file: UploadFile = File(...)):
    """
    Accepts upload and starts background OCR job. Returns a job_id.
    File is processed in-memory. No disk writes.
    """
    # Validate content type
    if not (file.content_type == "application/pdf" or (file.content_type and file.content_type.startswith("image/"))):
        raise HTTPException(status_code=415, detail="Unsupported file type. Please upload a PDF or image.")

    job_id = str(uuid.uuid4())

    # Read file into memory
    try:
        file_bytes = await file.read()
        if not file_bytes:
            raise Exception("Empty file")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")

    # Initialize job entry
    with job_store_lock:
        job_store[job_id] = {
            "status": "queued",
            "progress": 0,
            "result": None,
            "error": None,
            "content_type": file.content_type,
        }

    # Start background processing in a thread
    asyncio.create_task(asyncio.to_thread(process_file_sync, job_id, file_bytes, file.content_type))

    return {"job_id": job_id}


@app.get("/progress/{job_id}")
async def progress_stream(job_id: str):
    """SSE endpoint streaming progress updates for a job."""
    with job_store_lock:
        if job_id not in job_store:
            raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        last_progress = -1
        max_attempts = 600  # 5 mins at 0.5s intervals
        attempts = 0
        
        while attempts < max_attempts:
            with job_store_lock:
                job = job_store.get(job_id, {})
                status = job.get("status")
                progress = job.get("progress", 0)
                error = job.get("error")

            if progress != last_progress or status in ("finished", "error"):
                data = {"status": status, "progress": progress, "error": error}
                yield f"data: {json.dumps(data)}\n\n"
                last_progress = progress

            if status in ("finished", "error"):
                break

            await asyncio.sleep(0.5)
            attempts += 1

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


@app.get("/result/{job_id}")
async def get_result(job_id: str):
    with job_store_lock:
        job = job_store.get(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") == "finished":
        return {"text": job.get("result")}
    elif job.get("status") == "error":
        raise HTTPException(status_code=500, detail=job.get("error") or "Processing error")
    else:
        return {"status": job.get("status"), "progress": job.get("progress")}

@app.post("/download-docx")
async def download_docx(item: TextItem):
    """
    Converts extracted text to a .docx file and returns it for download.
    """
    try:
        document = Document()
        document.add_paragraph(item.text)
        
        # Save document to a byte stream
        file_stream = io.BytesIO()
        document.save(file_stream)
        file_stream.seek(0)
        
        return StreamingResponse(
            file_stream,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": "attachment; filename=extracted_text.docx"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating DOCX file: {e}")

@app.post("/download-txt")
async def download_txt(item: TextItem):
    """
    Converts extracted text to a .txt file and returns it for download.
    """
    try:
        # Convert text to bytes
        file_bytes = item.text.encode('utf-8')
        file_stream = io.BytesIO(file_bytes)
        file_stream.seek(0)
        
        return StreamingResponse(
            file_stream,
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=extracted_text.txt"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating TXT file: {e}")

if __name__ == "__main__":
    import uvicorn
    print("Starting server at http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)