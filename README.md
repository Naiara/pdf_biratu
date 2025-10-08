# PDF Rotation Fixer (Docker + FastAPI)

This small service detects rotated pages in a PDF and returns a corrected PDF.

Features:
- Uses Poppler (`pdftoppm`) to render PDF pages to images.
- Uses Tesseract OCR to detect page orientation.
- Uses PyPDF2 to rotate PDF pages and produce a new PDF.

Everything runs inside Docker. Minimal dependencies: Python, poppler-utils, tesseract.

How to build and run (PowerShell):

```powershell
# from repository root
docker compose build
docker compose up
```

The service will be available at http://localhost:8000.

Endpoint:
- POST /fix_rotation (form file upload, field name `file`) -> returns fixed PDF or original if no rotation detected.

Notes and next steps:
- This uses Tesseract OSD which may need language packs for best results. I included Spanish (`spa`).
- For n8n integration, call the endpoint from your n8n workflow (in the same LAN) and pass the PDF file; mount a shared volume if you prefer.
