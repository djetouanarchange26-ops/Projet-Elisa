# Directive Claude Code — Outil d'Analyse ESG Bancaire

## CONTEXTE

Tu travailles sur un outil d'analyse ESG (Environnement, Social, Gouvernance) destiné à une banque. L'architecture actuelle repose sur :
- **LLM** pour l'analyse textuelle des rapports et documents ESG
- **FAISS** comme index vectoriel pour le retrieval (RAG)
- **Modèle de Cox** (survie) pour la modélisation du risque
- **Embeddings** pour la représentation sémantique des documents

### Problème identifié
Les analyses produites sont **trop superficielles** : elles paraphrasent les rapports ESG sans capter les signaux faibles, les contradictions, les omissions, ni les risques latents. L'outil se comporte comme un résumeur au lieu d'un analyste.

---

## PHASE 1 — AUDIT DU CODE EXISTANT

Avant toute modification, fais un audit complet du projet. Explore l'intégralité du codebase et produis un rapport structuré couvrant :

### 1.1 Architecture
- Cartographie tous les modules, leur rôle, et leurs dépendances
- Identifie le pipeline complet : ingestion → chunking → embedding → indexation FAISS → retrieval → prompt LLM → scoring Cox → output final
- Documente les modèles utilisés (quel LLM, quel modèle d'embedding, quelle config FAISS)
- Identifie les sources de données consommées (rapports PDF, APIs, bases internes, etc.)

### 1.2 Chunking & Indexation
- Comment les documents sont-ils découpés ? (taille fixe ? overlap ? sémantique ?)
- Quel modèle d'embedding est utilisé ? Quelle dimension ?
- Comment l'index FAISS est-il construit ? (IndexFlatL2, IVF, HNSW ?)
- Y a-t-il un re-ranking après le retrieval FAISS ?
- Les métadonnées sont-elles conservées avec les chunks ? (source, date, section, entreprise)

### 1.3 Prompting & Chaîne LLM
- Quels sont les prompts système et utilisateur actuels ?
- Y a-t-il une chaîne multi-étapes ou un seul appel LLM ?
- Le LLM reçoit-il du contexte au-delà des chunks récupérés ?
- Y a-t-il des instructions pour détecter les contradictions ou omissions ?

### 1.4 Modèle de Cox
- Quelles features alimentent le modèle ?
- Comment les scores ESG sont-ils transformés en covariables ?
- Y a-t-il des termes d'interaction ou des features de second ordre ?
- Quelle est la performance actuelle (C-index, calibration) ?

### 1.5 Output & Reporting
- Quel format de sortie ? (score, rapport texte, dashboard)
- Les analyses sont-elles traçables ? (quelles sources ont mené à quelle conclusion)
- Y a-t-il un système de confiance/incertitude sur les analyses ?

Produis ce rapport d'audit dans un fichier `AUDIT_ESG.md` à la racine du projet.

---

## PHASE 2 — AMÉLIORATIONS À IMPLÉMENTER

Une fois l'audit terminé, implémente les améliorations suivantes **dans l'ordre de priorité**. Chaque amélioration doit être un commit séparé avec un message clair.

### 2.1 [PRIORITÉ HAUTE] Chunking sémantique hiérarchique

**Problème** : le chunking à taille fixe casse les unités argumentatives et noie les signaux faibles.

**Implémentation** :
- Remplace le chunking fixe par un chunking sémantique basé sur la cohérence thématique
- Chaque chunk doit représenter une **unité argumentative** : un claim + son evidence
- Implémente une hiérarchie à 3 niveaux :
  - **Document** → métadonnées globales (entreprise, date, type de rapport)
  - **Section** → thème ESG (environnement, social, gouvernance, sous-catégories)
  - **Chunk** → assertion unitaire avec son contexte
- Conserve les métadonnées enrichies avec chaque chunk :
  ```python
  {
      "text": "...",
      "company": "...",
      "report_date": "...",
      "section": "environmental/emissions",
      "chunk_type": "claim|metric|commitment|narrative",
      "entities": [...],
      "temporal_refs": [...],  # dates et horizons mentionnés
      "sentiment": float,
      "specificity_score": float  # à quel point c'est concret vs vague
  }
  ```
- Calcule un **specificity_score** : les formulations vagues ("nous nous engageons à réduire...") scorent bas, les métriques précises ("réduction de 12% du Scope 1 entre 2022 et 2023") scorent haut. Ce score est un signal ESG en soi.

### 2.2 [PRIORITÉ HAUTE] Re-ranking cross-encoder

**Problème** : FAISS retourne les chunks les plus similaires lexicalement, pas les plus pertinents analytiquement.

**Implémentation** :
- Après le retrieval FAISS (top-k, k=20-50), applique un re-ranker cross-encoder
- Modèle recommandé : `cross-encoder/ms-marco-MiniLM-L-12-v2` ou équivalent
- Le re-ranker doit scorer la pertinence **analytique**, pas juste la similarité
- Implémente un scoring composite :
  ```
  score_final = α * score_cross_encoder + β * score_recency + γ * score_specificity + δ * score_source_credibility
  ```
  - `score_recency` : les données récentes pèsent plus
  - `score_specificity` : les chunks avec des métriques concrètes pèsent plus
  - `score_source_credibility` : données réglementaires > rapport entreprise > presse

### 2.3 [PRIORITÉ HAUTE] Pipeline d'analyse LLM multi-pass

**Problème** : un seul appel LLM produit du résumé, pas de l'analyse.

**Implémentation** — Crée un pipeline à 4 passes séquentielles :

#### Pass 1 — Extraction structurée
```
SYSTEM: Tu es un extracteur de données ESG. À partir des documents fournis,
extrais UNIQUEMENT les faits dans le schéma JSON suivant. Ne résume pas,
n'interprète pas. Si une information est absente, indique "NON_MENTIONNÉ".

Schéma :
{
  "engagements": [{"description", "horizon_temporel", "métrique_cible", "baseline", "progression_actuelle"}],
  "métriques_reportées": [{"indicateur", "valeur", "unité", "période", "périmètre", "vérifié_par_tiers": bool}],
  "incidents_controverses": [{"description", "date", "impact", "réponse_entreprise"}],
  "gouvernance": {"composition_board", "comité_esg_dédié", "rémunération_liée_esg", "turnover_dirigeants"},
  "supply_chain": {"tier1_visibilité", "audit_fournisseurs", "concentration_géographique"},
  "formulations_évasives": ["liste des phrases vagues ou non-engageantes détectées"]
}
```

#### Pass 2 — Détection de contradictions et d'omissions
```
SYSTEM: Tu es un analyste ESG forensique spécialisé dans la détection de
greenwashing et de risques cachés. Tu reçois :
- Les faits extraits de l'entreprise (Pass 1)
- Des données de référence sectorielles
- Des données réglementaires et juridiques externes

Ta mission : identifier avec précision :

1. CONTRADICTIONS : écarts entre ce que l'entreprise dit et ce que les données
   montrent. Cite les deux sources en regard.

2. OMISSIONS SUSPECTES : sujets ESG matériels pour ce secteur qui ne sont
   PAS mentionnés dans le rapport. Compare avec la matrice de matérialité
   sectorielle (SASB/GRI).

3. FORMULATIONS ÉVASIVES : engagements sans baseline, sans horizon, sans
   métrique, ou avec des qualificatifs ("dans la mesure du possible",
   "nous aspirons à"). Score de 1 (engageant) à 5 (évasif).

4. TRAJECTOIRE : les métriques s'améliorent-elles réellement ou l'entreprise
   change-t-elle de périmètre/méthodologie pour masquer une stagnation ?

Pour chaque finding, attribue :
- severity: critical | high | medium | low
- confidence: high | medium | low
- evidence: citations exactes des sources
```

#### Pass 3 — Analyse contrefactuelle et scénarios
```
SYSTEM: Tu es un analyste de risque quantitatif. À partir des findings
de l'analyse ESG (Pass 2), construis des scénarios d'impact :

Pour chaque risque identifié (severity >= medium) :
1. SCÉNARIO DE MATÉRIALISATION : que se passe-t-il concrètement si ce risque
   se réalise ? (amende, litige, perte de licence, attrition clients, coût de
   remédiation)
2. ESTIMATION D'IMPACT : fourchette financière (% du CA, % de l'EBITDA,
   impact sur le spread de crédit) basée sur des précédents sectoriels
3. PROBABILITÉ : estimate basée sur la trajectoire et les précédents
4. HORIZON TEMPOREL : court terme (<1 an), moyen terme (1-3 ans), long terme (>3 ans)
5. FACTEURS AGGRAVANTS / ATTÉNUANTS

Produis un JSON structuré exploitable par le modèle de Cox.
```

#### Pass 4 — Synthèse analytique
```
SYSTEM: Tu es l'analyste ESG senior qui rédige la note finale pour le comité
de crédit. Tu disposes de toute l'analyse précédente.

Rédige une analyse qui :
- COMMENCE par la conclusion (recommandation + score)
- DISTINGUE les risques déclarés (connus du marché) des risques latents
  (détectés par notre analyse)
- QUANTIFIE chaque risque avec une fourchette d'impact
- IDENTIFIE les catalyseurs potentiels (réglementation à venir, échéances
  d'engagements, etc.)
- COMPARE avec les pairs sectoriels
- ATTRIBUE un SCORE DE CONFIANCE global à l'analyse

Ton analyse doit apporter de la valeur ajoutée par rapport au consensus.
Ce que tout le monde sait déjà n'est pas intéressant. Concentre-toi sur
ce que les autres ont raté.
```

### 2.4 [PRIORITÉ MOYENNE] Features avancées pour le modèle de Cox

**Problème** : les covariables actuelles sont trop évidentes et capturent ce que le marché price déjà.

**Implémentation** — Ajoute ces features :

```python
# Features de second ordre (dérivées)
features_avancees = {
    # Trajectoire et volatilité
    "esg_score_trend_12m": "",        # pente de régression linéaire du score sur 12 mois
    "esg_score_volatility_12m": "",   # écart-type du score sur 12 mois
    "esg_momentum": "",               # accélération : trend actuel vs trend précédent

    # Écarts et contradictions (OUTPUT du Pass 2)
    "gap_declared_vs_observed": "",   # écart entre score déclaré et score implicite
    "omission_count": "",             # nombre d'omissions matérielles détectées
    "evasiveness_score": "",          # score moyen de formulation évasive
    "contradiction_severity_sum": "", # somme pondérée des contradictions

    # Contexte sectoriel
    "esg_vs_sector_median": "",       # positionnement relatif dans le secteur
    "esg_vs_sector_best": "",         # écart avec le best-in-class
    "regulatory_exposure": "",        # score d'exposition réglementaire (taxonomie EU, CSRD, etc.)

    # Interactions clé (non-linéarités)
    "env_x_gov_interaction": "",      # E faible + G faible = risque multiplicatif
    "controversy_x_trend": "",        # controverse + tendance négative = signal fort
    "size_x_esg_gap": "",             # grosse entreprise + gros écart = plus de scrutiny

    # Signaux de marché
    "cds_spread_residual": "",        # spread CDS non expliqué par le financier pur
    "esg_event_market_beta": "",      # sensibilité du titre aux news ESG
}
```

- Implémente la génération automatique de ces features dans le pipeline
- Ajoute une validation : corrélation croisée, VIF pour la multicolinéarité
- Log l'importance des features (SHAP ou permutation importance) pour traçabilité

### 2.5 [PRIORITÉ MOYENNE] Enrichissement des sources de données

**Problème** : se baser uniquement sur les rapports ESG officiels = analyser le marketing.

**Implémentation** :
- Crée un module d'ingestion pour les **données alternatives** :
  - Sanctions et amendes réglementaires (si APIs disponibles)
  - Données de turnover dirigeants (départs de C-suite, rotation du board)
  - Controverses presse (avec analyse de sentiment et de gravité)
- Chaque source doit avoir un **score de crédibilité** et une **date de fraîcheur**
- Indexe ces données alternatives dans FAISS avec un tag `source_type` pour que le retriever puisse pondérer

### 2.6 [PRIORITÉ BASSE] Gap Analysis automatisé

**Implémentation** — Module de triangulation systématique :

```
┌─────────────────────┐
│  CE QUE L'ENTREPRISE │ ← rapports ESG, CDP, communiqués
│  DIT                 │
└────────┬────────────┘
         │ comparaison automatique
         ▼
┌─────────────────────┐
│  CE QUE LES DONNÉES │ ← régulateur, données alt, satellites, presse
│  MONTRENT            │
└────────┬────────────┘
         │ comparaison automatique
         ▼
┌─────────────────────┐
│  CE QUE LE MARCHÉ   │ ← spreads CDS, multiples, beta ESG, ratings
│  PRICE               │
└─────────────────────┘
```

- Pour chaque entreprise analysée, calcule les **écarts** entre ces 3 couches
- Chaque écart significatif génère une **alerte** avec un niveau de sévérité
- Les écarts sont les inputs les plus précieux pour le modèle de Cox

---

## PHASE 3 — TESTS ET VALIDATION

### 3.1 Tests de qualité des analyses
- Compare les outputs avant/après sur un échantillon de 5-10 entreprises
- Vérifie que les analyses post-amélioration détectent des éléments que l'ancien pipeline manquait
- Mesure le taux de "findings non-triviaux" (contradictions, omissions) par analyse

### 3.2 Tests techniques
- Benchmark de performance du re-ranker (latence acceptable ?)
- Vérification que le pipeline multi-pass respecte les limites de tokens
- Tests de régression sur le modèle de Cox avec les nouvelles features

### 3.3 Traçabilité
- Chaque conclusion de l'analyse finale doit être traçable jusqu'à sa source
- Implémente un système de citations/références dans l'output

---

## CONTRAINTES TECHNIQUES

- Maintiens la compatibilité avec l'architecture existante — refactore, ne réécris pas from scratch
- Chaque amélioration doit être activable/désactivable via config (feature flags)
- Documente chaque module ajouté (docstrings + README)
- Gère les erreurs gracieusement : si une pass LLM échoue, l'analyse doit quand même produire un résultat (dégradé mais fonctionnel)
- Attention aux coûts API LLM : le pipeline multi-pass multiplie les appels. Implémente un cache intelligent pour les analyses déjà faites sur les mêmes documents

---

## ORDRE D'EXÉCUTION

1. **Audit** (Phase 1) → produit `AUDIT_ESG.md`
2. **Revue avec moi** → on valide ensemble les priorités
3. **Implémentation** (Phase 2) → par ordre de priorité, commit par commit
4. **Tests** (Phase 3) → validation sur cas réels
