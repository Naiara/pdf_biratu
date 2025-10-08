from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse
import shutil
import os
import logging
from .pdf_utils import fix_pdf_rotation, detect_rotations

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pdf-rotator")

app = FastAPI(title="PDF Rotation Fixer")


@app.get('/health')
async def health():
    return {"status": "ok"}


# Max upload size in bytes (default 10 MB)
MAX_UPLOAD_SIZE = int(os.environ.get('MAX_UPLOAD_SIZE', 10 * 1024 * 1024))


@app.post('/fix_rotation')
async def fix_rotation(file: UploadFile = File(...), debug: int = 0):
    # quick size check (UploadFile doesn't expose size before reading; stream into temp and check)
    tmp_in = f"/tmp/input_{file.filename}"
    tmp_out = f"/tmp/output_{file.filename}"
    total = 0
    with open(tmp_in, 'wb') as f:
        while True:
            chunk = await file.read(1024 * 64)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_SIZE:
                raise HTTPException(status_code=413, detail="Uploaded file is too large")
            f.write(chunk)

    try:
        if debug:
            diagnostics = detect_rotations(tmp_in)
            # log diagnostics so they appear in docker logs
            logger.info("Diagnostics for %s: %s", file.filename, diagnostics)
            return JSONResponse(status_code=200, content={"diagnostics": diagnostics})
        fixed = fix_pdf_rotation(tmp_in, tmp_out)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

    if not fixed:
        # return original file
        return FileResponse(tmp_in, media_type='application/pdf', filename=file.filename)

    return FileResponse(tmp_out, media_type='application/pdf', filename=f"fixed_{file.filename}")

