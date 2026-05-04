"""Routing par détection d'intention — V2 amélioration.

Inspiré du pattern classique RAG : analyser la question utilisateur AVANT
le retrieval pour adapter la stratégie (filter metadata, top_n, format
de réponse).

Pourquoi c'est mieux qu'un retrieval uniforme ?
  - Question type "C13 ?" → on cherche directement le chunk C13 (filter
    metadata sur Qdrant), réponse en 1 chunk au lieu de 10 → -90% latence
    LLM, plus de précision.
  - Question type "quelle différence entre C13 et C19" → on récupère les
    2 chunks ciblés au lieu de top-10 hybrid → meilleure comparaison.
  - Question type "combien de blocs ?" → réponse pré-calculée depuis
    constantes, pas d'appel LLM, instantané.

Approche : regex robustes + extraction d'entités (numéros de compétences).
Pas de LLM-based routing pour rester rapide et déterministe — un classifier
ML aurait été overkill pour 6 intents bien définis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class Intent(StrEnum):
    """Type d'intention détectée dans la question utilisateur."""

    SPECIFIC_COMPETENCE = "specific_competence"  # "C13", "que dit C9"
    DEFINITION = "definition"  # "c'est quoi C5", "définis le bloc 2"
    COMPARISON = "comparison"  # "compare C13 et C19"
    COVERAGE_ANALYSIS = "coverage_analysis"  # "quelles compétences couvre mon projet"
    META = "meta"  # "combien de compétences au total", "liste les blocs"
    JURY_INTERVIEW = "jury_interview"  # "/jury", "prépare-moi à la soutenance"
    SMALL_TALK = "small_talk"  # "salut", "qui es-tu", "quel est ton rôle"
    GENERAL = "general"  # fallback : retrieval hybrid standard


@dataclass
class IntentResult:
    """Résultat de la classification d'une question.

    Attributes:
        intent: Type d'intention détectée.
        competences: Numéros de compétences mentionnés (ex: ["C13", "C19"]).
        suggested_top_n: Nombre suggéré de chunks à retrieve pour cet intent.
        bypass_rag: Si True, la question peut être répondue sans appel RAG.
        in_scope: Si False, la question est hors du domaine RNCP/dev — l'app
            doit répondre poliment au lieu de lancer un RAG bidon.
    """

    intent: Intent
    competences: list[str] = field(default_factory=list)
    suggested_top_n: int = 10
    bypass_rag: bool = False
    in_scope: bool = True


# Patterns regex compilés (init module = une seule fois)
# On utilise des word boundaries (\b) pour éviter les faux positifs.
COMPETENCE_PATTERN = re.compile(r"\bC(\d{1,2})\b")

DEFINITION_PATTERN = re.compile(
    r"\b(c'?est quoi|qu'?est[- ]ce que|que (?:veut dire|signifie)|définition|définis|décris|explique[- ]moi)\b",
    re.IGNORECASE,
)

COMPARISON_PATTERN = re.compile(
    r"\b(compar(?:e|er|aison)|différence(?:s)? entre|vs\.?|versus)\b",
    re.IGNORECASE,
)

COVERAGE_PATTERN = re.compile(
    r"\b(quelles? compétences?|couvre|valide(?:s)?|manque(?:nt)?|projet)\b",
    re.IGNORECASE,
)

META_PATTERN = re.compile(
    r"\b(combien de (?:compétences?|blocs?)|liste des? (?:blocs?|compétences?)|"
    r"total des? compétences?|nombre de blocs?)\b",
    re.IGNORECASE,
)

JURY_PATTERN = re.compile(
    r"(?:^|\s)(/jury|jury|entretien|soutenance|prépare[- ]?moi|simul(?:e|ation))\b",
    re.IGNORECASE,
)

# Small talk : salutations + questions sur l'identité du bot.
# On match au début de la question pour éviter de bloquer une vraie analyse
# ("Bonjour, voici mon projet FastAPI..." ne doit PAS être small talk).
SMALL_TALK_PATTERN = re.compile(
    r"^\s*(salut|bonjour|hello|hey|coucou|yo|"
    r"qui es[- ]?tu|t'es qui|c'est quoi ce bot|"
    r"quel est ton (?:rôle|role|but)|tu sers à quoi|"
    r"que (?:fais|peux)[- ]?tu|aide(?:[- ]?moi)?)\b",
    re.IGNORECASE,
)

# Mots-clés "dans le scope" du bot : RNCP, dev IA, projet, technos, etc.
# Si la question est en GENERAL et ne contient AUCUN de ces mots, on
# répond poliment hors-scope au lieu de lancer un RAG bidon (météo, blagues, etc.).
# Liste pensée pour être large mais pertinente — éviter les mots trop génériques.
SCOPE_KEYWORDS_PATTERN = re.compile(
    r"\b(?:"
    # RNCP / formation
    r"rncp|compétences?|bloc|simplon|soutenance|jury|formation|dossier|titre|"
    r"référentiel|certification|évaluation|"
    # Projet / code
    r"projets?|repos?|code|app(?:lication)?|développ(?:e|ement)|"
    r"architecture|conception|implémente?|fonctionn(?:e|ement|alité)?|"
    # Technos courantes
    r"api|rest|graphql|docker|kubernetes|k8s|fastapi|flask|django|"
    r"streamlit|gradio|chainlit|nodejs?|typescript|"
    r"github|gitlab|ci(?:[/_]?cd)?|pipeline|workflow|actions|"
    r"test(?:s|ing)?|pytest|unit\s?test|coverage|"
    # Data / IA
    r"data|donnée|database|sql|nosql|mongodb|postgres|"
    r"modèle|model|ia|ai|ml|mlops|machine[- ]?learning|deep[- ]?learning|"
    r"embedding|llm|rag|vector|qdrant|chroma|"
    # Production / monitoring
    r"déploi(?:e|ement)|monitoring|observabilité|prometheus|grafana|logs?|métri(?:que|cs)|"
    r"prod(?:uction)?|staging|incident|"
    # Auto-description (verbes 1ère personne)
    r"j'ai|mon\b|notre\b|nous\b|j'utilise|on\s+a\s|on\s+utilise"
    r")\b",
    re.IGNORECASE,
)


def _extract_competences(text: str) -> list[str]:
    """Extrait les codes compétence (C1-C21) mentionnés dans le texte.

    Filtre les codes hors plage valide (C0, C22, etc.) et déduplique
    en préservant l'ordre d'apparition.
    """
    found: list[str] = []
    seen: set[str] = set()
    for match in COMPETENCE_PATTERN.finditer(text):
        n = int(match.group(1))
        if 1 <= n <= 21:
            code = f"C{n}"
            if code not in seen:
                seen.add(code)
                found.append(code)
    return found


def detect_intent(query: str) -> IntentResult:
    """Classifie la question utilisateur dans une intention.

    Ordre de priorité (du plus spécifique au plus général) :
        1. META (questions sur la structure du référentiel lui-même)
        2. COMPARISON (mots-clés "compare" + ≥ 2 compétences)
        3. SPECIFIC_COMPETENCE (au moins 1 code C\\d mentionné)
        4. DEFINITION (mots-clés "c'est quoi", "définis"…)
        5. COVERAGE_ANALYSIS (mots-clés "quelles compétences", "couvre"…)
        6. GENERAL (fallback)

    Args:
        query: Question brute de l'utilisateur.

    Returns:
        IntentResult avec intent, compétences mentionnées et stratégie.
    """
    competences = _extract_competences(query)

    # 0. Small talk : "salut", "qui es-tu", "quel est ton rôle"
    #    Réponse pré-calculée, pas de RAG. On limite aux messages COURTS
    #    pour éviter de capturer "Bonjour, mon projet utilise FastAPI..."
    #    (qui doit être traité comme une vraie demande d'analyse).
    if SMALL_TALK_PATTERN.search(query) and len(query.strip()) <= 40:
        return IntentResult(intent=Intent.SMALL_TALK, bypass_rag=True, suggested_top_n=0)

    # 1. Méta : question sur la structure du référentiel
    if META_PATTERN.search(query):
        return IntentResult(intent=Intent.META, bypass_rag=True, suggested_top_n=0)

    # 1bis. Mode entretien jury : "/jury", "prépare-moi à la soutenance"
    if JURY_PATTERN.search(query):
        return IntentResult(
            intent=Intent.JURY_INTERVIEW,
            competences=competences,
            suggested_top_n=10,
        )

    # 2. Comparaison : "compare C13 et C19"
    if COMPARISON_PATTERN.search(query) and len(competences) >= 2:
        return IntentResult(
            intent=Intent.COMPARISON,
            competences=competences,
            suggested_top_n=len(competences) + 2,  # marge pour contexte
        )

    # 3. Compétence spécifique : "C13", "que dit C9"
    if competences:
        return IntentResult(
            intent=Intent.SPECIFIC_COMPETENCE,
            competences=competences,
            suggested_top_n=max(3, len(competences) + 1),
        )

    # 4. Définition générale : "c'est quoi le bloc MLOps"
    if DEFINITION_PATTERN.search(query):
        return IntentResult(intent=Intent.DEFINITION, suggested_top_n=3)

    # 5. Analyse de couverture : "quelles compétences couvre mon projet"
    if COVERAGE_PATTERN.search(query):
        return IntentResult(intent=Intent.COVERAGE_ANALYSIS, suggested_top_n=10)

    # 6. Fallback : retrieval hybrid standard
    # On vérifie aussi si la question contient au moins un signal "dans le scope"
    # (mots-clés RNCP/dev/IA). Sinon → réponse polie hors-scope au lieu d'un RAG bidon.
    in_scope = bool(SCOPE_KEYWORDS_PATTERN.search(query))
    return IntentResult(intent=Intent.GENERAL, suggested_top_n=10, in_scope=in_scope)


# ---------------------------------------------------------------------------
# Réponses pré-calculées pour les intentions META (pas besoin de RAG)
# ---------------------------------------------------------------------------
META_RESPONSE = """Le référentiel RNCP "Développeur en intelligence artificielle"
(titre 2023, Simplon) compte **21 compétences** réparties en **3 blocs** :

- **Bloc 1 — Données** (C1 à C5) : 5 compétences
  Extraction, requêtes SQL, préparation, BDD avec RGPD, API REST.
- **Bloc 2 — Modèles d'IA** (C6 à C13) : 8 compétences
  Veille technique, évaluation, modèles IA, API IA, intégration,
  monitoring modèle, tests, CI/CD modèle.
- **Bloc 3 — Application** (C14 à C21) : 8 compétences
  Analyse besoin, conception, coordination, composants/interfaces,
  tests application, CI/CD application, monitoring application,
  résolution d'incidents.

**Total : 21 compétences** ; chaque bloc peut être validé indépendamment."""


# Réponse pré-calculée pour SMALL_TALK (présentation conversationnelle du bot)
SMALL_TALK_RESPONSE = """Salut 👋 Je suis le **Chatbot RNCP Dev IA**.

Mon rôle : **analyser la couverture du référentiel RNCP "Développeur en
intelligence artificielle"** (titre 2023, Simplon) par un projet que tu me
décris ou dont tu me donnes le repo GitHub.

### Ce que je peux faire

- 🚀 **Analyser un repo GitHub** : colle l'URL, je clone, je détecte les
  technos (FastAPI, Docker, GitHub Actions, MLflow, etc.), et je te dis
  quelles compétences ton projet valide.
- 💬 **Analyser une description** : décris ton projet en français, même
  résultat.
- 🎓 **Mode entretien jury** : tape `/jury` pour que je te pose 5 questions
  techniques exigeantes — entraînement à la soutenance.
- 📋 **Question ciblée** : "C13 ?" pour le détail d'une compétence,
  "compare C13 et C19" pour une comparaison.
- 📥 **Rapport téléchargeable** Markdown (joignable au dossier de soutenance).

➡️ Vas-y, **colle ton URL GitHub ou décris ton projet**.
"""


# Réponse polie quand la question est clairement hors du scope du bot
# (météo, blagues, sujets non-RNCP, etc.) — évite un RAG bidon.
OUT_OF_SCOPE_RESPONSE = """Je suis spécialisé sur le **référentiel RNCP "Développeur en intelligence artificielle"**
(titre 2023, Simplon). Ta question semble hors de ce périmètre.

### Voici ce que je peux faire pour toi

- 🚀 **Analyser un repo GitHub** : colle l'URL → détection des technos + couverture RNCP
- 💬 **Analyser une description de projet** en langage naturel
- 🎓 **Mode entretien jury** : tape `/jury <projet>` pour t'entraîner à la soutenance
- 📋 **Question ciblée** : "C13 ?", "compare C13 et C19", "combien de blocs ?"

➡️ **Reformule** ta question dans ce cadre ou décris ton projet."""
