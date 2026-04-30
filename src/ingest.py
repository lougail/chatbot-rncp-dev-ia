"""Pipeline d'indexation du référentiel RNCP dans Qdrant.

Ce module fait le travail UNIQUE qu'il faut faire AVANT de pouvoir poser des questions :
  1. Charger le PDF du référentiel
  2. Le découper en chunks (RecursiveCharacterTextSplitter de LangChain)
  3. Calculer les embeddings de chaque chunk via Mistral
  4. Stocker (texte + vecteur + métadonnées) dans Qdrant

Ce script est lancé UNE FOIS au setup. Ensuite, le chatbot interroge l'index existant.

Usage :
    uv run python -m src.ingest

ou via le main :
    uv run python -m src.ingest --collection mon_index --recreate
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from langchain_core.documents import Document
from langchain_mistralai import MistralAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from src.config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    MISTRAL_API_KEY,
    MISTRAL_EMBED_MODEL,
    QDRANT_COLLECTION,
    QDRANT_URL,
    find_referentiel_pdf,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Étape 1 : Load — chargement du PDF
# ---------------------------------------------------------------------------
def load_pdf(pdf_path: Path) -> list[Document]:
    """Charge le PDF et retourne une liste de Documents (un par page).

    On garde la page comme métadonnée — utile pour citer la source en démo.
    """
    log.info(f"📖 Chargement du PDF : {pdf_path.name}")
    reader = PdfReader(pdf_path)
    documents: list[Document] = []

    for page_num, page in enumerate(reader.pages, start=1):
        text = page.extract_text()
        if not text or not text.strip():
            # Pages vides ou avec uniquement des images — on saute
            continue

        documents.append(
            Document(
                page_content=text,
                metadata={
                    "source": pdf_path.name,
                    "page": page_num,
                },
            )
        )

    log.info(f"   → {len(documents)} pages chargées")
    return documents


# ---------------------------------------------------------------------------
# Étape 2 : Split — découpage en chunks
# ---------------------------------------------------------------------------
def split_documents(documents: list[Document]) -> list[Document]:
    """Découpe les documents en chunks de ~CHUNK_SIZE caractères avec un overlap.

    On utilise RecursiveCharacterTextSplitter qui essaie de couper sur les
    séparateurs naturels du texte (paragraphes > phrases > mots) avant de
    couper au milieu d'un mot.

    Pourquoi l'overlap ?
        Pour préserver le contexte aux frontières des chunks. Sans overlap,
        une phrase importante coupée en deux peut perdre son sens.
    """
    log.info(f"✂️  Découpage en chunks (size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP})")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        # Séparateurs ordonnés du plus "fort" au plus "faible"
        # Le splitter essaie d'abord \n\n (paragraphe), puis \n (ligne), etc.
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(documents)

    log.info(f"   → {len(chunks)} chunks créés")
    return chunks


# ---------------------------------------------------------------------------
# Étape 3 + 4 : Embed + Store — vectorisation et stockage dans Qdrant
# ---------------------------------------------------------------------------
def build_vector_store(
    chunks: list[Document],
    *,
    collection_name: str = QDRANT_COLLECTION,
    recreate: bool = False,
) -> QdrantVectorStore:
    """Crée la collection Qdrant et indexe tous les chunks.

    Si la collection existe déjà :
      - recreate=False (défaut) : on lève une erreur (sécurité, on n'écrase pas)
      - recreate=True : on la supprime et on recrée

    On utilise mistral-embed (1024 dimensions, multilingue, FR-friendly).
    """
    log.info(f"🔌 Connexion à Qdrant ({QDRANT_URL})")
    client = QdrantClient(url=QDRANT_URL)

    # Vérifier si la collection existe déjà
    collections = [c.name for c in client.get_collections().collections]
    if collection_name in collections:
        if recreate:
            log.info(f"🗑️  Suppression de la collection existante '{collection_name}'")
            client.delete_collection(collection_name)
        else:
            raise RuntimeError(
                f"La collection '{collection_name}' existe déjà. "
                "Utilise --recreate pour l'écraser, ou choisis un autre nom."
            )

    # Créer la collection avec les bonnes dimensions
    # mistral-embed produit des vecteurs de 1024 dimensions
    log.info(f"🆕 Création de la collection '{collection_name}'")
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(
            size=1024,  # dimensions de mistral-embed
            distance=Distance.COSINE,  # similarité cosinus (standard pour embeddings)
        ),
    )

    # Embedder + stocker en une fois
    log.info(f"🧠 Calcul des embeddings via {MISTRAL_EMBED_MODEL} et indexation Qdrant")
    embeddings = MistralAIEmbeddings(
        model=MISTRAL_EMBED_MODEL,
        api_key=MISTRAL_API_KEY,
    )

    vector_store = QdrantVectorStore(
        client=client,
        collection_name=collection_name,
        embedding=embeddings,
    )

    # add_documents() s'occupe de tout : embed + insert
    # Mistral facture quelques centimes pour ~200 chunks, c'est négligeable
    vector_store.add_documents(chunks)

    log.info(f"✅ {len(chunks)} chunks indexés dans Qdrant")
    return vector_store


# ---------------------------------------------------------------------------
# Pipeline complet
# ---------------------------------------------------------------------------
def run_ingestion(*, collection_name: str = QDRANT_COLLECTION, recreate: bool = False) -> None:
    """Lance le pipeline complet Load → Split → Embed → Store."""
    pdf_path = find_referentiel_pdf()

    documents = load_pdf(pdf_path)
    chunks = split_documents(documents)
    build_vector_store(chunks, collection_name=collection_name, recreate=recreate)

    log.info("🎉 Indexation terminée. Tu peux maintenant lancer l'app : `chainlit run app.py`")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Indexe le référentiel RNCP dans Qdrant")
    parser.add_argument(
        "--collection",
        default=QDRANT_COLLECTION,
        help=f"Nom de la collection Qdrant (défaut : {QDRANT_COLLECTION})",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Supprime la collection existante avant de réindexer",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_ingestion(collection_name=args.collection, recreate=args.recreate)
