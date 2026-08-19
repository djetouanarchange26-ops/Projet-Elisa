"""
CHANTIER 0b (PROMPT_CLAUDE_CODE_ESG_V2) — Collecte des projets IFC « contrôles »
=================================================================================
Objectif : trouver des projets IFC (event=0, pas de plainte CAO) comparables
en secteur/pays aux cas `event=1` collectés par `scrape_cao.py`, pour
rééquilibrer le corpus d'entraînement du modèle Cox.

Contrairement à `cao-ombudsman.org` (CSV export exhaustif, cf.
scrape_cao.py), `disclosures.ifc.org` n'a pas d'export en clair et son
frontend (page /search, fiches /project-detail/...) est un SPA derrière
Cloudflare (cookie `__cf_bm` observé dès les premières requêtes). MAIS son
véritable backend de recherche est un service public normal, appelable en
`requests.post` simple, SANS blocage observé pendant la reconnaissance
(2026-07-30) :

    POST https://webapi.worldbank.org/aemsite/ifc-disclosure-search
    {"search": "*", "filter": "Country_Description eq 'X' and
     Industry_Description eq 'Y'", "top": N, "skip": 0, ...}

    -> Azure Cognitive Search, 10490 documents indexés au 2026-07-30,
    facettes Country/Industry/Region/Document type, contenu textuel réel
    par projet (Project_Description, Environmental_Social_Categorization_
    Rationale, Impact, Mitigation_Measures, Risk_Assessment...).

Ce script interroge CETTE API plutôt que de scraper le frontend JS —
conforme à la consigne "utilise l'API si disponible" (arbitrage du
2026-07-30). Playwright (déjà dans venv/) n'est pas nécessaire pour la
collecte de contenu ; il resterait une option de repli si cette API
disparaissait, mais n'est pas utilisé ici.

LIMITES ASSUMÉES (à connaître avant d'exploiter les contrôles collectés) :

1. **Pas de T0 automatique.** Le champ `Approval_Date` est vide sur la
   quasi-totalité des enregistrements observés (champ déprécié côté API).
   Ce script NE CALCULE PAS `time_to_event` ni de date d'approbation — la
   date « Board Date » de chaque contrôle retenu doit être vérifiée à la
   main sur sa page disclosures.ifc.org et ajoutée à `ifc_board_dates.py`,
   exactement comme les 39 projets déjà présents (voir la docstring de ce
   fichier). Volontairement pas de raccourci ici : inventer une date non
   vérifiée corromprait `time_to_event` en silence (cf. CORRECTIONS.md §2,
   qui documente pourquoi ça a été évité pour les projets déjà en corpus).
2. **Contenu plus mince que les PDFs complets.** `Mitigation_Measures`
   renvoie souvent un simple renvoi ("Please refer to the ESAP tab...")
   plutôt que le tableau d'actions/échéances détaillé — celui-ci vit dans
   le PDF ESRS complet, pas dans cette API. Le texte collecté ici est plus
   proche d'un résumé structuré que des documents complets de
   `scrape_cao.py`. À garder en tête si la comparabilité des chunks entre
   projets CAO et contrôles importe pour la Phase 2 (chunking).
3. **Appariement secteur/pays automatique, pas la validation finale.** Le
   script exclut les numéros de projet déjà dans le corpus et regroupe par
   (pays, secteur) — la validation qu'un contrôle est réellement comparable
   (même type de risque, échelle similaire) reste manuelle (cf. le prompt :
   "un projet minier en RDC ne se compare pas à un barrage au Brésil").

Usage :
    cd scripts/
    python scrape_ifc.py --dry-run --country Pakistan --industry Infrastructure --limit 5
    python scrape_ifc.py --from-cao-metadata --limit 20   # apparie automatiquement sur data/raw/cao_cases_metadata.csv (sortie de scrape_cao.py)
"""

import argparse
import csv
import html
import re
import time
from pathlib import Path

import requests

from ifc_board_dates import IFC_BOARD_DATES

BASE = Path(__file__).resolve().parent.parent
CORPUS_DIR = BASE / "corpus"
CAO_METADATA_PATH = BASE / "data/raw/cao_cases_metadata.csv"
OUTPUT_METADATA = BASE / "data/raw/ifc_controls_metadata.csv"

SEARCH_URL = "https://webapi.worldbank.org/aemsite/ifc-disclosure-search"
HEADERS = {"User-Agent": "ESGRiskIntelligence-MVP-Research/0.1 (local prototype; one-off dataset enrichment)"}
REQUEST_DELAY_S = 1.5  # SEUIL: aucun blocage observé en reconnaissance, délai de politesse par défaut malgré tout

# Champs textuels substantiels à agréger par projet — voir LIMITES ASSUMÉES
# ci-dessus pour ce qu'ils couvrent (et ne couvrent pas) réellement.
TEXT_FIELDS = [
    "Project_Description", "Environmental_Social_Categorization_Rationale",
    "Impact", "Mitigation_Measures", "Risk_Assessment", "Risk_Impact",
    "Environmental_Social_Info", "Environmental_Social_Issues", "ESAP",
    "Result",
]


# ============================================================================
# ÉTAPE 1 — Requête au moteur de recherche IFC
# ============================================================================

def search_ifc(session, filter_str=None, search_text="*", top=50, skip=0):
    """Un appel à l'API de recherche IFC (Azure Cognitive Search, confirmé
    public et sans authentification lors de la reconnaissance du 2026-07-30).
    """
    body = {"search": search_text, "count": True, "orderby": "Disclosed_Date desc", "top": top, "skip": skip}
    if filter_str:
        body["filter"] = filter_str
    resp = session.post(SEARCH_URL, json=body, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _odata_escape(value):
    return value.replace("'", "''")


def iter_projects(session, country, industry, page_size=50, delay=REQUEST_DELAY_S, max_pages=20):
    """Pagine sur tous les documents (Country_Description, Industry_Description)
    et regroupe par Project_Number -> liste de documents (un projet a souvent
    plusieurs enregistrements : Early Disclosure, Environmental Documents,
    Summary of Investment Information...).
    """
    filter_str = f"Country_Description eq '{_odata_escape(country)}' and Industry_Description eq '{_odata_escape(industry)}'"
    by_project = {}
    skip = 0
    for _ in range(max_pages):
        data = search_ifc(session, filter_str=filter_str, top=page_size, skip=skip)
        docs = data.get("value", [])
        if not docs:
            break
        for d in docs:
            by_project.setdefault(d["Project_Number"], []).append(d)
        skip += page_size
        if skip >= (data.get("@odata.count") or 0):
            break
        time.sleep(delay)
    return by_project


# ============================================================================
# ÉTAPE 2 — Critères d'appariement (depuis les cas CAO déjà collectés)
# ============================================================================

def pairing_criteria_from_cao_metadata(path=CAO_METADATA_PATH):
    """Lit data/raw/cao_cases_metadata.csv (sortie de scrape_cao.py) et
    retourne l'ensemble des (pays, secteur) distincts à apparier — un
    contrôle par combinaison, pas par cas individuel."""
    if not path.exists():
        return set()
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {(r["country"], r["sector"]) for r in rows if r.get("country") and r.get("sector")}


# ============================================================================
# ÉTAPE 3 — Construction du texte corpus par projet
# ============================================================================

_TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(raw):
    """Les champs de l'API contiennent des entités HTML (&#8220; ...) et
    parfois des balises simples — nettoyage minimal, pas un vrai parseur
    HTML (contenu déjà largement textuel, cf. reconnaissance du 2026-07-30)."""
    text = html.unescape(str(raw))
    text = _TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def build_project_text(project_number, documents):
    """Concatène les champs textuels substantiels de tous les documents
    d'un projet en un seul texte — un document par Document_Type_Description
    (Early Disclosure, Environmental Documents, Summary of Investment...),
    chacun avec ses propres champs remplis ou non."""
    parts = [f"Project {project_number} — {documents[0].get('Project_Name', '')}\n"]
    seen = set()
    for doc in documents:
        header = f"\n--- {doc.get('Document_Type_Description', 'Document')} ({doc.get('Disclosed_Date', '')[:10]}) ---\n"
        block = []
        for field in TEXT_FIELDS:
            val = doc.get(field)
            if not val:
                continue
            cleaned = _clean_text(val)
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                block.append(cleaned)
        if block:
            parts.append(header + "\n".join(block))
    return "\n".join(parts)


def safe_filename_part(s, max_len=40):
    s = re.sub(r"[^A-Za-z0-9]+", "", s)
    return (s or "x")[:max_len]


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--country", help="Filtre pays unique (ex: Pakistan) — alternative à --from-cao-metadata")
    parser.add_argument("--industry", help="Filtre secteur unique (ex: Infrastructure) — alternative à --from-cao-metadata")
    parser.add_argument("--from-cao-metadata", action="store_true",
                         help="Apparie automatiquement sur les (pays, secteur) de data/raw/cao_cases_metadata.csv")
    parser.add_argument("--limit", type=int, default=None, help="Ne traiter que N projets candidats au total (tests)")
    parser.add_argument("--dry-run", action="store_true", help="Collecte les métadonnées sans écrire les .txt dans corpus/")
    parser.add_argument("--delay", type=float, default=REQUEST_DELAY_S)
    args = parser.parse_args()

    if args.from_cao_metadata:
        pairs = sorted(pairing_criteria_from_cao_metadata())
        if not pairs:
            print(f"Aucun (pays, secteur) trouvé dans {CAO_METADATA_PATH} — lance scrape_cao.py d'abord, "
                  "ou précise --country/--industry directement.")
            return
    elif args.country and args.industry:
        pairs = [(args.country, args.industry)]
    else:
        parser.error("Précise soit --from-cao-metadata, soit --country ET --industry")
        return

    print(f"{len(pairs)} combinaison(s) (pays, secteur) à interroger : {pairs}")

    session = requests.Session()
    existing_numbers = set(IFC_BOARD_DATES.keys())
    # FRAGILE: même limite que scrape_cao.py — IFC_BOARD_DATES ne couvre que
    # les projets déjà sourcés manuellement (39 à ce jour), pas l'intégralité
    # potentielle de chunks.csv. Recouper avec chunks.csv en Étape 0c si des
    # doublons apparaissent.

    all_candidates = {}
    for country, industry in pairs:
        print(f"\nRecherche : {country} / {industry}...")
        try:
            by_project = iter_projects(session, country, industry, delay=args.delay)
        except requests.RequestException as e:
            print(f"  [ERREUR] requête échouée pour ({country}, {industry}) : {e}")
            continue
        new_here = {k: v for k, v in by_project.items() if k not in existing_numbers and k not in all_candidates}
        print(f"  {len(by_project)} projet(s) trouvés, {len(new_here)} nouveaux (absents du corpus)")
        all_candidates.update(new_here)

    candidates = list(all_candidates.items())
    if args.limit:
        candidates = candidates[: args.limit]
        print(f"\n--limit {args.limit} -> {len(candidates)} projets traités cette run")

    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    metadata_rows = []

    for i, (project_number, documents) in enumerate(candidates, 1):
        name = documents[0].get("Project_Name", "")
        country = documents[0].get("Country_Description", "")
        sector = documents[0].get("Industry_Description", "")
        print(f"[{i}/{len(candidates)}] {project_number} — {name} ({country}, {sector}) — {len(documents)} document(s)")

        text = build_project_text(project_number, documents)
        fname = f"IFC_{project_number}_{safe_filename_part(name)}_CTRL.txt"

        if not args.dry_run:
            dest = CORPUS_DIR / fname
            if dest.exists():
                print("  (déjà présent, non réécrit)")
            else:
                dest.write_text(text, encoding="utf-8")
                print(f"  -> {fname} ({len(text)} caractères)")
        else:
            print(f"  [DRY-RUN] {len(text)} caractères, non écrit")

        metadata_rows.append({
            "project_number":  project_number,
            "project_name":    name,
            "country":         country,
            "sector":          sector,
            "disclosed_date":  documents[0].get("Disclosed_Date", "")[:10],
            "n_documents":      len(documents),
            "corpus_file":      fname,
            "t0_status":        "A_VERIFIER",  # cf. LIMITES ASSUMÉES — pas de date inventée
        })

    if metadata_rows:
        OUTPUT_METADATA.parent.mkdir(parents=True, exist_ok=True)
        write_header = not OUTPUT_METADATA.exists()
        with open(OUTPUT_METADATA, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=metadata_rows[0].keys())
            if write_header:
                writer.writeheader()
            writer.writerows(metadata_rows)

    print(f"\nTerminé — {len(metadata_rows)} projet(s) contrôle(s) candidats"
          f"{' (dry-run)' if args.dry_run else ''}. "
          f"Rappel : t0_status=A_VERIFIER pour tous — voir ifc_board_dates.py avant d'utiliser ces "
          f"contrôles dans annote.py/model.build_training_data.")


if __name__ == "__main__":
    main()
