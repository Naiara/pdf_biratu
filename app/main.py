from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse
import shutil
import os
import logging
import json
from datetime import datetime
from .pdf_utils import fix_pdf_rotation, detect_rotations, export_rotated_images_zip

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pdf-rotator")

app = FastAPI(title="PDF Rotation Fixer")


@app.get('/health')
async def health():
    return {"status": "ok"}


# Max upload size in bytes (default 10 MB)
MAX_UPLOAD_SIZE = int(os.environ.get('MAX_UPLOAD_SIZE', 10 * 1024 * 1024))


@app.post('/fix_rotation')
async def fix_rotation(file: UploadFile = File(...), debug: int = 0, format: str = 'pdf', image_format: str = 'png', image_dpi: int = 200):
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
        # enforce image_dpi limits
        if image_dpi is None or image_dpi <= 0:
            image_dpi = 200
        if image_dpi > 500:
            image_dpi = 500

        # prepare safe base name for saved artifacts
        base = os.path.splitext(file.filename)[0]
        safe = ''.join(c for c in base if c.isalnum() or c in (' ', '.', '_', '-')).rstrip()

        if debug:
            diagnostics = detect_rotations(tmp_in, dpi=image_dpi)
            # log diagnostics so they appear in docker logs
            logger.info("Diagnostics for %s: %s", file.filename, diagnostics)
            # ensure debug directory exists inside mounted data
            debug_dir = '/data/debug'
            try:
                os.makedirs(debug_dir, exist_ok=True)
            except Exception:
                # best effort - if cannot create, continue without halting
                logger.warning("Could not create debug dir %s", debug_dir)
            # write diagnostics JSON with timestamped filename
            try:
                ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
                debug_path = f"{debug_dir}/{safe}_{ts}.json"
                with open(debug_path, 'w', encoding='utf-8') as df:
                    json.dump({"diagnostics": diagnostics}, df, ensure_ascii=False, indent=2)
                logger.info("Wrote debug JSON to %s", debug_path)
            except Exception as e:
                logger.warning("Failed to write debug JSON: %s", e)

            return JSONResponse(status_code=200, content={"diagnostics": diagnostics})

        if format.lower() == 'zip':
            # produce a zip with images of rotated pages
            # sanitize base filename and write into the mounted /data directory
            base = os.path.splitext(file.filename)[0]
            # allow only safe chars
            safe = ''.join(c for c in base if c.isalnum() or c in (' ', '.', '_', '-')).rstrip()
            zip_out = f"/data/fixed_{safe}.zip"
            ok = export_rotated_images_zip(tmp_in, zip_out, image_format=image_format, dpi=image_dpi)
            if not ok:
                return JSONResponse(status_code=500, content={"error": "Failed to produce zip"})
            return FileResponse(zip_out, media_type='application/zip', filename=f"fixed_{safe}.zip")
        fixed = fix_pdf_rotation(tmp_in, tmp_out, dpi=image_dpi)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

    if not fixed:
        # return original file
        return FileResponse(tmp_in, media_type='application/pdf', filename=file.filename)

    return FileResponse(tmp_out, media_type='application/pdf', filename=f"fixed_{file.filename}")

