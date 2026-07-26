"""
PRÉCHAUFFAGE DU CACHE LLM (llm_confirm.py)
=============================================
Le filtre de polarité (llm_confirm.confirm_risk) est appelé de façon
synchrone, chunk par chunk, dans search.get_flag_scores_from_chunks — ce qui
est très bien pour l'inférence live (une poignée d'appels par document
uploadé), mais beaucoup trop lent en séquentiel pour ré-entraîner le Cox sur
tout le corpus (3962 paires (chunk, flag) mesurées sur les 46 projets
exploitables → ~132 min à ~2s/appel séquentiel).

CHOIX: préchauffer le cache disque (models/llm_confirm_cache.json) en
parallèle AVANT de lancer pipeline.py, plutôt que de paralléliser
get_flag_scores_from_chunks lui-même — garde cette fonction simple, et le
cache profite à la fois à l'entraînement et à l'inférence.

STATUT (2026-07-25) : NON RÉSOLU, préchauffage complet mis en pause — voir
checklist.md "Chantier ouvert — préchauffage du cache LLM". Mesuré : le
débit se dégrade sur charge SOUTENUE (au-delà de ~1-2 min de requêtes
continues), et ça ne semble pas être qu'une question de niveau de
concurrence — un test à 16 threads dégradait vite (5s → 90s/appel en
~1min30), un test à 4 threads semblait stable sur de courtes rafales
(12-26s, ~74 appels/min) mais s'est avéré TOUT AUSSI lent (~11 appels/min)
sur un run réel soutenu de plusieurs minutes. Cause probable : accumulation
de pression mémoire/contexte côté Ollama sur ce CPU, pas encore diagnostiquée
plus précisément (pistes non explorées : `OLLAMA_KEEP_ALIVE`, redémarrage
périodique du service, `OLLAMA_NUM_PARALLEL`). Le filtre live
(`search.get_flag_scores_from_chunks`, quelques appels par document
uploadé) n'est PAS affecté — il reste dans la fenêtre "courte rafale" où le
débit mesuré est bon. N'utiliser ce script qu'après avoir réglé la cause
racine, pas en l'état.

Usage :
    cd scripts/
    python warm_llm_cache.py                # tous les projets exploitables, 4 threads
    python warm_llm_cache.py --workers 6     # ajuster la concurrence
"""

import argparse
import time
import concurrent.futures
from pathlib import Path

import pandas as pd

import signals
import llm_confirm

BASE = Path(__file__).resolve().parent.parent
CHUNKS_PATH = BASE / "data/processed/chunks.csv"


def build_pending_pairs():
    """Réplique le filtre de model.build_training_data (projets annotés
    avec time_to_event exploitable) pour ne préchauffer que ce que le
    prochain `python pipeline.py` va réellement interroger."""
    chunks_df = pd.read_csv(CHUNKS_PATH)
    annotated = chunks_df.dropna(subset=["event"]).drop_duplicates("project_name")
    usable = annotated.dropna(subset=["time_to_event"])
    project_names = set(usable["project_name"])

    relevant = chunks_df[chunks_df["project_name"].isin(project_names)]

    pairs = set()
    for text in relevant["text"].astype(str):
        for flag_num in signals.flags_mentioned_in_text(text):
            pairs.add((text, flag_num))
    return list(pairs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    print("Construction de la liste des paires (chunk, flag)...", flush=True)
    pairs = build_pending_pairs()
    print(f"  {len(pairs)} paires candidates au total", flush=True)

    cache = llm_confirm._load_cache()
    pending = [
        (text, flag_num) for text, flag_num in pairs
        if llm_confirm._cache_key(text, flag_num) not in cache
    ]
    print(f"  {len(pairs) - len(pending)} déjà en cache, {len(pending)} à traiter", flush=True)

    if not pending:
        print("Rien à faire — cache déjà chaud.", flush=True)
        return

    t0 = time.time()
    done = 0
    print_every = 10  # FRAGILE: stdout est bufferisé si redirigé vers un fichier
    # sans flush=True — sans ça, aucune ligne n'apparaît avant la fin du process
    # (vécu : le premier run est resté invisible et bloqué sans le moindre signe).

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {
            ex.submit(llm_confirm.confirm_risk, text, flag_num, save=False): (text, flag_num)
            for text, flag_num in pending
        }
        for future in concurrent.futures.as_completed(futures):
            done += 1
            try:
                future.result()
            except Exception as e:
                text, flag_num = futures[future]
                print(f"  [ERREUR] flag{flag_num} sur chunk '{text[:50]}...' : {e}", flush=True)
            if done % print_every == 0 or done == len(pending):
                llm_confirm.flush_cache()  # CHOIX: écriture groupée plutôt qu'à chaque appel (voir confirm_risk(save=))
                dt = time.time() - t0
                rate = done / dt * 60
                eta = (len(pending) - done) / (done / dt) if done < len(pending) else 0
                print(f"  {done}/{len(pending)} — {rate:.0f} appels/min — ETA {eta/60:.1f} min", flush=True)

    llm_confirm.flush_cache()
    dt = time.time() - t0
    print(f"\nTerminé — {len(pending)} paires traitées en {dt/60:.1f} min "
          f"({len(pending)/dt*60:.0f} appels/min)", flush=True)


if __name__ == "__main__":
    main()
