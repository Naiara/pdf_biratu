from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response
from PIL import Image
import pytesseract
from pytesseract import TesseractError
import cv2
import numpy as np
from deskew import determine_skew
import io
import logging
import os
import time
from deskew import determine_skew

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("image-rotator")

app = FastAPI(title="Image Rotation Fixer")

MAX_UPLOAD_SIZE = int(os.environ.get('MAX_UPLOAD_SIZE', 10 * 1024 * 1024))
MAX_DIMENSION = 2000


def detect_table_angle(image_array):
    """
    Detecta el ángulo de rotación usando la librería deskew.
    Retorna el ángulo en grados para corregir.
    Retorna None si no se puede detectar.
    """
    try:
        # Convertir a escala de grises si es necesario
        if len(image_array.shape) == 3:
            gray = cv2.cvtColor(image_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = image_array
        
        # Detectar ángulo usando deskew
        angle = determine_skew(gray)
        
        if angle is None or np.isnan(angle):
            logger.info("Deskew: Could not determine skew angle")
            return None
        
        logger.info(f"Deskew detected angle: {angle:.2f}°")
        
        # Solo corregir si hay desviación significativa (>0.2°)
        if abs(angle) > 0.2:
            # deskew devuelve el ángulo de inclinación
            # Necesitamos rotar en sentido contrario, pero primero probamos SIN negar
            return angle
        
        logger.info(f"Angle too small ({angle:.2f}°), no correction needed")
        return 0
        
    except Exception as e:
        logger.warning(f"Deskew detection failed: {str(e)}")
        return None


@app.get('/health')
async def health():
    return {"status": "ok"}


@app.post('/fix_rotation')
async def fix_rotation(
    file: UploadFile = File(...),
    force_table_fix: bool = False
):
    """
    Detecta y corrige la rotación de una imagen con tablas o texto.
    Primero corrige orientación de página (90°, 180°, 270°), 
    luego corrige inclinación fina de tabla.
    
    Args:
        file: Imagen a procesar
        force_table_fix: Si es True, aplica corrección de tabla incluso con variación alta
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
        
        page_rotation = 0
        fine_rotation = 0
        detection_method = "none"
        
        # PASO 1: Detectar orientación de página (90°, 180°, 270°) con OCR
        try:
            # Redimensionar si es muy grande
            osd_image = image
            if max(image.size) > MAX_DIMENSION:
                ratio = MAX_DIMENSION / max(image.size)
                new_size = tuple(int(dim * ratio) for dim in image.size)
                osd_image = image.resize(new_size, Image.Resampling.LANCZOS)
            
            osd_start = time.time()
            osd = pytesseract.image_to_osd(osd_image)
            osd_time = time.time() - osd_start
            
            # Extraer ángulo de rotación de página
            for line in osd.split('\n'):
                if 'Rotate:' in line:
                    page_rotation = -int(line.split(':')[1].strip())
                    detection_method = "ocr"
                    break
            
            logger.info(f"OCR page rotation: {page_rotation}° in {osd_time:.2f}s")
            
            # Aplicar rotación de página si es necesario
            if page_rotation != 0:
                image = image.rotate(page_rotation, expand=True, fillcolor='white')
                logger.info(f"Page rotated {page_rotation}°")
                
        except Exception as e:
            logger.warning(f"OCR detection failed: {str(e)[:100]}")
        
        # PASO 2: Detectar inclinación fina con deskew
        try:
            image_array = np.array(image.convert('RGB'))
            table_angle = detect_table_angle(image_array)
            
            # Aplicar si hay ángulo significativo
            # O si force_table_fix=True y el ángulo no es exactamente 0
            should_apply = (table_angle is not None and abs(table_angle) > 0.3)
            if force_table_fix and table_angle is not None and table_angle != 0:
                should_apply = True
                logger.info(f"Forcing table fix with angle: {table_angle:.2f}°")
            
            if should_apply:
                fine_rotation = table_angle
                image = image.rotate(fine_rotation, expand=True, fillcolor='white')
                detection_method = "ocr+deskew" if page_rotation != 0 else "deskew"
                logger.info(f"Deskew fine rotation applied: {fine_rotation:.2f}°")
            else:
                logger.info("No significant skew detected or correction skipped")
        except Exception as e:
            logger.warning(f"Deskew detection failed: {str(e)}")
        
        total_rotation = page_rotation + fine_rotation
        
        # Guardar en memoria con calidad alta
        output = io.BytesIO()
        if original_format == 'JPEG':
            image.save(output, format=original_format, quality=95)
        else:
            image.save(output, format=original_format)
        output.seek(0)
        
        media_type = f"image/{original_format.lower()}"
        response_content = output.getvalue()
        total_time = time.time() - start_time
        
        logger.info(f"Total: {total_time:.2f}s, {len(response_content)} bytes, "
                   f"page={page_rotation}°, fine={fine_rotation:.2f}°, total={total_rotation:.2f}°, method={detection_method}")
        
        return Response(
            content=response_content,
            media_type=media_type,
            headers={
                "X-Rotation-Applied": str(round(total_rotation, 2)),
                "X-Page-Rotation": str(page_rotation),
                "X-Fine-Rotation": str(round(fine_rotation, 2)),
                "X-Detection-Method": detection_method,
                "X-Processing-Time": f"{total_time:.2f}",
                "Content-Disposition": f'inline; filename="fixed_{file.filename}"'
            }
        )
        
    except Exception as e:
        logger.error(f"Error processing image: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing image: {str(e)}")