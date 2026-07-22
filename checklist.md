# CHECKLIST FINALISATION MVP

## Ce qu'il manque dans search.py (à vérifier)

`model.py`, `explain.py` et `analyze.py` importent ces fonctions depuis `search.py` :

```python
search.load_search_components()    # → (model, index, metadata)
search.get_flag_scores(text, model, index, metadata, k=15)  # → dict
search.search_similar(text, model, index, metadata, k=15)   # → list[dict]
```

Vérifie que `search.py` exporte bien ces 3 fonctions avec ces signatures.
Si les noms sont différents dans ton fichier, soit tu les renommes dans search.py,
soit tu modifies les imports dans model.py / analyze.py.

---

## Données — avant de lancer `pipeline.py`

- [ ] `data/raw/corpus_cao_ifc.xlsx` contient les colonnes :
  - `project_name` (doit matcher exactement les noms dans chunks.csv)
  - `project_id` (optionnel mais utile)
  - `time_to_event` (en mois, > 0 pour tous)
  - `event` (0 ou 1)
  - `flag_type` (1, 2, ou 3)
- [ ] ≥30 projets dont ≥15 avec event=1
- [ ] Chaque flag a ≥5 projets représentatifs
- [ ] 15-20 projets "propres" (event=0) inclus
- [ ] `chunks.csv` colonnes : project_name, text, chunk_id, flag_type, event

---

## Séquence de lancement

```bash
cd C:/Users/djeto/Desktop/Projet-Elisa/scripts

# 1. D'abord : ré-entraîner tout (embeddings → FAISS → Cox)
python pipeline.py

# 2. Ensuite : lancer les tests
python tests.py

# 3. Si tout passe : tester la pipeline complète
python analyze.py

# 4. Lancer l'app Streamlit
cd ..
streamlit run app.py
```

---

## Modèle — après le premier entraînement

- [ ] C-index > 0.6
- [ ] Hazard ratios cohérents (consulter `cox.print_summary()`)
- [ ] Seuils de risk_grade validés (dans `model.py`, fonction `predict_risk`)
- [ ] SHAP < 15s par prédiction (sinon réduire `n_background` dans explain.py)

---

## Intégration avec app.py

Dans `app.py`, l'import doit être :
```python
# Ajouter le dossier scripts au path
import sys
sys.path.insert(0, "scripts")
from analyze import analyze
```

Ou si tu préfères la structure package :
```python
from scripts.analyze import analyze
```
(dans ce cas, ajoute un fichier `scripts/__init__.py` vide)

---

## Ajustements rapides (chercher les commentaires)

| Ce que tu veux changer | Où modifier | Commentaire à chercher |
|---|---|---|
| Méthode d'agrégation des scores (max / mean / weighted) | `search.py` → `get_flag_scores()` | `# ALT:` |
| Seuils de risk grade | `model.py` → `predict_risk()` | `# SEUIL:` |
| Régularisation Cox | `model.py` → `train_cox()` | `penalizer=` |
| Vitesse SHAP | `explain.py` → `create_shap_explainer()` | `n_background` |
| Précision SHAP | `explain.py` → `explain_prediction()` | `nsamples=` |
| Mots-clés de signaux | `analyze.py` → `_extract_signals()` | `signal_keywords` |
| Nombre de voisins FAISS | `analyze.py` → `analyze()` | `k=15` |
| Horizon de prédiction | `analyze.py` → `analyze()` | `horizon_months=` |
| Labels des flags | `explain.py` → `explain_prediction()` | `flag_labels` |