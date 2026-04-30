"""Configuration centralisée du projet.

Toutes les variables d'environnement et constantes sont chargées ici, depuis le fichier .env.
On expose des constantes Python typées (pas des `os.getenv()` éparpillés dans le code) — c'est plus sûr,
plus testable, et ça remonte les erreurs de config tout de suite au démarrage.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Chargement du .env depuis la racine du projet (un seul appel pour tout le code)
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _required_env(name: str) -> str:
    """Lit une variable d'environnement OBLIGATOIRE et lève une erreur claire si absente.

    On préfère échouer au démarrage (fail-fast) plutôt que d'avoir un crash bizarre
    au moment du premier appel API.
    """
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Variable d'environnement '{name}' manquante. "
            f"Crée un fichier .env à la racine (voir .env.example)."
        )
    return value


def _int_env(name: str, default: int) -> int:
    """Lit une variable d'environnement entière, avec valeur par défaut."""
    return int(os.getenv(name, default))


def _float_env(name: str, default: float) -> float:
    """Lit une variable d'environnement flottante, avec valeur par défaut."""
    return float(os.getenv(name, default))


# ---------------------------------------------------------------------------
# Mistral API — LLM + embeddings
# ---------------------------------------------------------------------------
# Clé API : obligatoire (sinon impossible de faire des requêtes)
MISTRAL_API_KEY: str = _required_env("MISTRAL_API_KEY")

# Modèle de génération : mistral-small-latest est le sweet spot perf/coût pour du français
MISTRAL_LLM_MODEL: str = os.getenv("MISTRAL_LLM_MODEL", "mistral-small-latest")

# Modèle d'embeddings : mistral-embed est multilingue (entraîné sur du français)
MISTRAL_EMBED_MODEL: str = os.getenv("MISTRAL_EMBED_MODEL", "mistral-embed")


# ---------------------------------------------------------------------------
# Qdrant — vector store
# ---------------------------------------------------------------------------
# URL du serveur Qdrant : http://localhost:6333 en dev, http://qdrant:6333 dans Docker
QDRANT_URL: str = os.getenv("QDRANT_URL", "http://localhost:6333")

# Nom de la collection (équivalent d'une "table" en SQL — un namespace pour nos vecteurs)
QDRANT_COLLECTION: str = os.getenv("QDRANT_COLLECTION", "referentiel_rncp")


# ---------------------------------------------------------------------------
# Paramètres RAG — chaque valeur est justifiable en soutenance
# ---------------------------------------------------------------------------
# Taille des chunks (en caractères) : 512 = sweet spot identifié dans les benchmarks 2026
# - trop petit (<300) : pas assez de contexte par chunk
# - trop grand (>1000) : le LLM se "noie" dans des chunks bruyants
CHUNK_SIZE: int = _int_env("CHUNK_SIZE", 512)

# Chevauchement entre chunks (en caractères) : ~15% de chunk_size
# Sert à préserver le contexte aux frontières — sans overlap, une phrase importante
# coupée en deux peut perdre son sens dans le chunk suivant.
CHUNK_OVERLAP: int = _int_env("CHUNK_OVERLAP", 80)

# Nombre de chunks retournés par le retriever pour chaque question
# 4 = bon compromis : assez de contexte, pas trop de bruit
RETRIEVAL_K: int = _int_env("RETRIEVAL_K", 4)

# Seuil minimum de similarité — sous ce score, un chunk est rejeté
# Garde-fou anti-hallucination : si la question est hors-sujet, retriever retourne []
# et le LLM peut dire "je ne sais pas" plutôt que d'inventer.
SCORE_THRESHOLD: float = _float_env("SCORE_THRESHOLD", 0.4)


# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------
DATA_DIR: Path = ROOT_DIR / "data"


# Le PDF du référentiel (à placer dans data/)
# On accepte n'importe quel PDF dans le dossier — utile si Simplon met à jour le référentiel.
def find_referentiel_pdf() -> Path:
    """Trouve le PDF du référentiel dans data/. Lève une erreur si aucun trouvé."""
    pdfs = list(DATA_DIR.glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(
            f"Aucun PDF trouvé dans {DATA_DIR}. "
            "Place le référentiel RNCP dans data/ (par exemple data/referentiel-rncp-dev-ia.pdf)."
        )
    if len(pdfs) > 1:
        # On prend le premier mais on prévient — utile pour debug
        print(f"⚠️  Plusieurs PDF trouvés, utilisation de {pdfs[0].name}")
    return pdfs[0]
