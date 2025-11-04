FROM python:3.11-slim

# Instalar Tesseract OCR
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-spa \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

ENV MAX_UPLOAD_SIZE=10485760

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
