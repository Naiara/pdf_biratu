from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response
from PIL import Image
import pytesseract
from pytesseract import TesseractError
import io
import logging
import os
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("image-rotator")

app = FastAPI(title="Image Rotation Fixer")

MAX_UPLOAD_SIZE = int(os.environ.get('MAX_UPLOAD_SIZE', 10 * 1024 * 1024))
MAX_DIMENSION = 2000  # Redimensionar imágenes muy grandes para OSD más rápido


@app.get('/health')
async def health():
    return {"status": "ok"}


@app.post('/fix_rotation')
async def fix_rotation(file: UploadFile = File(...)):
    """
    Detecta y corrige la rotación de una imagen con texto.
    Devuelve la imagen corregida en el mismo formato.
    """
    start_time = time.time()
    logger.info(f"Processing file: {file.filename}, content_type: {file.content_type}")
    
    # Leer imagen con límite de tamaño
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="Image too large")
    
    try:
        # Abrir imagen
        image = Image.open(io.BytesIO(content))
        original_format = image.format or 'PNG'
        logger.info(f"Image size: {image.size}, format: {original_format}")
        
        # Redimensionar temporalmente si la imagen es muy grande (mejora velocidad OSD)
        osd_image = image
        needs_resize = max(image.size) > MAX_DIMENSION
        if needs_resize:
            ratio = MAX_DIMENSION / max(image.size)
            new_size = tuple(int(dim * ratio) for dim in image.size)
            osd_image = image.resize(new_size, Image.Resampling.LANCZOS)
            logger.info(f"Resized for OSD: {image.size} -> {new_size}")
        
        rotation_angle = 0
        
        try:
            # Detectar orientación usando Tesseract
            osd_start = time.time()
            osd = pytesseract.image_to_osd(osd_image)
            osd_time = time.time() - osd_start
            logger.info(f"OSD successful in {osd_time:.2f}s")
            
            # Extraer ángulo de rotación
            for line in osd.split('\n'):
                if 'Rotate:' in line:
                    rotation_angle = int(line.split(':')[1].strip())
                    break
            
            logger.info(f"Detected rotation: {rotation_angle} degrees")
            
        except Exception as e:
            # Captura cualquier error de Tesseract (insuficiente texto, baja resolución, etc.)
            logger.warning(f"OSD detection failed: {str(e)[:100]}. Returning original image.")
            rotation_angle = 0
        
        # Rotar si es necesario (usar imagen ORIGINAL, no la redimensionada)
        if rotation_angle != 0:
            # Tesseract devuelve el ángulo que HAY que rotar para corregir
            image = image.rotate(-rotation_angle, expand=True)
            logger.info(f"Image rotated {-rotation_angle} degrees")
        
        # Guardar en memoria con calidad alta
        output = io.BytesIO()
        if original_format == 'JPEG':
            image.save(output, format=original_format, quality=95)
        else:
            image.save(output, format=original_format)
        output.seek(0)
        
        # Determinar media type
        media_type = f"image/{original_format.lower()}"
        
        response_content = output.getvalue()
        total_time = time.time() - start_time
        logger.info(f"Total processing time: {total_time:.2f}s, returning {len(response_content)} bytes, rotation={-rotation_angle if rotation_angle else 0}")
        
        return Response(
            content=response_content,
            media_type=media_type,
            headers={
                "X-Rotation-Applied": str(-rotation_angle if rotation_angle else 0),
                "X-Processing-Time": f"{total_time:.2f}",
                "Content-Disposition": f'inline; filename="fixed_{file.filename}"'
            }
        )
        
    except Exception as e:
        logger.error(f"Error processing image: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing image: {str(e)}")