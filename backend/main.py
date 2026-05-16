"""
JWW Converter SaaS - FastAPI Backend
Handles JWW/DWG/DXF file conversion with security hardening.
"""

import asyncio
import logging
import os
import io
import re
import shutil
import time
import uuid
import zipfile
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from converter.parser import parse_dxf
from converter.mapper import map_entities
from converter.jww_exporter import export_optimized_dxf

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# --- Configuration ---
UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB per file
MAX_FILES_PER_BATCH = 20
FILE_TTL_SECONDS = 30 * 60  # 30 minutes - auto-delete after this
CLEANUP_INTERVAL_SECONDS = 5 * 60  # Run cleanup every 5 minutes
ALLOWED_EXTENSIONS = ('.dxf', '.dwg', '.jww')
RATE_LIMIT_UPLOADS_PER_MIN = 30
RATE_LIMIT_CONVERTS_PER_MIN = 20

# Valid file_id pattern (UUID only)
UUID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


# --- Rate Limiter ---
class RateLimiter:
    """Simple in-memory rate limiter by IP."""
    def __init__(self):
        self._requests = defaultdict(list)

    def check(self, key: str, limit: int, window: int = 60) -> bool:
        """Returns True if request is allowed."""
        now = time.time()
        self._requests[key] = [t for t in self._requests[key] if now - t < window]
        if len(self._requests[key]) >= limit:
            return False
        self._requests[key].append(now)
        return True

rate_limiter = RateLimiter()


# --- File Cleanup ---
async def cleanup_old_files():
    """Periodically delete files older than FILE_TTL_SECONDS."""
    while True:
        try:
            now = time.time()
            for directory in [UPLOAD_DIR, OUTPUT_DIR]:
                if not os.path.isdir(directory):
                    continue
                for filename in os.listdir(directory):
                    filepath = os.path.join(directory, filename)
                    try:
                        if os.path.isfile(filepath):
                            age = now - os.path.getmtime(filepath)
                            if age > FILE_TTL_SECONDS:
                                os.remove(filepath)
                                logger.debug(f"Cleaned up: {filepath}")
                    except OSError:
                        pass
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background cleanup task on startup."""
    task = asyncio.create_task(cleanup_old_files())
    yield
    task.cancel()


# --- App Setup ---
app = FastAPI(
    title="JWW Converter SaaS API",
    docs_url=None,  # Disable Swagger UI in production
    redoc_url=None,
    lifespan=lifespan,
)

# CORS - restrict in production
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


# Security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


# Serve frontend
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'frontend')
FRONTEND_DIR_DOCKER = os.path.join(os.path.dirname(__file__), 'frontend_static')
_frontend = FRONTEND_DIR if os.path.isdir(FRONTEND_DIR) else FRONTEND_DIR_DOCKER
if os.path.isdir(_frontend):
    app.mount("/app", StaticFiles(directory=_frontend, html=True), name="frontend")


# --- Validation Helpers ---
def validate_file_id(file_id: str) -> str:
    """Validate file_id is a proper UUID to prevent path traversal."""
    if not UUID_PATTERN.match(file_id):
        raise HTTPException(status_code=400, detail="無効なファイルIDです。")
    return file_id


def get_client_ip(request: Request) -> str:
    """Get client IP, respecting X-Forwarded-For behind proxy."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def find_uploaded_file(file_id: str) -> Optional[str]:
    """Find uploaded file by ID. Returns filepath or None."""
    file_id = validate_file_id(file_id)
    for ext in ALLOWED_EXTENSIONS:
        p = os.path.join(UPLOAD_DIR, f"{file_id}{ext}")
        if os.path.exists(p):
            return p
    return None


# --- Pydantic Models ---
class SuggestMappingRequest(BaseModel):
    direction: str = "to-jww"
    layers: list[str]
    colors: list[str]

    @field_validator('layers')
    @classmethod
    def limit_layers(cls, v):
        if len(v) > 500:
            raise ValueError("レイヤー数が多すぎます（最大500）")
        return v

    @field_validator('direction')
    @classmethod
    def valid_direction(cls, v):
        if v not in ('to-jww', 'to-dwg', 'to-dxf', 'jww-to-dwg'):
            raise ValueError("無効な変換方向です")
        return v


class ConvertRequest(BaseModel):
    file_id: str
    mapping: dict
    direction: str = "to-jww"

    @field_validator('file_id')
    @classmethod
    def valid_file_id(cls, v):
        if not UUID_PATTERN.match(v):
            raise ValueError("無効なファイルIDです")
        return v

    @field_validator('direction')
    @classmethod
    def valid_direction(cls, v):
        if v not in ('to-jww', 'to-dxf', 'jww-to-dwg'):
            raise ValueError("無効な変換方向です")
        return v


class BatchConvertRequest(BaseModel):
    file_ids: list[str]
    mapping: dict
    direction: str = "to-jww"

    @field_validator('file_ids')
    @classmethod
    def limit_files(cls, v):
        if len(v) > MAX_FILES_PER_BATCH:
            raise ValueError(f"一度に変換できるのは{MAX_FILES_PER_BATCH}ファイルまでです")
        for fid in v:
            if not UUID_PATTERN.match(fid):
                raise ValueError("無効なファイルIDが含まれています")
        return v


# --- API Endpoints ---

@app.get("/api/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {"status": "ok"}


@app.post("/api/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    # Rate limit
    client_ip = get_client_ip(request)
    if not rate_limiter.check(f"upload:{client_ip}", RATE_LIMIT_UPLOADS_PER_MIN):
        raise HTTPException(status_code=429, detail="アップロード回数の上限に達しました。しばらく待ってから再試行してください。")

    # Validate extension
    if not file.filename:
        raise HTTPException(status_code=400, detail="ファイル名が不正です。")

    filename_lower = file.filename.lower()
    if not filename_lower.endswith(ALLOWED_EXTENSIONS):
        raise HTTPException(status_code=400, detail="DXF/DWG/JWWファイルのみ対応しています。")

    # Check file size (read in chunks)
    file_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename)[1].lower()
    filepath = os.path.join(UPLOAD_DIR, f"{file_id}{ext}")

    total_size = 0
    try:
        with open(filepath, "wb") as buffer:
            while True:
                chunk = await file.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MAX_FILE_SIZE:
                    # Clean up partial file
                    buffer.close()
                    os.remove(filepath)
                    raise HTTPException(
                        status_code=413,
                        detail=f"ファイルサイズが大きすぎます（上限: {MAX_FILE_SIZE // (1024*1024)}MB）"
                    )
                buffer.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        if os.path.exists(filepath):
            os.remove(filepath)
        raise HTTPException(status_code=500, detail="ファイルのアップロードに失敗しました。")

    if total_size == 0:
        os.remove(filepath)
        raise HTTPException(status_code=400, detail="空のファイルです。")

    # Save original filename
    meta_path = os.path.join(UPLOAD_DIR, f"{file_id}.meta")
    with open(meta_path, "w") as f:
        f.write(file.filename)

    try:
        metadata = parse_dxf(filepath)
        return {
            "file_id": file_id,
            "filename": file.filename,
            "source_format": ext.lstrip('.'),
            "file_size": total_size,
            "metadata": metadata
        }
    except Exception as e:
        logger.error(f"Parse error for {file.filename}: {e}")
        # Clean up on parse failure
        for f in [filepath, meta_path]:
            if os.path.exists(f):
                os.remove(f)
        raise HTTPException(status_code=400, detail=f"ファイルの解析に失敗しました。ファイルが破損している可能性があります。")


@app.post("/api/ai-suggest-mapping")
async def ai_suggest_mapping(request: SuggestMappingRequest):
    from converter.ai_assistant import suggest_mapping
    try:
        suggestion = suggest_mapping(request.layers, request.colors, request.direction)
        return suggestion
    except Exception as e:
        logger.error(f"AI suggestion error: {e}")
        raise HTTPException(status_code=500, detail="AI提案機能でエラーが発生しました。手動でマッピングを設定してください。")


@app.post("/api/convert")
async def convert_file(request_body: ConvertRequest, request: Request):
    # Rate limit
    client_ip = get_client_ip(request)
    if not rate_limiter.check(f"convert:{client_ip}", RATE_LIMIT_CONVERTS_PER_MIN):
        raise HTTPException(status_code=429, detail="変換回数の上限に達しました。しばらく待ってから再試行してください。")

    file_id = request_body.file_id
    filepath = find_uploaded_file(file_id)
    if not filepath:
        raise HTTPException(status_code=404, detail="ファイルが見つかりません。再アップロードしてください。")

    try:
        source_ext = os.path.splitext(filepath)[1].lower()
        mapped_data = map_entities(filepath, request_body.mapping, request_body.direction)

        out_ext = ".dxf"
        out_filepath = os.path.join(OUTPUT_DIR, f"{file_id}_converted{out_ext}")

        if request_body.direction == "to-jww":
            export_optimized_dxf(mapped_data, out_filepath)
        else:
            mapped_data.saveas(out_filepath)

        return {
            "download_url": f"/api/download/{file_id}",
            "output_format": out_ext.lstrip('.'),
            "source_format": source_ext.lstrip('.')
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Convert error for {file_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="変換中にエラーが発生しました。ファイル形式を確認してください。")


@app.post("/api/convert-batch")
async def convert_batch(request_body: BatchConvertRequest, request: Request):
    client_ip = get_client_ip(request)
    if not rate_limiter.check(f"convert:{client_ip}", RATE_LIMIT_CONVERTS_PER_MIN):
        raise HTTPException(status_code=429, detail="変換回数の上限に達しました。しばらく待ってから再試行してください。")

    batch_id = str(uuid.uuid4())
    results = []
    errors = []

    for file_id in request_body.file_ids:
        filepath = find_uploaded_file(file_id)
        if not filepath:
            errors.append({"file_id": file_id, "error": "ファイルが見つかりません"})
            continue

        try:
            mapped_data = map_entities(filepath, request_body.mapping, request_body.direction)

            out_ext = ".dxf"
            out_filepath = os.path.join(OUTPUT_DIR, f"{file_id}_converted{out_ext}")

            if request_body.direction == "to-jww":
                export_optimized_dxf(mapped_data, out_filepath)
            else:
                mapped_data.saveas(out_filepath)

            results.append({
                "file_id": file_id,
                "output_format": out_ext.lstrip('.')
            })
        except Exception as e:
            logger.error(f"Batch convert error for {file_id}: {e}")
            errors.append({"file_id": file_id, "error": "変換に失敗しました"})

    batch_meta = os.path.join(OUTPUT_DIR, f"{batch_id}.batch")
    with open(batch_meta, "w") as f:
        for r in results:
            f.write(f"{r['file_id']}\n")

    return {
        "batch_id": batch_id,
        "results": results,
        "errors": errors,
        "download_url": f"/api/download-batch/{batch_id}"
    }


@app.get("/api/download-batch/{batch_id}")
async def download_batch(batch_id: str):
    validate_file_id(batch_id)
    batch_meta = os.path.join(OUTPUT_DIR, f"{batch_id}.batch")
    if not os.path.exists(batch_meta):
        raise HTTPException(status_code=404, detail="バッチが見つかりません。")

    with open(batch_meta, "r") as f:
        file_ids = [line.strip() for line in f if line.strip()]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file_id in file_ids:
            if not UUID_PATTERN.match(file_id):
                continue
            for ext in ['.dxf']:
                filepath = os.path.join(OUTPUT_DIR, f"{file_id}_converted{ext}")
                if os.path.exists(filepath):
                    original_name = None
                    meta_path = os.path.join(UPLOAD_DIR, f"{file_id}.meta")
                    if os.path.exists(meta_path):
                        with open(meta_path, "r") as mf:
                            original_name = mf.read().strip()
                    if original_name:
                        base = os.path.splitext(original_name)[0]
                        arcname = f"{base}{ext}"
                    else:
                        arcname = f"converted_{file_id}{ext}"
                    zf.write(filepath, arcname)
                    break

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=converted_files.zip"}
    )


@app.get("/api/download/{file_id}")
async def download_file(file_id: str):
    validate_file_id(file_id)

    original_name = None
    meta_path = os.path.join(UPLOAD_DIR, f"{file_id}.meta")
    if os.path.exists(meta_path):
        with open(meta_path, "r") as f:
            original_name = f.read().strip()

    for ext in ['.dxf']:
        filepath = os.path.join(OUTPUT_DIR, f"{file_id}_converted{ext}")
        if os.path.exists(filepath):
            if original_name:
                base = os.path.splitext(original_name)[0]
                filename = f"{base}{ext}"
            else:
                filename = f"converted_{file_id}{ext}"
            return FileResponse(filepath, filename=filename, media_type="application/octet-stream")

    raise HTTPException(status_code=404, detail="変換済みファイルが見つかりません。有効期限が切れた可能性があります。")
