FROM python:3.11-slim
WORKDIR /app
# poppler-utils ajouté (absent de la directive V3.1) : pdf2image (requirements.txt,
# utilisé par ingest.py pour l'OCR de secours sur les PDF scannés) est un wrapper
# autour des binaires poppler (pdftoppm/pdfinfo) — sans ce paquet système,
# convert_from_path() lève PDFInfoNotInstalledError au premier PDF scanné.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr libgl1 poppler-utils && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV OLLAMA_HOST=http://ollama:11434
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", \
     "--server.port=8501"]
