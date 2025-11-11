FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

# Tesseract + librerías para OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-osd \
    tesseract-ocr-spa \
    libgl1 \
    libglib2.0-0 \
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
