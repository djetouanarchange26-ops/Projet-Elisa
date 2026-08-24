"""
CONSERVATION DES ANALYSES — persistance sur disque (directive "multi-doc ->
un seul document + conservation", 2026-08-20)
=====================================================================
Permet à l'analyste de retrouver une analyse déjà faite (Portfolio
Dashboard) sans ré-uploader le document ni relancer le pipeline LLM.

CHOIX: fichiers JSON sur disque, pas de base de données — rien de tel
dans le stack actuel (docker-compose : app/ollama/caddy, aucun service
DB), et grid_result.py documente déjà result_v4 comme "sérialisable en
JSON sans transformation". Cohérent avec models/corpus/ (fichiers,
gitignorés) plutôt que d'introduire une dépendance lourde pour un MVP.

Scope volontairement V4 uniquement (pipeline legacy non concerné, cf.
app.py : le pipeline legacy garde son historique de session existant,
inchangé — legacy est en voie de retrait, pas la peine d'y investir).

FRAGILE: pas d'index séparé — list_analyses() relit chaque fichier JSON
du dossier à chaque appel pour construire les résumés. Correct et simple
pour un volume d'analyses MVP (dizaines, pas milliers) ; si le volume
grossit, un index (CSV/SQLite léger) éviterait de tout relire à chaque
affichage du dashboard — pas fait ici, prématuré.
"""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

ANALYSES_DIR = Path(__file__).resolve().parent.parent / "data" / "analyses"


def _slugify(name, max_len=40):
    """Nom de fichier sûr à partir du nom de document — même esprit que
    app._safe_filename, dupliqué ici pour ne pas créer une dépendance
    scripts/ -> app.py (app.py importe scripts/, jamais l'inverse)."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", str(name)).strip("_")
    return (slug or "document")[:max_len]


def save_analysis(result_v4, document, documents, analyzed_at):
    """Persiste une analyse V4 complète sur disque (un fichier JSON par
    analyse, nommé par timestamp pour un tri chronologique trivial par
    nom de fichier). Fail-open (ADR-002, même esprit que les appels LLM) :
    ne lève jamais, retourne le Path créé ou None si l'écriture échoue —
    une sauvegarde ratée ne doit jamais faire échouer l'analyse elle-même.

    result_v4 : dict (grid_result.build_grid_result), déjà sérialisable
        en JSON tel quel (aucune transformation ici).
    document : str — doc_label (nom affiché), pour le nom de fichier et
        l'affichage dans Portfolio Dashboard.
    documents : list[str] — cf. app.py, un seul élément (un seul document
        par analyse, MVP 2026-08-20).
    analyzed_at : datetime — horodatage réel du clic "Run Analysis"
        (cf. app.py), converti en ISO 8601 pour le JSON.
    """
    scoring = (result_v4 or {}).get("scoring", {})
    detection = (result_v4 or {}).get("document_type_detection") or {}
    timestamp_str = analyzed_at.strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp_str}_{_slugify(document)}_{scoring.get('score', 'NA')}.json"
    path = ANALYSES_DIR / filename

    payload = {
        "document": document,
        "documents": documents,
        "analyzed_at": analyzed_at.isoformat(),
        "score": scoring.get("score"),
        "color": scoring.get("color"),
        "questions_active": scoring.get("questions_active"),
        "document_type": (result_v4 or {}).get("document_type"),
        "reading_mode_label": (result_v4 or {}).get("reading_mode_label"),
        "detection_source": detection.get("source"),
        "result_v4": result_v4,
    }
    try:
        ANALYSES_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("analysis_store: échec sauvegarde de l'analyse (%s) : %s", path, e)
        return None
    return path


def list_analyses():
    """Liste les analyses sauvegardées, de la plus récente à la plus
    ancienne. Résumés légers (sans result_v4 complet) — cf.
    load_analysis() pour charger le détail complet d'une entrée. Un
    fichier illisible/corrompu est ignoré (loggé), pas une exception qui
    casserait tout le dashboard pour une seule entrée abîmée."""
    if not ANALYSES_DIR.exists():
        return []

    summaries = []
    for path in sorted(ANALYSES_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("analysis_store: fichier ignoré (illisible) %s : %s", path, e)
            continue
        summaries.append({
            "path": path,
            "document": data.get("document"),
            "documents": data.get("documents"),
            "analyzed_at": data.get("analyzed_at"),
            "score": data.get("score"),
            "color": data.get("color"),
            "questions_active": data.get("questions_active"),
            "document_type": data.get("document_type"),
            "reading_mode_label": data.get("reading_mode_label"),
            "detection_source": data.get("detection_source"),
        })
    return summaries


def load_analysis(path):
    """Charge le détail complet (result_v4 inclus) d'une analyse
    sauvegardée. Retourne None (pas d'exception) si le fichier est
    manquant/corrompu — fail-open, cf. save_analysis."""
    path = Path(path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("analysis_store: échec chargement %s : %s", path, e)
        return None


def delete_analysis(path):
    """Supprime définitivement une analyse sauvegardée (Portfolio
    Dashboard, action irréversible confirmée côté UI). Fail-open (ADR-002,
    même esprit que save_analysis/load_analysis) : ne lève jamais.
    Retourne True si le fichier a été supprimé, False sinon (déjà absent
    ou erreur disque — l'appelant affiche une erreur dans ce cas)."""
    path = Path(path)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError as e:
        logger.warning("analysis_store: échec suppression %s : %s", path, e)
        return False
