"""Pipeline d'indexation du référentiel RNCP dans Qdrant.

Ce module fait le travail UNIQUE qu'il faut faire AVANT de pouvoir poser des questions :
  1. Charger le PDF du référentiel via PyMuPDF
  2. Le découper en chunks par regex sur "C\\d+\\." (1 chunk = 1 compétence)
  3. Calculer les embeddings de chaque chunk via Mistral
  4. Stocker (texte + vecteur + métadonnées) dans Qdrant
  5. Sauvegarder le corpus en JSON pour BM25 (retrieval lexical hybride)

Ce script est lancé UNE FOIS au setup. Ensuite, le chatbot interroge l'index existant.

Usage :
    uv run python -m src.ingest

ou avec options :
    uv run python -m src.ingest --collection mon_index --recreate
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

import pymupdf  # alias officiel : `import fitz` mais déprécié en 2024
from langchain_core.documents import Document
from langchain_mistralai import MistralAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from src.config import (
    DATA_DIR,
    MISTRAL_API_KEY,
    MISTRAL_EMBED_MODEL,
    QDRANT_COLLECTION,
    QDRANT_URL,
    find_referentiel_pdf,
)

# Chemin du corpus BM25 sérialisé en JSON.
# On stocke les Documents bruts (page_content + metadata) pour reconstruire
# BM25Retriever au démarrage de l'app, sans avoir à re-parser le PDF.
# Format JSON pour la sécurité (lisible, portable, pas d'exécution de code arbitraire).
BM25_CORPUS_PATH = DATA_DIR / "bm25_corpus.json"

# Regex de séparation des compétences.
# Le `(?=...)` est un lookahead : on split AVANT chaque "C1.", "C2.", ..., "C21."
# en début de ligne, ce qui garantit que chaque chunk commence par son code.
COMPETENCE_PATTERN = re.compile(r"(?=^C\d+\.\s)", re.MULTILINE)

# Taille max d'un chunk (en caractères).
# Au-delà, on re-split avec RecursiveCharacterTextSplitter pour éviter :
#   - les chunks géants (16k+ caractères) qui saturent les embeddings
#   - le reranker qui retourne des scores nuls sur des séquences trop longues
MAX_CHUNK_SIZE = 1500
SUB_CHUNK_OVERLAP = 100

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Étape 1 : Load — chargement du PDF
# ---------------------------------------------------------------------------
def load_pdf(pdf_path: Path) -> list[Document]:
    """Charge le PDF et retourne une liste de Documents (un par page).

    On utilise PyMuPDF (fitz) plutôt que pypdf parce que pypdf perd les espaces
    sur certains PDF (polices vectorielles, encodage particulier — c'était notre
    cas avec le référentiel Simplon). PyMuPDF préserve mieux la mise en page.

    On garde la page comme métadonnée — utile pour citer la source en démo.
    """
    log.info(f"📖 Chargement du PDF : {pdf_path.name}")
    doc = pymupdf.open(pdf_path)
    documents: list[Document] = []

    for page_num, page in enumerate(doc, start=1):
        # `get_text("text")` extrait le texte brut en respectant l'ordre de lecture
        # et les espaces. Plus propre que `get_text()` qui peut concaténer sans séparateur.
        text = page.get_text("text")
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

    doc.close()
    log.info(f"   → {len(documents)} pages chargées")
    return documents


# ---------------------------------------------------------------------------
# Étape 2 : Split — découpage par compétence (regex)
# ---------------------------------------------------------------------------
def split_competences(documents: list[Document]) -> list[Document]:
    """Découpe le PDF en chunks où chaque chunk = une compétence (idéalement).

    Stratégie : on concatène tout le texte du PDF puis on split sur le pattern
    `^C\\d+\\.\\s` (Cxx. en début de ligne). Chaque chunk obtenu commence donc
    par un code de compétence (C1., C2., ..., C21.) et contient :
      - soit le LIBELLÉ complet de la compétence (cas idéal — pages 4-5 du PDF)
      - soit une mention de la compétence dans une annexe (grille d'évaluation)

    Métadonnée injectée :
      - `competence` : le code (ex: "C5") — utile pour filtrage Qdrant et citation

    Pourquoi pas RecursiveCharacterTextSplitter générique ?
        Avec chunk_size fixe, les libellés de compétence sont fragmentés sur
        plusieurs chunks (perdant l'ancrage "C5." en début), ce qui dégrade
        sévèrement le retrieval. Le split par regex garantit qu'une compétence
        reste atomique dans son chunk.
    """
    log.info("✂️  Découpage par compétence (regex sur ^C\\d+\\.)")

    # Sub-splitter pour les blocs trop gros (ex: tout ce qui suit C21. en fin de PDF
    # peut faire 16k caractères, ce qui sature les embeddings et le reranker).
    sub_splitter = RecursiveCharacterTextSplitter(
        chunk_size=MAX_CHUNK_SIZE,
        chunk_overlap=SUB_CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks: list[Document] = []
    # On split PAGE PAR PAGE plutôt que sur le texte global, ce qui permet de
    # préserver la métadonnée `page` pour la traçabilité (citation des sources).
    for page_doc in documents:
        page_num = page_doc.metadata.get("page")
        source = page_doc.metadata.get("source", "unknown")
        text = page_doc.page_content

        # Split sur le pattern (lookahead = "Cxx." reste au début de chaque part)
        parts = [p.strip() for p in COMPETENCE_PATTERN.split(text) if p.strip()]

        for part in parts:
            # Extraction du code de compétence (C1, C2, ..., C21)
            m = re.match(r"^(C\d+)\.", part)
            if not m:
                # Texte sans Cxx en début (préambule, milieu d'une compétence
                # qui chevauche la page précédente, etc.) — on l'ignore.
                continue
            code = m.group(1)
            metadata = {"source": source, "competence": code, "page": page_num}

            if len(part) <= MAX_CHUNK_SIZE:
                # Cas idéal : le bloc tient dans un seul chunk
                chunks.append(Document(page_content=part, metadata=metadata))
            else:
                # Bloc trop gros : on le sous-découpe en gardant le metadata
                # pour que chaque sous-chunk reste rattaché à sa compétence et sa page.
                sub_docs = sub_splitter.create_documents([part], metadatas=[metadata])
                chunks.extend(sub_docs)

    # Compter combien de compétences uniques on a capturées (pour debug)
    unique_codes = sorted({c.metadata["competence"] for c in chunks}, key=lambda x: int(x[1:]))
    log.info(f"   → {len(chunks)} chunks créés, {len(unique_codes)} compétences uniques")
    log.info(f"   → Compétences couvertes : {', '.join(unique_codes)}")
    return chunks


# ---------------------------------------------------------------------------
# Étape 2 bis : Sauvegarde du corpus pour BM25 (retrieval lexical hybride)
# ---------------------------------------------------------------------------
def save_bm25_corpus(chunks: list[Document]) -> None:
    """Sauvegarde les chunks au format JSON pour reconstruction BM25 au runtime.

    Pourquoi JSON et pas pickle ?
      - Lisible (debug et audit faciles)
      - Sécurisé (pas de risque d'exécution de code arbitraire à la deserialization)
      - Portable entre versions de Python et de LangChain

    Pourquoi sauvegarder le corpus et pas l'objet BM25Retriever ?
      - Le retriever est trivialement reconstructible (~50ms pour 30 chunks)
      - L'objet BM25Retriever sérialise mal entre versions de langchain_community
    """
    BM25_CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = [{"page_content": d.page_content, "metadata": d.metadata} for d in chunks]
    BM25_CORPUS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    log.info(f"💾 Corpus BM25 sauvegardé : {BM25_CORPUS_PATH.name} ({len(chunks)} chunks)")


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
    """Lance le pipeline complet Load → Split → Embed → Store + corpus BM25."""
    pdf_path = find_referentiel_pdf()

    documents = load_pdf(pdf_path)
    chunks = split_competences(documents)
    build_vector_store(chunks, collection_name=collection_name, recreate=recreate)
    save_bm25_corpus(chunks)

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
