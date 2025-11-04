from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response
from PIL import Image
import pytesseract
import io
import logging
import os  # <-- FALTABA ESTE IMPORT

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("image-rotator")

app = FastAPI(title="Image Rotation Fixer")

MAX_UPLOAD_SIZE = int(os.environ.get('MAX_UPLOAD_SIZE', 10 * 1024 * 1024))


@app.get('/health')
async def health():
    return {"status": "ok"}


@app.post('/fix_rotation')
async def fix_rotation(file: UploadFile = File(...)):
    """
    Detecta y corrige la rotación de una imagen con texto.
    Devuelve la imagen corregida en el mismo formato.
    """
    # Leer imagen con límite de tamaño
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="Image too large")
    
    try:
        # Abrir imagen
        image = Image.open(io.BytesIO(content))
        original_format = image.format or 'PNG'
        
        # Detectar orientación usando Tesseract
        osd = pytesseract.image_to_osd(image)
        logger.info(f"OSD result: {osd}")
        
        # Extraer ángulo de rotación
        rotation_angle = 0
        for line in osd.split('\n'):
            if 'Rotate:' in line:
                rotation_angle = int(line.split(':')[1].strip())
                break
        
        logger.info(f"Detected rotation: {rotation_angle} degrees")
        
        # Rotar si es necesario
        if rotation_angle != 0:
            # Tesseract devuelve el ángulo que HAY que rotar para corregir
            image = image.rotate(-rotation_angle, expand=True)
            logger.info(f"Image rotated {-rotation_angle} degrees")
        
        # Guardar en memoria
        output = io.BytesIO()
        image.save(output, format=original_format)
        output.seek(0)
        
        # Determinar media type
        media_type = f"image/{original_format.lower()}"
        
        return Response(
            content=output.getvalue(),
            media_type=media_type,
            headers={
                "X-Rotation-Applied": str(-rotation_angle if rotation_angle else 0),
                "Content-Disposition": f'inline; filename="fixed_{file.filename}"'
            }
        )
        
    except Exception as e:
        logger.error(f"Error processing image: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing image: {str(e)}")