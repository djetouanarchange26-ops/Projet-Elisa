import pdfplumber
import pytesseract
from pdf2image import convert_from_path
from pathlib import Path
import csv
import os

corpus = Path("C:/Users/djeto/Desktop/Projet-Elisa/corpus")
output = Path("C:/Users/djeto/Desktop/Projet-Elisa/data/processed")
output.mkdir(parents=True, exist_ok=True)


def chunk_text(text, chunk_size=175, overlap=50):
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i:i + chunk_size])
        if len(chunk.split()) > 30:
            chunks.append(chunk)
    return chunks


def extract_pdf(pdf_path):
    full_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if len(text) < 50:
                try:
                    images = convert_from_path(pdf_path, first_page=page.page_number, last_page=page.page_number)
                    text = pytesseract.image_to_string(images[0])
                except:
                    text = ""
            full_text += text + "\n"
    return full_text


# Charger les IDs déjà traités pour éviter les doublons
existing_ids = set()
csv_path = output / "chunks.csv"
if csv_path.exists():
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            existing_ids.add(row["project_id"])

all_chunks = []

# Traitement des PDF
for pdf_file in corpus.glob("*.pdf"):
    if pdf_file.stem in existing_ids:
        print(f"Skipping {pdf_file.name} (already processed)")
        continue

    print(f"Processing {pdf_file.name}...")
    full_text = extract_pdf(pdf_file)
    chunks = chunk_text(full_text)

    for i, chunk in enumerate(chunks):
        all_chunks.append({
            "project_id": pdf_file.stem,
            "project_name": pdf_file.stem,
            "chunk_id": f"{pdf_file.stem}_chunk_{i}",
            "text": chunk,
            "flag_type": "",
            "event": "",
            "time_to_event": "",
            "doc_date": ""
        })

# Traitement des TXT
for txt_file in corpus.glob("*.txt"):
    if txt_file.stem in existing_ids:
        print(f"Skipping {txt_file.name} (already processed)")
        continue

    print(f"Processing {txt_file.name}...")
    full_text = txt_file.read_text(encoding="utf-8")
    chunks = chunk_text(full_text)

    for i, chunk in enumerate(chunks):
        all_chunks.append({
            "project_id": txt_file.stem,
            "project_name": txt_file.stem,
            "chunk_id": f"{txt_file.stem}_chunk_{i}",
            "text": chunk,
            "flag_type": "",
            "event": "",
            "time_to_event": "",
            "doc_date": ""
        })

# Sauvegarde — append si le fichier existe déjà, sinon création
if not all_chunks:
    print("Aucun nouveau fichier à traiter.")
else:
    mode = "a" if csv_path.exists() else "w"
    with open(csv_path, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_chunks[0].keys())
        if mode == "w":
            writer.writeheader()
        writer.writerows(all_chunks)
    print(f"Done — {len(all_chunks)} nouveaux chunks ajoutés")
   
