from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import shutil
import os
import uuid
import zipfile
import io
from typing import Optional

from converter.parser import parse_dxf
from converter.mapper import map_entities
from converter.jww_exporter import export_optimized_dxf

app = FastAPI(title="JWW Converter SaaS API")

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'frontend')
FRONTEND_DIR_DOCKER = os.path.join(os.path.dirname(__file__), 'frontend_static')
_frontend = FRONTEND_DIR if os.path.isdir(FRONTEND_DIR) else FRONTEND_DIR_DOCKER
if os.path.isdir(_frontend):
    app.mount("/app", StaticFiles(directory=_frontend, html=True), name="frontend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = ('.dxf', '.dwg', '.jww')


@app.get("/api/debug/oda")
async def debug_oda():
    import subprocess
    paths = [
        "/usr/bin/ODAFileConverter",
        "/usr/local/bin/ODAFileConverter",
        "/opt/ODAFileConverter/ODAFileConverter",
    ]
    found = {p: os.path.isfile(p) for p in paths}
    which = subprocess.run(["which", "ODAFileConverter"], capture_output=True, text=True)
    find = subprocess.run(["find", "/", "-name", "ODAFileConverter", "-type", "f"], capture_output=True, text=True, timeout=5)
    from ezdxf.addons import odafc
    # Test actual ODA execution
    oda_test = ""
    try:
        r = subprocess.run(["ODAFileConverter"], capture_output=True, text=True, timeout=5)
        oda_test = f"rc={r.returncode} stdout={r.stdout[:200]} stderr={r.stderr[:200]}"
    except Exception as e:
        oda_test = str(e)
    # Check ldd
    ldd = ""
    try:
        r2 = subprocess.run(["ldd", "/usr/bin/ODAFileConverter"], capture_output=True, text=True, timeout=5)
        missing = [l.strip() for l in r2.stdout.split('\n') if 'not found' in l]
        ldd = missing if missing else "all libs found"
    except Exception as e:
        ldd = str(e)
    return {
        "paths_checked": found,
        "which": which.stdout.strip(),
        "find": find.stdout.strip(),
        "odafc_installed": odafc.is_installed(),
        "oda_exec_test": oda_test,
        "missing_libs": ldd,
    }


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(ALLOWED_EXTENSIONS):
        raise HTTPException(status_code=400, detail="DXF/DWG/JWWファイルのみ対応しています。")

    file_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename)[1].lower()
    filepath = os.path.join(UPLOAD_DIR, f"{file_id}{ext}")

    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    meta_path = os.path.join(UPLOAD_DIR, f"{file_id}.meta")
    with open(meta_path, "w") as f:
        f.write(file.filename)

    try:
        metadata = parse_dxf(filepath)
        return {
            "file_id": file_id,
            "filename": file.filename,
            "source_format": ext.lstrip('.'),
            "metadata": metadata
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ファイル解析エラー: {str(e)}")


class SuggestMappingRequest(BaseModel):
    direction: str = "to-jww"
    layers: list[str]
    colors: list[str]


@app.post("/api/ai-suggest-mapping")
async def ai_suggest_mapping(request: SuggestMappingRequest):
    from converter.ai_assistant import suggest_mapping
    try:
        suggestion = suggest_mapping(request.layers, request.colors, request.direction)
        return suggestion
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Suggestion error: {str(e)}")


class ConvertRequest(BaseModel):
    file_id: str
    mapping: dict
    direction: str = "to-jww"


class BatchConvertRequest(BaseModel):
    file_ids: list[str]
    mapping: dict
    direction: str = "to-jww"


@app.post("/api/convert")
async def convert_file(request: ConvertRequest):
    file_id = request.file_id
    filepath = None

    for ext in ['.dxf', '.dwg', '.jww']:
        p = os.path.join(UPLOAD_DIR, f"{file_id}{ext}")
        if os.path.exists(p):
            filepath = p
            break

    if not filepath:
        raise HTTPException(status_code=404, detail="ファイルが見つかりません。")

    try:
        mapped_data = map_entities(filepath, request.mapping, request.direction)

        is_jww_source = filepath.lower().endswith('.jww')

        if request.direction == "to-jww":
            out_ext = ".dxf"
            out_filepath = os.path.join(OUTPUT_DIR, f"{file_id}_converted{out_ext}")
            export_optimized_dxf(mapped_data, out_filepath)
        elif is_jww_source or request.direction == "jww-to-dwg":
            out_ext = ".dxf"
            out_filepath = os.path.join(OUTPUT_DIR, f"{file_id}_converted{out_ext}")
            from converter.dwg_exporter import export_optimized_dwg
            export_optimized_dwg(mapped_data, out_filepath)
            dwg_path = os.path.join(OUTPUT_DIR, f"{file_id}_converted.dwg")
            if os.path.exists(dwg_path):
                out_ext = ".dwg"
        else:
            out_ext = ".dxf"
            out_filepath = os.path.join(OUTPUT_DIR, f"{file_id}_converted{out_ext}")
            from converter.dwg_exporter import export_optimized_dwg
            export_optimized_dwg(mapped_data, out_filepath)

        return {
            "download_url": f"/api/download/{file_id}",
            "output_format": out_ext.lstrip('.')
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"変換エラー: {str(e)}")


@app.post("/api/convert-batch")
async def convert_batch(request: BatchConvertRequest):
    batch_id = str(uuid.uuid4())
    results = []
    errors = []

    for file_id in request.file_ids:
        filepath = None
        for ext in ['.dxf', '.dwg', '.jww']:
            p = os.path.join(UPLOAD_DIR, f"{file_id}{ext}")
            if os.path.exists(p):
                filepath = p
                break

        if not filepath:
            errors.append({"file_id": file_id, "error": "ファイルが見つかりません"})
            continue

        try:
            mapped_data = map_entities(filepath, request.mapping, request.direction)
            is_jww_source = filepath.lower().endswith('.jww')

            if request.direction == "to-jww":
                out_ext = ".dxf"
                out_filepath = os.path.join(OUTPUT_DIR, f"{file_id}_converted{out_ext}")
                export_optimized_dxf(mapped_data, out_filepath)
            elif is_jww_source or request.direction == "jww-to-dwg":
                out_ext = ".dxf"
                out_filepath = os.path.join(OUTPUT_DIR, f"{file_id}_converted{out_ext}")
                from converter.dwg_exporter import export_optimized_dwg
                export_optimized_dwg(mapped_data, out_filepath)
                dwg_path = os.path.join(OUTPUT_DIR, f"{file_id}_converted.dwg")
                if os.path.exists(dwg_path):
                    out_ext = ".dwg"
            else:
                out_ext = ".dxf"
                out_filepath = os.path.join(OUTPUT_DIR, f"{file_id}_converted{out_ext}")
                from converter.dwg_exporter import export_optimized_dwg
                export_optimized_dwg(mapped_data, out_filepath)

            results.append({
                "file_id": file_id,
                "output_format": out_ext.lstrip('.')
            })
        except Exception as e:
            errors.append({"file_id": file_id, "error": str(e)})

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
    batch_meta = os.path.join(OUTPUT_DIR, f"{batch_id}.batch")
    if not os.path.exists(batch_meta):
        raise HTTPException(status_code=404, detail="バッチが見つかりません。")

    with open(batch_meta, "r") as f:
        file_ids = [line.strip() for line in f if line.strip()]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file_id in file_ids:
            for ext in ['.dwg', '.dxf', '.jwc']:
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
    original_name = None
    meta_path = os.path.join(UPLOAD_DIR, f"{file_id}.meta")
    if os.path.exists(meta_path):
        with open(meta_path, "r") as f:
            original_name = f.read().strip()

    for ext in ['.dwg', '.dxf', '.jwc']:
        filepath = os.path.join(OUTPUT_DIR, f"{file_id}_converted{ext}")
        if os.path.exists(filepath):
            media_type = "application/octet-stream"
            if original_name:
                base = os.path.splitext(original_name)[0]
                filename = f"{base}{ext}"
            else:
                filename = f"converted_{file_id}{ext}"
            return FileResponse(filepath, filename=filename, media_type=media_type)

    raise HTTPException(status_code=404, detail="変換済みファイルが見つかりません。")
