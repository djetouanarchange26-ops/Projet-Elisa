"""
Mots-clés de signaux ESG par flag — source unique partagée entre :
  - analyze.py   : détection de signaux dans le document uploadé (surlignage)
  - annote.py    : ré-annotation des chunks du corpus par contenu réel
                    (plutôt que par héritage du flag_type du projet entier)

CHOIX: recherche de mots-clés prédéfinis directement dans le texte.
ALT: zero-shot classification avec un modèle NLP (plus précis, plus lent)
ALT: appeler un LLM pour résumer les passages en signaux (le plus précis)
TODO: enrichir ces listes avec le feedback de ton associée
"""

import re

SIGNAL_KEYWORDS = {
    1: {
        "community opposition":  ["opposition", "protest", "community", "resist", "grievance"],
        "displacement risk":     ["displace", "resettle", "relocat", "involuntary", "land acquisition"],
        "stakeholder conflict":  ["stakeholder", "conflict", "indigenous", "livelihood", "affected people"],
        "consultation gaps":     ["consultation", "FPIC", "consent", "engagement", "participation"],
    },
    2: {
        "pollution risk":        ["pollut", "contaminat", "emission", "discharge", "effluent"],
        "monitoring gaps":       ["monitor", "threshold", "exceedance", "baseline", "sampling"],
        "spill risk":            ["spill", "leak", "seepage", "tailings", "waste"],
    },
    3: {
        "biodiversity threat":   ["biodiversity", "habitat", "critical habitat", "PS6", "endangered", "species"],
        "ESAP delays":           ["ESAP", "action plan", "delay", "overdue", "non-compliance"],
        "PS non-conformance":    ["performance standard", "PS1", "PS2", "PS3", "PS4", "PS5", "PS7", "PS8"],
    },
}
# ALT: ajouter des catégories supplémentaires :
# 4: {"governance risk": ["governance", "board", "transparency", "audit"]}

SIGNAL_PATTERNS = {
    (flag_num, signal_name): re.compile(
        r"\b(?:" + "|".join(re.escape(kw) for kw in keywords) + r")\w*",
        re.IGNORECASE,
    )
    for flag_num, keywords_by_signal in SIGNAL_KEYWORDS.items()
    for signal_name, keywords in keywords_by_signal.items()
}


def flags_mentioned_in_text(text):
    """Retourne l'ensemble des numéros de flag (1, 2, 3) dont au moins un
    mot-clé apparaît dans `text`. Utilisé par annote.py pour ne garder le
    flag_type d'un chunk que si son contenu le justifie réellement, au lieu
    de l'hériter en bloc du projet entier (qui bruite la recherche FAISS
    avec des chunks administratifs/génériques).
    """
    found = set()
    for (flag_num, _signal_name), pattern in SIGNAL_PATTERNS.items():
        if flag_num in found:
            continue
        if pattern.search(text):
            found.add(flag_num)
    return found
