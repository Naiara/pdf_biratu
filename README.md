# Image Rotation Fixer

Servicio FastAPI que detecta y corrige automáticamente la rotación de imágenes usando OCR.

## Características

- Detecta orientación de texto en imágenes
- Corrige automáticamente imágenes rotadas (90°, 180°, 270°)
- Mantiene el formato original (JPG, PNG, etc.)
- API REST simple

## Requisitos

- Python 3.11+
- Tesseract OCR

## Instalación Local

```bash
pip install -r requirements.txt
```

## Ejecución Local

```bash
uvicorn app.main:app --reload
```

## Docker

```bash
docker-compose up --build
```

## API Endpoints

### `POST /fix_rotation`

Sube una imagen y recibe la versión corregida.

**Ejemplo con curl (PowerShell):**

```powershell
curl.exe -X POST "http://localhost:8000/fix_rotation" -F "file=@data/froga_2.png" --output data/froga_2_fixed.png
```

**Ejemplo con curl (Bash):**

```bash
curl -X POST "http://localhost:8000/fix_rotation" \
  -F "file=@data/froga_2.png" \
  --output data/froga_2_fixed.png
```

**Ver headers de respuesta:**

```powershell
curl.exe -X POST "http://localhost:8000/fix_rotation" -F "file=@data/froga_2.png" -i --output data/froga_2_fixed.png
```

**Headers de respuesta:**
- `X-Rotation-Applied`: Grados de rotación aplicados (0, 90, 180, 270)

### `GET /health`

Verifica el estado del servicio.

```bash
curl http://localhost:8000/health
```

## Variables de Entorno

- `MAX_UPLOAD_SIZE`: Tamaño máximo de archivo en bytes (default: 10MB)

## Estructura del Proyecto

```
img_biratu/
├── app/
│   └── main.py          # Aplicación FastAPI
├── data/                # Imágenes de prueba
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```
