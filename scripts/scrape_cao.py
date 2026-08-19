"""
CHANTIER 0a (PROMPT_CLAUDE_CODE_ESG_V2) — Collecte des cas CAO
================================================================
Objectif : trouver des cas CAO (Compliance Advisor/Ombudsman) dont le
numéro de projet IFC n'est PAS déjà dans le corpus, pour enrichir les
projets `event=1` (plainte ESG confirmée) du modèle Cox.

Source de la LISTE des cas : le CSV "Export All Cases"
(https://www.cao-ombudsman.org/export-all-cases) — PAS un scraping de la
page /cases elle-même. Cette dernière est une base de recherche pilotée
par JavaScript (filtres dynamiques, pagination côté client) ;
`requests`+`BeautifulSoup` seuls n'y verraient rien. Le CSV export, lui,
est une réponse statique et couvre l'intégralité des cas (260 au
2026-07-30). Voir AUDIT_ESG.md, section "Addendum — Chantier 0".

En revanche, la fiche individuelle d'un cas (`/case/{slug}`) EST du HTML
statique — pas besoin de JS pour cette partie. Son URL n'étant pas dans le
CSV, elle est devinée par normalisation du nom de cas (`slugify`), avec
repli sur une variante tronquée si la première tentative échoue. Les cas
dont l'URL n'est pas trouvée sont journalisés dans
`data/raw/cao_cases_manual_review.csv` plutôt que silencieusement ignorés
(cf. le prompt : "documenter une procédure de téléchargement manuel
assisté" si le site bloque/échappe au scraping automatique).

FRAGILE : un même numéro de projet IFC peut apparaître dans PLUSIEURS cas
CAO distincts (ex. "Serbia: Morava Corridor Motorway-01/03/05" référencent
tous le projet 14629 — plaintes successives sur le même projet, vérifié
sur le CSV réel). Ce script écrit une ligne par CAS (pas par projet) dans
le CSV de sortie. Dédupliquer/agréger par projet (quel T_event retenir ?
quels documents combiner dans quel fichier corpus ?) est un choix éditorial
volontairement laissé à l'Étape 0c (manuelle, voir PROMPT_CLAUDE_CODE_ESG_V2),
pas automatisé ici.

Ce script ne modifie ni `data/raw/corpus_cao_ifc.xlsx` ni `chunks.csv` — il
ne fait que la collecte (documents PDF dans `corpus/` + métadonnées dans
`data/raw/cao_cases_metadata.csv`).

Usage :
    cd scripts/
    python scrape_cao.py --dry-run --limit 5   # teste la collecte de métadonnées, sans télécharger de PDF
    python scrape_cao.py --limit 5             # + téléchargement réel des PDFs (5 cas)
    python scrape_cao.py                       # tous les cas Closed candidats
    python scrape_cao.py --status Open,Closed  # inclure aussi les cas encore ouverts
"""

import argparse
import csv
import re
import time
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from ifc_board_dates import IFC_BOARD_DATES

BASE = Path(__file__).resolve().parent.parent
CORPUS_DIR = BASE / "corpus"
OUTPUT_METADATA = BASE / "data/raw/cao_cases_metadata.csv"
REVIEW_LOG = BASE / "data/raw/cao_cases_manual_review.csv"

SITE = "https://www.cao-ombudsman.org"
EXPORT_URL = f"{SITE}/export-all-cases"
PROJECT_NUM_COL = "Name and Number (Project number)"

# CHOIX: identification honnête du bot plutôt qu'un User-Agent de navigateur
# usurpé — usage ponctuel de recherche, pas un crawl continu.
HEADERS = {"User-Agent": "ESGRiskIntelligence-MVP-Research/0.1 (local prototype; one-off dataset enrichment)"}
REQUEST_DELAY_S = 1.5  # SEUIL: aucun Crawl-delay déclaré dans robots.txt — délai de politesse choisi arbitrairement


# ============================================================================
# ÉTAPE 1 — Liste des cas (CSV export)
# ============================================================================

def fetch_cases_csv(session):
    """Télécharge le CSV 'Export All Cases' — liste exhaustive des cas CAO,
    contrairement à la page /cases (recherche JS, non scrapable en HTML brut)."""
    resp = session.get(EXPORT_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return list(csv.DictReader(resp.text.splitlines()))


def extract_project_numbers(raw):
    """"IFC Project No. 46586" / "IFC Project #36008" /
    "IFC Project Nos.: 44742, 42480, 44882, and 38609" -> ["46586"] / ["36008"] / [...].
    """
    return re.findall(r"\d{4,}", raw or "")


def already_tracked(project_numbers, existing_numbers):
    return any(n in existing_numbers for n in project_numbers)


# ============================================================================
# ÉTAPE 2 — Fiche de cas individuelle (devinée puis scrapée)
# ============================================================================

_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


def slugify(case_name):
    """Normalise un nom de cas ("Pakistan: Karot Hydro-02/Jhelum River") en
    un slug d'URL candidat ("pakistan-karot-hydro-02jhelum-river") — vérifié
    empiriquement sur plusieurs cas via le sitemap CAO. Best-effort : voir
    find_case_url() pour les variantes de repli si ce slug ne répond pas.
    """
    s = unicodedata.normalize("NFKD", case_name).encode("ascii", "ignore").decode("ascii")
    s = s.lower().replace("&", "and").replace("'", "")
    s = _SLUG_STRIP_RE.sub("-", s).strip("-")
    return s


def find_case_url(session, case_name, delay=REQUEST_DELAY_S):
    """Devine l'URL de la fiche de cas — le CSV export ne contient pas
    l'URL, seulement le nom. Retourne (url, html) ou (None, None) si aucune
    variante ne répond 200 (à consigner dans REVIEW_LOG plutôt qu'ignorer)."""
    candidates = [slugify(case_name)]
    if "/" in case_name:
        candidates.append(slugify(case_name.split("/")[0]))  # variante sans le sous-titre après "/"

    for slug in candidates:
        url = f"{SITE}/case/{slug}"
        try:
            resp = session.get(url, headers=HEADERS, timeout=20)
        except requests.RequestException:
            resp = None
        time.sleep(delay)
        if resp is not None and resp.status_code == 200 and "Date Filed" in resp.text:
            return url, resp.text
    return None, None


def parse_case_page(html):
    """Extrait (header, documents) d'une fiche de cas.

    header : dict depuis `.cases-header--wrapper` — ex.
        {"date_filed": "24 Aug 2019", "status": "Open", "phase": "Compliance",
         "country": "Pakistan"}
    documents : liste de {"doc_type", "language", "doc_date", "url"} depuis
        les blocs `.case-documents--wrapper` (structure vérifiée sur une
        fiche réelle — voir AUDIT_ESG.md).
    """
    soup = BeautifulSoup(html, "html.parser")

    header = {}
    wrapper = soup.find(class_="cases-header--wrapper")
    if wrapper:
        parts = [p for p in wrapper.get_text("|", strip=True).split("|") if p]
        if len(parts) % 2 != 0:
            print(f"  [WARN] Bloc d'en-tête à nombre de champs impair ({len(parts)}) — parsing partiel possible")
        for i in range(0, len(parts) - 1, 2):
            header[parts[i].strip().lower().replace(" ", "_")] = parts[i + 1].strip()

    documents = []
    for block in soup.find_all(class_="case-documents--wrapper"):
        link_el = block.find("a", href=True)
        if not link_el:
            continue
        title_el = block.find(class_="title")
        lang_el = block.find(class_="language")
        date_el = block.find(class_="date")
        documents.append({
            "doc_type": title_el.get_text(strip=True) if title_el else "unknown",
            "language": lang_el.get_text(strip=True) if lang_el else "",
            "doc_date": date_el.get_text(strip=True) if date_el else "",
            "url": link_el["href"],
        })
    return header, documents


def select_documents(documents, preferred_language="English"):
    """Garde au plus un document par doc_type — priorité à
    `preferred_language` (les fiches CAO proposent souvent la même pièce en
    anglais + langue locale), sinon le premier trouvé pour ce type."""
    by_type = {}
    for d in documents:
        key = d["doc_type"]
        if key not in by_type or (
            d["language"] == preferred_language and by_type[key]["language"] != preferred_language
        ):
            by_type[key] = d
    return list(by_type.values())


# ============================================================================
# ÉTAPE 3 — Téléchargement des PDFs
# ============================================================================

def safe_filename_part(s, max_len=60):
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    return (s or "x")[:max_len]


def download_pdf(session, url, dest_path):
    """Télécharge `url` vers `dest_path`. Ne re-télécharge pas un fichier
    déjà présent (résumabilité — cf. ingest.py)."""
    if dest_path.exists():
        return "skipped_exists"
    if not url.startswith("http"):
        url = SITE + url
    try:
        resp = session.get(url, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        if not resp.content[:4] == b"%PDF":
            return "error_not_pdf"
        dest_path.write_bytes(resp.content)
        return "downloaded"
    except requests.RequestException as e:
        return f"error_{e.__class__.__name__}"


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=None, help="Ne traiter que N cas candidats (tests)")
    parser.add_argument("--dry-run", action="store_true", help="Collecte les métadonnées sans télécharger les PDFs")
    parser.add_argument("--status", default="Closed", help="Statuts CAO à inclure, séparés par virgule (défaut: Closed)")
    parser.add_argument("--delay", type=float, default=REQUEST_DELAY_S, help="Délai en secondes entre requêtes")
    args = parser.parse_args()

    statuses = {s.strip() for s in args.status.split(",")}
    session = requests.Session()

    print("Téléchargement du CSV 'Export All Cases'...")
    rows = fetch_cases_csv(session)
    print(f"  {len(rows)} cas au total sur cao-ombudsman.org")

    existing_numbers = set(IFC_BOARD_DATES.keys())
    # FRAGILE: IFC_BOARD_DATES ne couvre que les projets déjà scrapés (39 à ce
    # jour) — c'est le proxy le plus simple de "déjà dans le corpus" mais un
    # projet ajouté au corpus sans board date connue échapperait à ce filtre.
    # Recouper avec data/processed/chunks.csv (project_id) si des doublons
    # apparaissent en Étape 0c.

    candidates = [
        (row, extract_project_numbers(row.get(PROJECT_NUM_COL, "")))
        for row in rows
        if row["Status"] in statuses
    ]
    candidates = [(r, n) for r, n in candidates if n and not already_tracked(n, existing_numbers)]

    print(f"  {len(candidates)} cas candidats (statut in {statuses}, numéro de projet absent du corpus)")
    if args.limit:
        candidates = candidates[: args.limit]
        print(f"  --limit {args.limit} -> {len(candidates)} cas traités cette run")

    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    metadata_rows, review_rows = [], []

    for i, (row, nums) in enumerate(candidates, 1):
        case_name = row["Case Name"]
        print(f"[{i}/{len(candidates)}] {case_name} (projet {','.join(nums)})")

        url, html = find_case_url(session, case_name, delay=args.delay)
        if not url:
            print("  [MANUEL] URL de la fiche introuvable par déduction du slug")
            review_rows.append({
                "case_name": case_name, "project_numbers": ";".join(nums),
                "reason": "slug_not_found",
            })
            continue

        header, documents = parse_case_page(html)
        docs_to_get = select_documents(documents)

        downloaded = []
        if not args.dry_run:
            for doc in docs_to_get:
                fname = f"CAO_{safe_filename_part(case_name)}_{safe_filename_part(doc['doc_type'])}.pdf"
                status = download_pdf(session, doc["url"], CORPUS_DIR / fname)
                print(f"    {doc['doc_type']} ({doc['language'] or '?'}): {status}")
                if status in ("downloaded", "skipped_exists"):
                    downloaded.append(fname)
                time.sleep(args.delay)
        else:
            print(f"  [DRY-RUN] {len(docs_to_get)} document(s) trouvés, non téléchargés")

        metadata_rows.append({
            "case_number":        case_name,
            "ifc_project_number": ";".join(nums),
            "country":            row.get("Country", ""),
            "sector":             row.get("Sector", ""),
            "complaint_date":     header.get("date_filed", ""),
            "status":             row.get("Status", ""),
            "case_url":           url,
            "docs_available":     len(documents),
            "docs_downloaded":    ";".join(downloaded),
        })

    OUTPUT_METADATA.parent.mkdir(parents=True, exist_ok=True)
    if metadata_rows:
        write_header = not OUTPUT_METADATA.exists()
        with open(OUTPUT_METADATA, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=metadata_rows[0].keys())
            if write_header:
                writer.writeheader()
            writer.writerows(metadata_rows)

    if review_rows:
        write_header_r = not REVIEW_LOG.exists()
        with open(REVIEW_LOG, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=review_rows[0].keys())
            if write_header_r:
                writer.writeheader()
            writer.writerows(review_rows)

    print(f"\nTerminé — {len(metadata_rows)} cas traités"
          f"{' (dry-run, aucun PDF téléchargé)' if args.dry_run else ''}, "
          f"{len(review_rows)} à vérifier manuellement (voir {REVIEW_LOG.name})")


if __name__ == "__main__":
    main()
