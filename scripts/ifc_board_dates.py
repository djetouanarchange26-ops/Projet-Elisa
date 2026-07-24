"""
Dates d'approbation ("Board Date") des projets IFC présents dans le corpus.

Source : pages de divulgation publiques disclosures.ifc.org
(project-detail/SPI ou SII/{numéro}/...), champ "Approved" de la section
"Previous Events" / "Summary of Investment Information". Recherchées et
vérifiées une par une le 2026-07-14.

Sert de T0 (date de référence, début d'exposition au risque) pour calculer
time_to_event = durée jusqu'à la plainte CAO (ou jusqu'à aujourd'hui pour
les projets censurés). Voir annote.py.

FRAGILE: ne couvre que les 23 numéros IFC présents dans data/processed/
chunks.csv. Les ~37 autres lignes de corpus_cao_ifc.xlsx sont encore
marquées "à vérifier" et ne sont pas dans le corpus — pas de date à
chercher tant qu'elles n'y sont pas.
"""

IFC_BOARD_DATES = {
    "25797": "2008-04-08",  # Tata Ultra Mega (Coastal Gujarat Power)
    "24408": "2007-04-26",  # Bujagali Energy
    "35349": "2018-09-06",  # Daehan Wind Power (Tafila)
    "29197": "2011-01-06",  # Togo LCT (Lomé Container Terminal)
    "24803": "2006-12-19",  # Lonmin
    "44364": "2022-07-21",  # Zarafshon Wind
    "33557": "2013-09-12",  # Delonex Energy
    "36699": "2015-07-09",  # Africa Oil
    "32408": "2013-06-03",  # Palma Guinée (Sheraton Conakry)
    "39729": "2017-07-20",  # Al Subh Solar Power
    "39995": "2017-07-20",  # Acciona Benban 2
    "39997": "2017-07-20",  # Acciona Benban 3
    "35483": "2014-09-16",  # Falcon Ma'an Solar Power
    "26031": "2008-05-15",  # CIFI
    "36008": "2016-05-19",  # Karot Hydro
    "37673": "2018-07-19",  # Nachtigal Hydropower
    "50035": "2025-03-14",  # Antalya Airport LTF
    "31632": "2013-10-24",  # Alto Maipo
    "30979": "2011-09-28",  # enso Albania (Lengarica)
    "31383": "2012-11-29",  # Reventazón HPP
    "39102": "2018-03-08",  # Bujagali 2 (Refi)
    "32874": "2015-01-21",  # Gulpur Hydro (CONTRÔLE)
    "36402": "2015-11-11",  # KTDA Small Hydro (CONTRÔLE)

    # Ajoutés le 2026-07-23 — projets "contrôle" (event=0) scrapés sur
    # disclosures.ifc.org pour rééquilibrer le dataset (28 event=1 / 2
    # event=0 avant ajout). Vérifiés individuellement absents de la base
    # CAO (cao-ombudsman.org) — voir data/raw/corpus_cao_ifc.xlsx pour le
    # détail des sources par projet.
    "30266": "2013-05-16",  # Zhaoheng Hydropower Holdings (CONTRÔLE)
    "29405": "2010-12-07",  # Cheves Hydro (CONTRÔLE)
    "28083": "2010-05-13",  # Butwal Power Co / Andhi Khola (CONTRÔLE)
    "36729": "2015-04-29",  # Cullinan / Petra Diamonds (CONTRÔLE)
    "28215": "2009-06-19",  # Antares Minerals (CONTRÔLE)
    "30053": "2013-02-22",  # SEI Solar Power (CONTRÔLE)
    "28842": "2010-05-13",  # Solar Power Korat 1 (CONTRÔLE)
    "33943": "2013-07-08",  # Mersin International Port (CONTRÔLE)
    "28544": "2010-03-18",  # Santa Marta International Terminal (CONTRÔLE)
    "29472": "2010-05-21",  # TCE Ege Konteyner Terminal (CONTRÔLE)
    "25637": "2007-05-22",  # GSPL — Gujarat State Petronet (CONTRÔLE)
    "32859": "2014-05-01",  # Azura Edo IPP (CONTRÔLE)
    "36787": "2016-10-27",  # Mocuba Solar (CONTRÔLE)
    "33839": "2017-10-06",  # Dolovo Wind / Čibuk 1 (CONTRÔLE)
    "27746": "2010-01-22",  # SMP Gold — Saza Makongolosi (CONTRÔLE)
    "27274": "2010-12-19",  # E-Power S.A. (CONTRÔLE)
}
